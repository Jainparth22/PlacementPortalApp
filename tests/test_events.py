"""Transactional outbox -> Redis Streams -> SSE."""
import json
import time

import pytest

import cache
import events
from conftest import login, bearer, make_user
from models import db, Notification, OutboxEvent


def _parse_sse(text):
    out = []
    for block in text.strip().split('\n\n'):
        ev = {'event': 'message', 'id': None, 'data': ''}
        for line in block.split('\n'):
            if line.startswith('event:'):
                ev['event'] = line[6:].strip()
            elif line.startswith('id:'):
                ev['id'] = line[3:].strip()
            elif line.startswith('data:'):
                ev['data'] += line[5:].strip()
        if ev['data'] or ev['event'] != 'message':
            out.append(ev)
    return out


# ------------------------------------------------------------------ outbox atomicity
def test_notify_writes_notification_and_outbox_in_one_transaction(app, student):
    events.notify(student.id, 'hello')
    db.session.commit()
    assert Notification.query.count() == 1
    row = OutboxEvent.query.one()
    payload = json.loads(row.payload)
    assert row.user_id == student.id and row.published_at is None
    assert payload['message'] == 'hello' and payload['id'] == Notification.query.one().id


def test_rollback_removes_both_notification_and_event(app, student):
    events.notify(student.id, 'will not happen')
    db.session.rollback()                       # the business transaction failed
    assert Notification.query.count() == 0 and OutboxEvent.query.count() == 0     # no phantom event


# ------------------------------------------------------------------ relay
def test_relay_publishes_to_user_and_global_streams(app, student, fake_redis):
    app.config['STATE_REDIS_URL'] = 'redis://configured'
    events.notify(student.id, 'm1')
    events.notify(student.id, 'm2')
    db.session.commit()
    assert events.relay_outbox() == 2
    assert fake_redis.xlen(events.USER_STREAM.format(student.id)) == 2
    assert fake_redis.xlen(events.GLOBAL_STREAM) == 2
    assert all(r.published_at for r in OutboxEvent.query)
    assert events.relay_outbox() == 0            # nothing left: no double publish
    entry = fake_redis.xrange(events.USER_STREAM.format(student.id))[0][1]
    assert entry['type'] == 'notification.created' and entry['event_id']
    assert fake_redis.ttl(events.USER_STREAM.format(student.id)) > 0          # streams expire (no unbounded growth)


def test_streams_are_capped(app, student, fake_redis, monkeypatch):
    monkeypatch.setattr(events, 'USER_STREAM_MAXLEN', 5)
    app.config['STATE_REDIS_URL'] = 'redis://configured'
    for i in range(40):
        events.notify(student.id, f'm{i}')
    db.session.commit()
    events.relay_outbox(limit=100)
    assert 5 <= fake_redis.xlen(events.USER_STREAM.format(student.id)) < 40      # approximate trim (~)


def test_redis_outage_keeps_events_in_outbox_then_delivers_later(app, student, fake_redis):
    """Nothing is lost while Redis is down; after recovery the relay delivers (at-least-once)."""
    app.config['STATE_REDIS_URL'] = 'redis://configured'
    cache.use_redis_clients(None, None)
    cache._ROLES['state'].down_until = time.monotonic() + 100
    events.notify(student.id, 'during outage')
    db.session.commit()
    assert events.relay_outbox() == 0                                   # cannot publish -> stays pending
    assert OutboxEvent.query.one().published_at is None
    cache.use_redis_clients(fake_redis, fake_redis)                     # Redis is back
    assert events.relay_outbox() == 1
    assert fake_redis.xlen(events.USER_STREAM.format(student.id)) == 1
    assert OutboxEvent.query.one().published_at is not None


def test_without_redis_configured_memory_stream_is_the_transport(app, student):
    events.notify(student.id, 'dev mode')
    db.session.commit()
    assert events.relay_outbox() == 1                                   # marked published (memory is the transport)
    got = events.read_events(student.id, '0-0', block_ms=50)
    assert [d['message'] for _, d in got] == ['dev mode']


def test_purge_old_published_rows(app, student):
    from datetime import datetime, timedelta
    events.notify(student.id, 'old')
    events.notify(student.id, 'fresh-unpublished')
    db.session.commit()
    old = OutboxEvent.query.first()
    old.published_at = datetime.utcnow() - timedelta(days=30)
    db.session.commit()
    assert events.purge_published() == 1 and OutboxEvent.query.count() == 1


# ------------------------------------------------------------------ reading / SSE framing
@pytest.mark.parametrize('use_redis', [False, True])
def test_stream_generator_frames_events_and_resumes_from_last_event_id(app, student, use_redis, request):
    if use_redis:
        request.getfixturevalue('fake_redis')
        app.config['STATE_REDIS_URL'] = 'redis://configured'
    for m in ('first', 'second', 'third'):
        events.notify(student.id, m)
    db.session.commit()
    events.relay_outbox()

    assert events.try_acquire_connection(5)
    body = ''.join(events.stream_notifications(student.id, '0-0', max_seconds=0.2, block_ms=50))
    parsed = _parse_sse(body)
    notes = [e for e in parsed if e['event'] == 'notification']
    assert [json.loads(e['data'])['message'] for e in notes] == ['first', 'second', 'third']
    assert all(e['id'] for e in notes)
    assert parsed[0]['event'] == 'ready' or body.startswith('retry: 3000')
    assert parsed[-1]['event'] == 'reconnect'
    assert events.active_connections() == 0                 # slot released when the stream ends

    # reconnect with Last-Event-ID => only what came after
    assert events.try_acquire_connection(5)
    body2 = ''.join(events.stream_notifications(student.id, notes[0]['id'], max_seconds=0.2, block_ms=50))
    msgs = [json.loads(e['data'])['message'] for e in _parse_sse(body2) if e['event'] == 'notification']
    assert msgs == ['second', 'third']


