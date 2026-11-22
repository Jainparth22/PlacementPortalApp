"""Prometheus metrics and OpenTelemetry tracing."""
import re

import pytest

import cache
import events
import tracing
from conftest import login, bearer, make_drive


def _metrics(client, headers=None):
    resp = client.get('/metrics', headers=headers or {})
    return resp, resp.get_data(as_text=True)


def _value(text, name, **labels):
    """Sum of samples of ``name`` whose labels include ``labels``."""
    total = 0.0
    for line in text.splitlines():
        if line.startswith('#') or not line.startswith(name):
            continue
        m = re.match(r'^' + re.escape(name) + r'(\{[^}]*\})?\s+([0-9.eE+-]+)$', line)
        if not m:
            continue
        have = dict(re.findall(r'(\w+)="([^"]*)"', m.group(1) or ''))
        if all(have.get(k) == v for k, v in labels.items()):
            total += float(m.group(2))
    return total


# ------------------------------------------------------------------ RED metrics
def test_requests_are_counted_by_route_template_not_raw_url(client, student, company):
    drive = make_drive(company)
    token = login(client, 'stu@example.com')
    for _ in range(3):
        client.post(f'/api/v1/student/apply/{drive.id}', json={}, headers=bearer(token))
    _, text = _metrics(client)
    # one label value for all drive ids => bounded cardinality
    assert _value(text, 'ppa_http_requests_total', route='/api/student/apply/<int:drive_id>', method='POST') >= 3
    assert str(drive.id) not in ''.join(re.findall(r'route="[^"]*"', text)) or '<int:drive_id>' in text
    assert _value(text, 'ppa_http_requests_total', route='/api/student/apply/<int:drive_id>', status='201') >= 1
    assert _value(text, 'ppa_http_requests_total', route='/api/student/apply/<int:drive_id>', status='409') >= 1


def test_latency_histogram_has_buckets_sum_and_count(client):
    client.get('/health')
    _, text = _metrics(client)
    assert 'ppa_http_request_duration_seconds_bucket{' in text
    assert _value(text, 'ppa_http_request_duration_seconds_count', route='/health') >= 1
    assert _value(text, 'ppa_http_request_duration_seconds_sum', route='/health') > 0


def test_unknown_urls_do_not_explode_label_cardinality(client):
    for i in range(5):
        client.get(f'/api/v1/random-{i}')
    _, text = _metrics(client)
    assert 'random-' not in text and _value(text, 'ppa_http_requests_total', route='unmatched') >= 5


def test_metrics_endpoint_does_not_count_itself(client):
    _metrics(client)
    _, text = _metrics(client)
    assert _value(text, 'ppa_http_requests_total', route='/metrics') == 0


# ------------------------------------------------------------------ access control
def test_metrics_open_in_dev_without_token(client):
    assert client.get('/metrics').status_code == 200


def test_metrics_requires_bearer_when_token_configured(client, app):
    app.config['METRICS_TOKEN'] = 's3cret-token'
    try:
        assert client.get('/metrics').status_code == 401
        assert client.get('/metrics', headers=bearer('wrong')).status_code == 401
        assert client.get('/metrics', headers=bearer('s3cret-token')).status_code == 200
    finally:
        app.config['METRICS_TOKEN'] = ''


def test_metrics_disabled_in_production_without_token(client, app):
    app.config['ENV_NAME'] = 'production'
    try:
        assert client.get('/metrics').status_code == 404
    finally:
        app.config['ENV_NAME'] = 'development'


# ------------------------------------------------------------------ business + infrastructure signals
def test_cache_hit_and_miss_counters(client, app):
    _, before = _metrics(client)
    cache.cache_get('nope')
    cache.cache_set('yes', 1)
    cache.cache_get('yes')
    _, after = _metrics(client)
    assert _value(after, 'ppa_cache_requests_total', result='miss') > _value(before, 'ppa_cache_requests_total', result='miss')
    assert _value(after, 'ppa_cache_requests_total', result='hit') > _value(before, 'ppa_cache_requests_total', result='hit')


