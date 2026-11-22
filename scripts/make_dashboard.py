#!/usr/bin/env python
"""Generates observability/grafana/dashboards/ppa.json (RED metrics + queue/DLQ/outbox/Redis health).
Run `python scripts/make_dashboard.py` after editing the panel list below, then restart Grafana."""
import json
import os

DS = {"type": "prometheus", "uid": "prometheus"}


def panel(i, title, exprs, x, y, w=12, h=8, unit=None, kind="timeseries", desc=None):
    p = {
        "id": i, "title": title, "type": kind, "datasource": DS, "gridPos": {"x": x, "y": y, "w": w, "h": h},
        "targets": [{"refId": chr(65 + k), "expr": e, "legendFormat": legend, "datasource": DS} for k, (e, legend) in enumerate(exprs)],
        "fieldConfig": {"defaults": {"unit": unit or "short"}, "overrides": []},
        "options": {"legend": {"displayMode": "list", "placement": "bottom"}},
    }
    if desc:
        p["description"] = desc
    if kind == "stat":
        p["options"] = {"reduceOptions": {"calcs": ["lastNotNull"]}, "colorMode": "value"}
    return p


PANELS = [
    panel(1, "Requests / sec by route", [('sum(rate(ppa_http_requests_total[1m])) by (route)', '{{route}}')], 0, 0, unit="reqps", desc="RED: Rate"),
    panel(2, "Error ratio (5xx)", [('sum(rate(ppa_http_requests_total{status=~"5.."}[5m])) / sum(rate(ppa_http_requests_total[5m]))', '5xx ratio')], 12, 0, unit="percentunit", desc="RED: Errors"),
    panel(3, "Latency p50 / p95 / p99", [
        ('histogram_quantile(0.50, sum(rate(ppa_http_request_duration_seconds_bucket[5m])) by (le))', 'p50'),
        ('histogram_quantile(0.95, sum(rate(ppa_http_request_duration_seconds_bucket[5m])) by (le))', 'p95'),
        ('histogram_quantile(0.99, sum(rate(ppa_http_request_duration_seconds_bucket[5m])) by (le))', 'p99')], 0, 8, unit="s", desc="RED: Duration"),
    panel(4, "Slowest routes (p95)", [('topk(8, histogram_quantile(0.95, sum(rate(ppa_http_request_duration_seconds_bucket[5m])) by (le, route)))', '{{route}}')], 12, 8, unit="s"),
    panel(5, "Cache hit ratio", [('sum(rate(ppa_cache_requests_total{result="hit"}[5m])) / sum(rate(ppa_cache_requests_total[5m]))', 'hit ratio')], 0, 16, w=8, unit="percentunit", desc="Cache-aside effectiveness (namespace-versioned keys)"),
    panel(6, "Cache lookups / sec", [('sum(rate(ppa_cache_requests_total[1m])) by (result)', '{{result}}')], 8, 16, w=8, unit="ops"),
    panel(7, "In-flight requests", [('sum(ppa_http_requests_in_flight)', 'in flight')], 16, 16, w=8),
    panel(8, "Celery queue depth", [('ppa_celery_queue_depth', 'waiting')], 0, 24, w=6, kind="stat", desc="Tasks waiting for a worker"),
    panel(9, "Celery workers online", [('ppa_celery_workers', 'workers')], 6, 24, w=6, kind="stat", desc="0 = jobs run inline in the web request"),
    panel(10, "Dead letters", [('ppa_dead_letter_depth', 'failed tasks')], 12, 24, w=6, kind="stat", desc="Should be 0. Review: GET /api/v1/admin/dead-letters"),
    panel(11, "Outbox backlog", [('ppa_outbox_pending', 'pending events')], 18, 24, w=6, kind="stat", desc="Live-notification events not yet relayed; should hover near 0"),
    panel(12, "Redis up (by role)", [('ppa_redis_up', '{{role}}')], 0, 32, w=8, desc="1 = reachable. Roles: cache, state"),
    panel(13, "Open SSE streams", [('ppa_sse_connections', 'streams')], 8, 32, w=8),
    panel(14, "Logins & rate limiting", [('sum(rate(ppa_logins_total[5m])) by (result)', 'login {{result}}'),
                                         ('sum(rate(ppa_rate_limited_total[5m])) by (scope)', 'limited {{scope}}')], 16, 32, w=8, unit="ops"),
    panel(15, "Idempotent replays / inline tasks / outbox relayed", [
        ('rate(ppa_idempotent_replays_total[5m])', 'idempotent replays'),
        ('rate(ppa_task_sync_fallbacks_total[5m])', 'tasks run inline'),
        ('rate(ppa_outbox_events_published_total[5m])', 'outbox published')], 0, 40, w=12, unit="ops"),
    panel(16, "Celery task outcomes (from Flower)", [('sum(rate(flower_events_total{type=~"task-succeeded|task-failed|task-retried"}[5m])) by (type)', '{{type}}')],
          12, 40, w=12, unit="ops", desc="Needs the Flower service (docker compose --profile observability up)"),
]

DASHBOARD = {
    "uid": "ppa-overview", "title": "PPA - Service overview", "tags": ["ppa"], "timezone": "browser", "schemaVersion": 39, "version": 1,
    "refresh": "15s", "time": {"from": "now-1h", "to": "now"}, "panels": PANELS, "templating": {"list": []}, "annotations": {"list": []},
    "links": [{"title": "Traces (Jaeger)", "url": "http://localhost:16686", "type": "link", "targetBlank": True}],
}

if __name__ == '__main__':
    out = os.path.join(os.path.dirname(__file__), '..', 'observability', 'grafana', 'dashboards', 'ppa.json')
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(out, 'w', encoding='utf-8') as f:
        json.dump(DASHBOARD, f, indent=1)
    print(f'wrote {os.path.abspath(out)} ({len(PANELS)} panels)')
