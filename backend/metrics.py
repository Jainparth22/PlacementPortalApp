"""Prometheus metrics (RED: Rate, Errors, Duration) + live gauges for the queue, DLQ, outbox and SSE.

* ``instrument(app)`` adds request counters/histograms (labelled by the ROUTE TEMPLATE, never the raw URL, so
  cardinality stays bounded) and the ``/metrics`` endpoint.
* A custom collector computes gauges at scrape time (queue depth, dead letters, pending outbox rows, workers,
  Redis up/down, open SSE streams) - always current, no background threads.
* Celery task metrics are exposed by Flower's own ``/metrics`` (scraped by the same Prometheus), so the worker
  processes don't need an HTTP server.
* Multi-process gunicorn: set ``PROMETHEUS_MULTIPROC_DIR`` (the Docker entrypoint does) and counters/histograms
  are aggregated across workers.
* ``/metrics`` access: ``Authorization: Bearer <METRICS_TOKEN>``. With no token it is open in development and
  **disabled in production** (a metrics endpoint leaks internals).
"""
import hmac
import logging
import os
import time

from flask import Response, g, jsonify, request
from prometheus_client import (CONTENT_TYPE_LATEST, CollectorRegistry, Counter, Gauge, Histogram, generate_latest)
from prometheus_client.core import GaugeMetricFamily

log = logging.getLogger(__name__)

_MULTIPROC = bool(os.environ.get('PROMETHEUS_MULTIPROC_DIR'))
REGISTRY = CollectorRegistry(auto_describe=True)

REQUESTS = Counter('ppa_http_requests_total', 'HTTP requests', ['method', 'route', 'status'], registry=REGISTRY)
LATENCY = Histogram('ppa_http_request_duration_seconds', 'HTTP request latency', ['method', 'route'], registry=REGISTRY,
                    buckets=(.005, .01, .025, .05, .1, .25, .5, 1, 2.5, 5, 10))
IN_FLIGHT = Gauge('ppa_http_requests_in_flight', 'Requests currently being served', registry=REGISTRY,
                  **({'multiprocess_mode': 'livesum'} if _MULTIPROC else {}))
CACHE = Counter('ppa_cache_requests_total', 'Cache lookups', ['result'], registry=REGISTRY)          # hit | miss
LOGINS = Counter('ppa_logins_total', 'Login attempts', ['result'], registry=REGISTRY)                # success | failed | locked
RATE_LIMITED = Counter('ppa_rate_limited_total', 'Requests rejected by a rate limiter', ['scope'], registry=REGISTRY)
IDEMPOTENT_REPLAYS = Counter('ppa_idempotent_replays_total', 'Responses replayed from an Idempotency-Key', registry=REGISTRY)
OUTBOX_PUBLISHED = Counter('ppa_outbox_events_published_total', 'Outbox events relayed to the event bus', registry=REGISTRY)
TASK_FALLBACKS = Counter('ppa_task_sync_fallbacks_total', 'Tasks run inline because no worker was available', registry=REGISTRY)


def inc(counter, *labels, amount=1):
    """Best-effort increment: metrics must never break a request."""
    try:
        (counter.labels(*labels) if labels else counter).inc(amount)
    except Exception:  # noqa: BLE001
        pass


# --------------------------------------------------------------------------- scrape-time gauges
class LiveCollector:
    """Gauges that are computed when Prometheus scrapes, so they are always current."""

    def collect(self):
        from cache import _call, redis_health
        from flask import current_app
        up = GaugeMetricFamily('ppa_redis_up', '1 if the Redis role answers PING', labels=['role'])
        for role, state in redis_health().items():
            up.add_metric([role], 1 if state == 'connected' else 0)
        yield up

        depth = GaugeMetricFamily('ppa_celery_queue_depth', 'Tasks waiting in the Celery queue', labels=['queue'])
        try:
            depth.add_metric(['ppa'], _queue_len(current_app.config['CELERY_BROKER_URL']))
            yield depth
        except Exception:  # noqa: BLE001 - broker down: the ppa_redis_up gauge already says so
            pass

        dlq = GaugeMetricFamily('ppa_dead_letter_depth', 'Permanently failed tasks awaiting review')
        res, ok = _call('state', lambda r: r.llen('ppa:dead_letter'))
        if ok:
            dlq.add_metric([], res)
            yield dlq

        try:
            from models import OutboxEvent
            pending = OutboxEvent.query.filter(OutboxEvent.published_at.is_(None)).count()
            g_pending = GaugeMetricFamily('ppa_outbox_pending', 'Outbox events not yet published (should hover near 0)')
            g_pending.add_metric([], pending)
            yield g_pending
        except Exception:  # noqa: BLE001 - schema not ready etc.
            pass

        import events
        sse = GaugeMetricFamily('ppa_sse_connections', 'Open live-notification streams in this process')
        sse.add_metric([], events.active_connections())
        yield sse

        try:
            from async_dispatch import worker_count
            workers = GaugeMetricFamily('ppa_celery_workers', 'Celery workers answering a ping (cached 15s)')
            workers.add_metric([], worker_count())
            yield workers
        except Exception:  # noqa: BLE001
            pass


def _queue_len(broker_url):
    """LLEN of the default queue on the broker DB (a different logical DB than the state Redis)."""
    import redis
    client = redis.Redis.from_url(broker_url, socket_connect_timeout=1, socket_timeout=1)
    try:
        return client.llen('ppa')
    finally:
        client.close()


_live = LiveCollector()


def _render():
    if _MULTIPROC:
        from prometheus_client import multiprocess
        reg = CollectorRegistry()
        multiprocess.MultiProcessCollector(reg)
    else:
        reg = REGISTRY
    out = generate_latest(reg)
    # live gauges live in a throw-away registry so they're evaluated once per scrape, in this process
    live = CollectorRegistry()
    live.register(_live)
    return out + generate_latest(live)


def _authorized(app):
    token = app.config.get('METRICS_TOKEN')
    if not token:
        return app.config.get('ENV_NAME') != 'production'
    header = request.headers.get('Authorization', '')
    return header.startswith('Bearer ') and hmac.compare_digest(header[7:].strip(), token)


def instrument(app):
    if not app.config.get('METRICS_ENABLED', True):
        return

    @app.before_request
    def _metrics_start():
        g._m_start = time.perf_counter()
        IN_FLIGHT.inc()

    @app.teardown_request
    def _metrics_end(exc):
        IN_FLIGHT.dec()

    @app.after_request
    def _metrics_record(resp):
        if request.path == '/metrics':
            return resp
        rule = request.url_rule.rule if request.url_rule else 'unmatched'
        if request.path.startswith('/static/'):
            rule = '/static/*'
        elapsed = time.perf_counter() - getattr(g, '_m_start', time.perf_counter())
        inc(REQUESTS, request.method, rule, str(resp.status_code))
        try:
            LATENCY.labels(request.method, rule).observe(elapsed)
        except Exception:  # noqa: BLE001
            pass
        return resp

    @app.route('/metrics')
    def metrics_endpoint():
        if not _authorized(app):
            return (jsonify({'error': 'Not found'}), 404) if not app.config.get('METRICS_TOKEN') else (jsonify({'error': 'Unauthorized'}), 401)
        return Response(_render(), mimetype=CONTENT_TYPE_LATEST)
