"""Refresh-token sessions: httpOnly cookies, rotation, reuse detection, CSRF, logout everywhere."""
from datetime import datetime, timedelta

import jwt

from conftest import login, bearer, csrf_headers, make_user
from models import db, RefreshToken

COOKIE = dict(path='/api/')


def _refresh_cookie(client):
    c = client.get_cookie('ppa_refresh', **COOKIE)
    return c.value if c else None


def _do_refresh(client, headers=None):
    return client.post('/api/v1/auth/refresh', headers=headers if headers is not None else csrf_headers(client))


def test_login_sets_httponly_refresh_cookie_and_readable_csrf_cookie(client, student):
    resp = client.post('/api/v1/auth/login', json={'email': 'stu@example.com', 'password': 'Passw0rd!'})
    cookies = {h.split('=')[0]: h for h in resp.headers.getlist('Set-Cookie')}
    refresh, csrf = cookies['ppa_refresh'], cookies['ppa_csrf']
    assert 'HttpOnly' in refresh and 'SameSite=Strict' in refresh and 'Path=/api/' in refresh
    assert 'HttpOnly' not in csrf                         # the SPA must be able to read it to send the header
    body = resp.get_json()
    assert body['expires_in'] == 900
    claims = jwt.decode(body['token'], options={'verify_signature': False})
    assert claims['exp'] - claims['iat'] == 900            # short-lived access token


def test_secure_flag_follows_config(client, student, app):
    app.config['COOKIE_SECURE'] = True
    try:
        resp = client.post('/api/v1/auth/login', json={'email': 'stu@example.com', 'password': 'Passw0rd!'})
        assert all('Secure' in h for h in resp.headers.getlist('Set-Cookie'))
    finally:
        app.config['COOKIE_SECURE'] = False


def test_only_a_hash_of_the_refresh_token_is_stored(client, student):
    login(client, 'stu@example.com')
    raw = _refresh_cookie(client)
    row = RefreshToken.query.one()
    assert raw and row.token_hash != raw and len(row.token_hash) == 64


def test_refresh_rotates_token_and_returns_new_access_token(client, student):
    old_access = login(client, 'stu@example.com')
    old_refresh = _refresh_cookie(client)
    resp = _do_refresh(client)
    assert resp.status_code == 200
    body = resp.get_json()
    assert body['token'] and body['user']['email'] == 'stu@example.com' and body['profile']['full_name']
    assert _refresh_cookie(client) != old_refresh           # rotated
    assert client.get('/api/v1/auth/me', headers=bearer(body['token'])).status_code == 200
    assert old_access                                       # (old access token simply expires on its own)
    assert RefreshToken.query.count() == 2 and len({r.family_id for r in RefreshToken.query}) == 1


def test_refresh_requires_csrf_header(client, student):
    login(client, 'stu@example.com')
    assert _do_refresh(client, headers={}).status_code == 403
    assert _do_refresh(client, headers={'X-CSRF-Token': 'wrong'}).status_code == 403


def test_refresh_rejects_cross_origin(client, student):
    login(client, 'stu@example.com')
    headers = {**csrf_headers(client), 'Origin': 'https://evil.example'}
    assert _do_refresh(client, headers=headers).status_code == 403


def test_refresh_without_cookie_is_401(client):
    client.post('/api/v1/auth/login', json={'email': 'x@y.com', 'password': 'nope-nope'})
    client.set_cookie('ppa_csrf', 'abc', **COOKIE)
    resp = client.post('/api/v1/auth/refresh', headers={'X-CSRF-Token': 'abc'})
    assert resp.status_code == 401 and resp.get_json()['code'] == 'missing'


def test_reused_refresh_token_revokes_the_whole_family(client, app, student):
    """A rotated token coming back means it was copied: kill every session of that login."""
    app.config['REFRESH_REUSE_GRACE_SECONDS'] = 0
    login(client, 'stu@example.com')
    stolen = _refresh_cookie(client)
    assert _do_refresh(client).status_code == 200            # legitimate rotation
    legit_new = _refresh_cookie(client)

    attacker = app.test_client()                             # attacker replays the OLD token
    attacker.set_cookie('ppa_refresh', stolen, **COOKIE)
    attacker.set_cookie('ppa_csrf', 'x', **COOKIE)
    resp = attacker.post('/api/v1/auth/refresh', headers={'X-CSRF-Token': 'x'})
    assert resp.status_code == 401 and resp.get_json()['code'] == 'reuse'

    client.set_cookie('ppa_refresh', legit_new, **COOKIE)    # the victim's newest token is dead too
    assert _do_refresh(client).status_code == 401
    assert all(r.revoked_at for r in RefreshToken.query)


