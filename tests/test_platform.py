"""Cross-cutting behaviour: headers, versioning, CORS, health, sanitising, SQL-injection audit, config."""
import os
import re

import pytest

from conftest import ROOT, login, bearer
from validators import clean_text, clean_list


def test_request_id_generated_and_echoed(client):
    resp = client.get('/health')
    assert re.fullmatch(r'[0-9a-f]{32}', resp.headers['X-Request-ID'])
    resp = client.get('/health', headers={'X-Request-ID': 'trace-abc-12345'})
    assert resp.headers['X-Request-ID'] == 'trace-abc-12345'
    resp = client.get('/health', headers={'X-Request-ID': 'bad id!!<script>'})
    assert resp.headers['X-Request-ID'] != 'bad id!!<script>'


def test_response_time_header(client):
    assert re.fullmatch(r'\d+ms', client.get('/health').headers['X-Response-Time'])


def test_api_v1_prefix_and_deprecated_alias(client, student):
    v1 = client.post('/api/v1/auth/login', json={'email': 'stu@example.com', 'password': 'Passw0rd!'})
    assert v1.status_code == 200 and v1.headers['X-API-Version'] == 'v1' and 'Deprecation' not in v1.headers
    legacy = client.post('/api/auth/login', json={'email': 'stu@example.com', 'password': 'Passw0rd!'})
    assert legacy.status_code == 200 and legacy.headers['Deprecation'] == 'true'
    assert '/api/v1/auth/login' in legacy.headers['Link']


def test_api_responses_are_not_browser_cached(client):
    assert client.get('/api/v1/auth/me').headers['Cache-Control'] == 'no-store'


def test_unknown_api_route_is_json_404(client):
    resp = client.get('/api/v1/nope')
    assert resp.status_code == 404 and resp.get_json() == {'error': 'Not found'}


def test_cors_disabled_by_default(client):
    resp = client.options('/api/v1/auth/login', headers={'Origin': 'https://evil.example', 'Access-Control-Request-Method': 'POST'})
    assert 'Access-Control-Allow-Origin' not in resp.headers


def test_health_reports_all_dependencies(client):
    data = client.get('/health').get_json()
    assert data['status'] == 'ok'
    assert data['database'] == 'connected'
    assert set(data['redis']) == {'cache', 'state'}
    assert 'workers' in data['celery'] and data['celery']['mode'] == 'sync-fallback'
    assert 'hit_rate' in data['cache']


def test_health_with_redis(client, fake_redis):
    data = client.get('/health').get_json()
    assert data['redis'] == {'cache': 'connected', 'state': 'connected'}
    assert data['cache']['backend'] == 'redis'


def test_unhandled_exception_is_json_500_with_request_id(client, student, monkeypatch):
    import routes.student as s
    monkeypatch.setattr(s, 'StudentProfile', None)       # force a crash inside a handler
    token = login(client, 'stu@example.com')
    resp = client.get('/api/v1/students/profile', headers=bearer(token))
    assert resp.status_code == 500 and resp.get_json()['request_id']
    assert 'Traceback' not in resp.get_data(as_text=True)


# ------------------------------------------------------------------ sanitisation
@pytest.mark.parametrize('raw,expected', [
    ('hello', 'hello'),
    ('<script>alert(1)</script>Bob', 'alert(1)Bob'),
    ('<<b>script>alert(1)<</b>/script>', 'script>alert(1)/script>'.replace('>', '').replace('<', '')),
    ('a\x00b\x07c', 'abc'),
    ('  spaced  ', 'spaced'),
    ('<img src=x onerror=alert(1)>', ''),
])
def test_clean_text(raw, expected):
    out = clean_text(raw)
    assert '<' not in out and '>' not in out
    assert out == expected


def test_clean_text_limits_and_types():
    assert clean_text('x' * 500, 10) == 'x' * 10
    assert clean_text(None) is None and clean_text(5) == 5
    assert clean_list(['a', '<b>b</b>', '', 3, 'c'] + ['z'] * 100) == ['a', 'b', 'c'] + ['z'] * 45


def test_reminder_email_escapes_html(app, student, company, monkeypatch):
    from datetime import datetime, timedelta
    import tasks
    from conftest import make_drive
    sent = []
    monkeypatch.setattr(tasks, 'send_email', lambda subject, to, body: sent.append(body) or True)
    make_drive(company, drive_name='<script>steal()</script>', deadline=datetime.utcnow() + timedelta(days=1))
    tasks.send_daily_reminders()
    assert sent and '<script>' not in sent[0] and '&lt;script&gt;' in sent[0]


# ------------------------------------------------------------------ SQL-injection audit
def test_no_raw_sql_string_building_in_backend():
    """Every query must go through the ORM / bound parameters. Allowed: the constant `SELECT 1` health probe."""
    offenders = []
    pattern = re.compile(r'(\.execute\(|text\()\s*(f["\']|["\'].*(%s|\{|\+))', re.I)
    for folder, _, files in os.walk(os.path.join(ROOT, 'backend')):
        if 'migrations' in folder or 'venv' in folder:
            continue
        for name in files:
            if name.endswith('.py'):
                for no, line in enumerate(open(os.path.join(folder, name), encoding='utf-8'), 1):
                    if pattern.search(line):
                        offenders.append(f'{name}:{no}: {line.strip()}')
    assert not offenders, offenders


def test_search_input_with_sql_metacharacters_is_harmless(client, student, company):
    from conftest import make_drive
    make_drive(company, drive_name='Alpha')
    token = login(client, 'stu@example.com')
    resp = client.get("/api/v1/student/drives?search=' OR 1=1; DROP TABLE users;--", headers=bearer(token))
    assert resp.status_code == 200 and resp.get_json()['total'] == 0
    assert client.get('/api/v1/auth/me', headers=bearer(token)).status_code == 200      # users table still there


# ------------------------------------------------------------------ config
def test_cache_and_celery_redis_urls_are_separated():
    from config import _with_db
    assert _with_db('redis://h:6379/0', 1) == 'redis://h:6379/1'
    assert _with_db('redis://h:6379', 2) == 'redis://h:6379/2'
    assert _with_db('redis://:pw@h:6379/5', 2) == 'redis://:pw@h:6379/2'


def test_celery_reliability_settings():
    from celery_worker import celery
    conf = celery.conf
    assert conf.broker_transport_options['visibility_timeout'] >= 7200
    assert conf.task_acks_late and conf.task_reject_on_worker_lost and conf.worker_prefetch_multiplier == 1
    assert conf.task_time_limit < conf.broker_transport_options['visibility_timeout']
    assert 'schedule' in conf.beat_schedule['monthly-report']
    assert 'crontab' in repr(conf.beat_schedule['monthly-report']['schedule']).lower()


def test_logging_json_formatter_has_event_and_request_id(app):
    import json
    import logging
    from logging_config import JsonFormatter, request_id_var, RequestIdFilter
    request_id_var.set('rid-123')
    rec = logging.LogRecord('ppa', logging.WARNING, __file__, 1, 'hf_api_fallback', (), None)
    rec.event, rec.student_id, rec.reason = 'hf_api_fallback', 123, 'timeout'
    RequestIdFilter().filter(rec)
    payload = json.loads(JsonFormatter().format(rec))
    assert payload['event'] == 'hf_api_fallback' and payload['student_id'] == 123 and payload['request_id'] == 'rid-123'
    request_id_var.set('-')