def test_login_and_rate_limit_counters(client, app, student):
    app.config['LOGIN_RATE_LIMIT'] = 2
    client.post('/api/v1/auth/login', json={'email': 'stu@example.com', 'password': 'Passw0rd!'})
    client.post('/api/v1/auth/login', json={'email': 'stu@example.com', 'password': 'bad-bad'})
    client.post('/api/v1/auth/login', json={'email': 'stu@example.com', 'password': 'bad-bad'})   # 3rd -> limited
    _, text = _metrics(client)
    assert _value(text, 'ppa_logins_total', result='success') >= 1
    assert _value(text, 'ppa_logins_total', result='failed') >= 1
    assert _value(text, 'ppa_rate_limited_total', scope='login-ip') >= 1


def test_live_gauges_present_and_correct(client, app, student, fake_redis):
    app.config['STATE_REDIS_URL'] = 'redis://configured'
    from dead_letter import push_dead_letter
    push_dead_letter('tasks.x', 'id1', [], {}, RuntimeError('boom'))
    events.notify(student.id, 'pending one')
    from models import db
    db.session.commit()                         # committed but not relayed => outbox backlog of 1
    assert events.try_acquire_connection(5)
    _, text = _metrics(client)
    assert _value(text, 'ppa_redis_up', role='cache') == 1 and _value(text, 'ppa_redis_up', role='state') == 1
    assert _value(text, 'ppa_dead_letter_depth') == 1
    assert _value(text, 'ppa_outbox_pending') == 1
    assert _value(text, 'ppa_sse_connections') == 1
    assert 'ppa_celery_workers' in text
    events.release_connection()


def test_redis_down_is_visible_as_a_gauge(client):
    _, text = _metrics(client)                  # tests run without Redis
    assert _value(text, 'ppa_redis_up', role='cache') == 0


def test_metrics_never_break_requests(client, monkeypatch):
    import metrics
    monkeypatch.setattr(metrics.REQUESTS, 'labels', lambda *a, **k: (_ for _ in ()).throw(RuntimeError('prom down')))
    assert client.get('/health').status_code == 200


# ------------------------------------------------------------------ tracing
@pytest.fixture()
def traced(app):
    """A FRESH Flask app instrumented with an in-memory exporter (Flask refuses new hooks after the first request,
    and the shared test app has already served requests)."""
    from app import create_app
    from opentelemetry.instrumentation.flask import FlaskInstrumentor
    from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
    exporter = InMemorySpanExporter()
    fresh = create_app({'SKIP_BOOTSTRAP': True, 'TESTING': True, 'REDIS_URL': '', 'STATE_REDIS_URL': '', 'FORCE_SYNC_TASKS': True})
    tracing._initialised = False
    assert tracing.init_tracing(fresh, exporter=exporter)
    yield fresh, exporter
    FlaskInstrumentor().uninstrument_app(fresh)
    tracing.uninstrument()


def test_a_request_produces_flask_and_database_spans_in_one_trace(student, traced):
    fresh, exporter = traced
    resp = fresh.test_client().post('/api/v1/auth/login', json={'email': 'stu@example.com', 'password': 'Passw0rd!'})
    assert resp.status_code == 200
    finished = exporter.get_finished_spans()
    names = [s.name for s in finished]
    root = next((s for s in finished if 'login' in s.name), None)
    assert root is not None, names                                           # Flask server span, named by route
    in_trace = [s for s in finished if s.context.trace_id == root.context.trace_id and s is not root]
    assert in_trace, names                                                   # DB spans hang under the request span
    assert any(s.attributes.get('db.system') for s in in_trace), [s.attributes for s in in_trace]


def test_health_and_metrics_are_not_traced(app, traced):
    fresh, exporter = traced
    c = fresh.test_client()
    c.get('/health')
    c.get('/metrics')
    assert not [s for s in exporter.get_finished_spans() if s.name.endswith('/health') or s.name.endswith('/metrics')]


def test_trace_id_is_available_to_logs_inside_a_span(app, traced):
    from opentelemetry import trace
    assert tracing.current_trace_id() is None
    with trace.get_tracer('t').start_as_current_span('work'):
        tid = tracing.current_trace_id()
    assert tid and re.fullmatch(r'[0-9a-f]{32}', tid)


def test_tracing_is_off_unless_configured(app, monkeypatch):
    monkeypatch.delenv('OTEL_EXPORTER_OTLP_ENDPOINT', raising=False)
    tracing._initialised = False
    assert tracing.init_tracing(app) is False