def test_reuse_inside_grace_window_is_benign(client, app, student):
    """Two tabs refresh at the same moment: the loser gets 'race', nobody is logged out."""
    app.config['REFRESH_REUSE_GRACE_SECONDS'] = 60
    login(client, 'stu@example.com')
    first = _refresh_cookie(client)
    assert _do_refresh(client).status_code == 200
    newest = _refresh_cookie(client)
    client.set_cookie('ppa_refresh', first, **COOKIE)
    resp = _do_refresh(client)
    assert resp.status_code == 401 and resp.get_json()['code'] == 'race'
    assert not any(r.revoked_at for r in RefreshToken.query)          # family untouched
    client.set_cookie('ppa_refresh', newest, **COOKIE)
    assert _do_refresh(client).status_code == 200                     # the newest token still works
    app.config['REFRESH_REUSE_GRACE_SECONDS'] = 10


def test_expired_refresh_token_is_rejected(client, student):
    login(client, 'stu@example.com')
    row = RefreshToken.query.one()
    row.expires_at = datetime.utcnow() - timedelta(seconds=1)
    db.session.commit()
    resp = _do_refresh(client)
    assert resp.status_code == 401 and resp.get_json()['code'] == 'expired'


def test_deactivated_user_cannot_refresh(client, student):
    login(client, 'stu@example.com')
    student.is_active = False
    db.session.commit()
    resp = _do_refresh(client)
    assert resp.status_code == 401 and resp.get_json()['code'] == 'forbidden'
    assert all(r.revoked_at for r in RefreshToken.query)


def test_logout_revokes_refresh_and_clears_cookies(client, student):
    token = login(client, 'stu@example.com')
    resp = client.post('/api/v1/auth/logout', headers=csrf_headers(client, token))
    assert resp.status_code == 200
    assert all('Max-Age=0' in h or 'Expires=Thu, 01 Jan 1970' in h for h in resp.headers.getlist('Set-Cookie'))
    assert client.get('/api/v1/auth/me', headers=bearer(token)).status_code == 401   # access jti blacklisted
    client.set_cookie('ppa_refresh', 'whatever', **COOKIE)


def test_logout_works_with_expired_access_token_via_cookie_alone(client, student):
    login(client, 'stu@example.com')
    cookie_before = _refresh_cookie(client)
    resp = client.post('/api/v1/auth/logout', headers=csrf_headers(client))          # no Authorization header at all
    assert resp.status_code == 200
    client.set_cookie('ppa_refresh', cookie_before, **COOKIE)
    client.set_cookie('ppa_csrf', 'x', **COOKIE)
    assert client.post('/api/v1/auth/refresh', headers={'X-CSRF-Token': 'x'}).status_code == 401


def test_logout_with_cookie_needs_csrf(client, student):
    login(client, 'stu@example.com')
    assert client.post('/api/v1/auth/logout').status_code == 403
    assert client.post('/api/v1/auth/logout', headers={'X-CSRF-Token': 'nope'}).status_code == 403


def test_logout_all_revokes_every_device(client, app, student):
    token = login(client, 'stu@example.com')
    other = app.test_client()
    login(other, 'stu@example.com')
    other_refresh = _refresh_cookie(other)
    assert client.post('/api/v1/auth/logout-all', headers=bearer(token)).status_code == 200
    other.set_cookie('ppa_refresh', other_refresh, **COOKIE)
    assert _do_refresh(other).status_code == 401


def test_separate_logins_are_separate_families(client, app, student):
    login(client, 'stu@example.com')
    login(app.test_client(), 'stu@example.com')
    assert len({r.family_id for r in RefreshToken.query}) == 2


def test_purge_expired_tokens(app, student):
    import sessions
    make_user('student', 'p@example.com')
    old = RefreshToken(user_id=student.id, family_id='f', token_hash='a' * 64, expires_at=datetime.utcnow() - timedelta(days=3))
    fresh = RefreshToken(user_id=student.id, family_id='g', token_hash='b' * 64, expires_at=datetime.utcnow() + timedelta(days=3))
    db.session.add_all([old, fresh])
    db.session.commit()
    assert sessions.purge_expired() == 1 and RefreshToken.query.count() == 1
