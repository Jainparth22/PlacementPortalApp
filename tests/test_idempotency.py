"""Idempotency-Key: retries return the original response and never repeat the side effect."""
import hashlib
import json
from types import SimpleNamespace

import pytest
from flask import jsonify

import idempotency
from conftest import login, bearer, make_drive
from models import Application, AsyncJob, PlacementDrive


@pytest.fixture(autouse=True)
def _clean():
    idempotency.clear_memory()


def _hdr(token, key):
    return {**bearer(token), 'Idempotency-Key': key}


def test_apply_retry_with_same_key_replays_and_creates_one_application(client, student, company, backend):
    drive = make_drive(company)
    token = login(client, 'stu@example.com')
    first = client.post(f'/api/v1/student/apply/{drive.id}', json={}, headers=_hdr(token, 'key-apply-0001'))
    second = client.post(f'/api/v1/student/apply/{drive.id}', json={}, headers=_hdr(token, 'key-apply-0001'))
    assert first.status_code == 201 and second.status_code == 201
    assert second.headers['Idempotent-Replay'] == 'true' and 'Idempotent-Replay' not in first.headers
    assert second.get_json() == first.get_json()
    assert Application.query.count() == 1


def test_without_key_second_apply_is_a_409_as_before(client, student, company):
    drive = make_drive(company)
    token = login(client, 'stu@example.com')
    assert client.post(f'/api/v1/student/apply/{drive.id}', json={}, headers=bearer(token)).status_code == 201
    assert client.post(f'/api/v1/student/apply/{drive.id}', json={}, headers=bearer(token)).status_code == 409


def test_same_key_different_body_is_422(client, student, company):
    drive = make_drive(company)
    token = login(client, 'stu@example.com')
    client.post(f'/api/v1/student/apply/{drive.id}', json={'cover_letter': 'a'}, headers=_hdr(token, 'key-body-0001'))
    resp = client.post(f'/api/v1/student/apply/{drive.id}', json={'cover_letter': 'b'}, headers=_hdr(token, 'key-body-0001'))
    assert resp.status_code == 422


def test_deterministic_client_errors_are_replayed_too(client, student, company):
    drive = make_drive(company, min_cgpa=9.9)
    token = login(client, 'stu@example.com')
    a = client.post(f'/api/v1/student/apply/{drive.id}', json={}, headers=_hdr(token, 'key-err-00001'))
    b = client.post(f'/api/v1/student/apply/{drive.id}', json={}, headers=_hdr(token, 'key-err-00001'))
    assert a.status_code == b.status_code == 400 and b.headers['Idempotent-Replay'] == 'true'


def test_keys_are_scoped_per_user(client, app, student, company):
    from conftest import make_user
    drive = make_drive(company)
    make_user('student', 'other@example.com')
    t1 = login(client, 'stu@example.com')
    t2 = login(app.test_client(), 'other@example.com')
    r1 = client.post(f'/api/v1/student/apply/{drive.id}', json={}, headers=_hdr(t1, 'shared-key-0001'))
    r2 = app.test_client().post(f'/api/v1/student/apply/{drive.id}', json={}, headers=_hdr(t2, 'shared-key-0001'))
    assert r1.status_code == r2.status_code == 201 and 'Idempotent-Replay' not in r2.headers
    assert Application.query.count() == 2


def test_invalid_key_is_rejected(client, student, company):
    drive = make_drive(company)
    token = login(client, 'stu@example.com')
    assert client.post(f'/api/v1/student/apply/{drive.id}', json={}, headers=_hdr(token, 'short')).status_code == 400
    assert client.post(f'/api/v1/student/apply/{drive.id}', json={}, headers=_hdr(token, 'bad key with spaces!!')).status_code == 400


def test_export_with_key_returns_same_job(client, student):
    token = login(client, 'stu@example.com')
    a = client.post('/api/v1/student/export-applications', headers=_hdr(token, 'key-export-001')).get_json()
    b = client.post('/api/v1/student/export-applications', headers=_hdr(token, 'key-export-001')).get_json()
    assert a['job_id'] == b['job_id'] and AsyncJob.query.count() == 1


def test_replay_does_not_consume_rate_limit(client, app, student):
    app.config['HEAVY_ENDPOINT_RATE_LIMIT'] = 1
    token = login(client, 'stu@example.com')
    for _ in range(4):
        assert client.post('/api/v1/student/export-applications', headers=_hdr(token, 'key-rl-000001')).status_code == 202


def test_create_drive_with_key_does_not_duplicate(client, company):
    token = login(client, 'hr@acme.com')
    body = {'drive_name': 'D', 'job_title': 'T'}
    client.post('/api/v1/company/drives', json=body, headers=_hdr(token, 'key-drive-0001'))
    client.post('/api/v1/company/drives', json=body, headers=_hdr(token, 'key-drive-0001'))
    assert PlacementDrive.query.count() == 1


# ------------------------------------------------------------------ decorator internals
def _call(app, fn, key='unit-key-0001', body=b'{}', user_id=1):
    with app.test_request_context('/x', method='POST', data=body, headers={'Idempotency-Key': key}):
        return idempotency.idempotent(fn)(SimpleNamespace(id=user_id))


def test_in_flight_request_gets_409_with_retry_after(app):
    body = b'{}'
    key = 'ppa:idem:1:POST:/x:unit-key-0001'
    idempotency._memory.set(key, json.dumps({'state': 'in_flight', 'fp': hashlib.sha256(body).hexdigest()}), 60)
    resp = _call(app, lambda u: (jsonify(ok=True), 201), body=body)
    assert resp.status_code == 409 and resp.headers['Retry-After'] == '1'


def test_server_errors_are_not_stored_so_the_client_can_retry(app):
    calls = []

    def flaky(user):
        calls.append(1)
        return (jsonify(error='boom'), 500) if len(calls) == 1 else (jsonify(ok=True), 201)

    assert _call(app, flaky).status_code == 500
    assert _call(app, flaky).status_code == 201 and len(calls) == 2


def test_rate_limited_responses_are_not_stored(app):
    calls = []

    def limited(user):
        calls.append(1)
        return (jsonify(error='slow down'), 429) if len(calls) == 1 else (jsonify(ok=True), 201)

    assert _call(app, limited).status_code == 429
    assert _call(app, limited).status_code == 201


def test_exception_releases_the_key(app):
    calls = []

    def crash(user):
        calls.append(1)
        if len(calls) == 1:
            raise RuntimeError('bug')
        return jsonify(ok=True), 201

    with pytest.raises(RuntimeError):
        _call(app, crash)
    assert _call(app, crash).status_code == 201


def test_no_header_means_no_idempotency(app):
    calls = []

    def fn(user):
        calls.append(1)
        return jsonify(n=len(calls)), 201

    with app.test_request_context('/x', method='POST', data=b'{}'):
        idempotency.idempotent(fn)(SimpleNamespace(id=1))
        idempotency.idempotent(fn)(SimpleNamespace(id=1))
    assert len(calls) == 2