def test_invalid_last_event_id_starts_from_now_not_from_history(app, student):
    events.notify(student.id, 'old news')
    db.session.commit()
    events.relay_outbox()
    assert events.try_acquire_connection(5)
    body = ''.join(events.stream_notifications(student.id, 'garbage<script>', max_seconds=0.2, block_ms=50))
    assert not [e for e in _parse_sse(body) if e['event'] == 'notification']


def test_new_event_arrives_while_connected(app, student):
    import threading
    got = []
    assert events.try_acquire_connection(5)

    def reader():
        with app.app_context():
            stream = events.stream_notifications(student.id, None, max_seconds=3, block_ms=200)
            for chunk in stream:
                if 'event: notification' in chunk:
                    got.append(chunk)
                    break
            stream.close()

    t = threading.Thread(target=reader)
    t.start()
    time.sleep(0.6)
    events.notify(student.id, 'live!')
    db.session.commit()
    events.relay_outbox()
    t.join(5)
    assert got and 'live!' in got[0]
    assert events.active_connections() == 0


def test_keepalive_comment_is_sent_when_idle(app, student):
    assert events.try_acquire_connection(5)
    body = ''.join(events.stream_notifications(student.id, None, max_seconds=0.5, keepalive_seconds=0.1, block_ms=50))
    assert ': keep-alive' in body


def test_connection_slot_released_even_if_stream_never_started(app):
    assert events.try_acquire_connection(1)
    it = events.stream_notifications(1, None, max_seconds=1)
    it.close()                                              # client hung up before the first byte
    assert events.active_connections() == 0
    assert events.try_acquire_connection(1)
    events.release_connection()


# ------------------------------------------------------------------ HTTP endpoint
def test_stream_endpoint_requires_auth(client):
    assert client.get('/api/v1/notifications/stream').status_code == 401


def test_stream_endpoint_headers_and_body(client, app, student):
    app.config['SSE_MAX_SECONDS'] = 1
    events.notify(student.id, 'hi there')
    db.session.commit()
    events.relay_outbox()
    token = login(client, 'stu@example.com')
    resp = client.get('/api/v1/notifications/stream', headers={**bearer(token), 'Last-Event-ID': '0-0'})
    assert resp.status_code == 200 and resp.mimetype == 'text/event-stream'
    assert resp.headers['X-Accel-Buffering'] == 'no' and resp.headers['Cache-Control'] == 'no-store'
    body = resp.get_data(as_text=True)
    assert 'event: notification' in body and 'hi there' in body
    assert events.active_connections() == 0


def test_stream_endpoint_refuses_when_at_capacity_so_client_falls_back_to_polling(client, app, student):
    app.config['SSE_MAX_CONNECTIONS'] = 0
    token = login(client, 'stu@example.com')
    resp = client.get('/api/v1/notifications/stream', headers=bearer(token))
    assert resp.status_code == 503 and resp.get_json()['code'] == 'stream_full' and 'Retry-After' in resp.headers
    app.config['SSE_MAX_CONNECTIONS'] = 50


def test_users_only_see_their_own_stream(app, student):
    other = make_user('student', 'other@example.com')
    events.notify(student.id, 'for student')
    events.notify(other.id, 'for other')
    db.session.commit()
    events.relay_outbox()
    assert [d['message'] for _, d in events.read_events(student.id, '0-0', 50)] == ['for student']
    assert [d['message'] for _, d in events.read_events(other.id, '0-0', 50)] == ['for other']


# ------------------------------------------------------------------ end to end through the real API
def test_admin_approval_pushes_a_live_event_to_the_company(client, app, admin):
    company_user = make_user('company', 'newco@example.com', approval_status='pending')
    profile = company_user.company_profile
    a_token = login(client, 'admin@example.com')
    assert client.put(f'/api/v1/admin/companies/{profile.id}/approve', headers=bearer(a_token)).status_code == 200
    # the request's after_request fast path already relayed it:
    assert OutboxEvent.query.one().published_at is not None
    got = events.read_events(company_user.id, '0-0', 50)
    assert len(got) == 1 and 'approved' in got[0][1]['message']


def test_apply_notifies_the_company_live(client, app, student, company):
    from conftest import make_drive
    drive = make_drive(company)
    token = login(client, 'stu@example.com')
    client.post(f'/api/v1/student/apply/{drive.id}', json={}, headers=bearer(token))
    got = events.read_events(company.user_id, '0-0', 50)
    assert got and 'applied' in got[0][1]['message']


def test_beat_schedules_relay_and_housekeeping():
    from celery_worker import celery
    assert celery.conf.beat_schedule['relay-outbox']['schedule'] == 30.0
    assert 'housekeeping' in celery.conf.beat_schedule


def test_relay_task_and_housekeeping_task(app, student):
    import tasks
    events.notify(student.id, 'x')
    db.session.commit()
    assert tasks.relay_outbox_task()['published'] == 1
    assert 'refresh_tokens' in tasks.housekeeping()
