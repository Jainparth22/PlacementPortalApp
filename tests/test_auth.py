import auth
import ratelimit
from conftest import login, bearer, make_user, csrf_headers


def test_login_success_and_me(client, student):
    token = login(client, 'stu@example.com')
    resp = client.get('/api/v1/auth/me', headers=bearer(token))
    assert resp.status_code == 200
    assert resp.get_json()['user']['email'] == 'stu@example.com'


def test_login_wrong_password_and_unknown_user_look_identical(client, student):
    a = client.post('/api/v1/auth/login', json={'email': 'stu@example.com', 'password': 'nope-nope'})
    b = client.post('/api/v1/auth/login', json={'email': 'ghost@example.com', 'password': 'nope-nope'})
    assert a.status_code == b.status_code == 401
    assert a.get_json() == b.get_json()


def test_deactivated_user_cannot_login(client, app, student):
    from models import db
    student.is_active = False
    db.session.commit()
    resp = client.post('/api/v1/auth/login', json={'email': 'stu@example.com', 'password': 'Passw0rd!'})
    assert resp.status_code == 403


def test_jwt_contains_jti_and_expiry(app, student):
    token = auth.generate_token(student)
    payload = auth.decode_token(token)
    assert payload['jti'] and payload['exp'] > payload['iat']


def test_logout_blacklists_token(client, student, backend):
    token = login(client, 'stu@example.com')
    assert client.get('/api/v1/auth/me', headers=bearer(token)).status_code == 200
    assert client.post('/api/v1/auth/logout', headers=csrf_headers(client, token)).status_code == 200
    # same, still-unexpired token must now be rejected
    assert client.get('/api/v1/auth/me', headers=bearer(token)).status_code == 401


def test_blacklist_is_shared_through_redis(client, student, fake_redis):
    token = login(client, 'stu@example.com')
    client.post('/api/v1/auth/logout', headers=csrf_headers(client, token))
    jti = auth.jwt.decode(token, options={'verify_signature': False})['jti']
    assert fake_redis.exists(f'bl:{jti}')
    assert 0 < fake_redis.ttl(f'bl:{jti}') <= 3600
    auth._blacklisted_memory.clear()     # a second process would have no local memory
    assert client.get('/api/v1/auth/me', headers=bearer(token)).status_code == 401


def test_login_ip_rate_limit(client, app, student):
    app.config['LOGIN_RATE_LIMIT'] = 3
    codes = [client.post('/api/v1/auth/login', json={'email': 'stu@example.com', 'password': 'bad-bad'}).status_code for _ in range(5)]
    assert codes[:3] == [401, 401, 401]
    assert codes[3:] == [429, 429]
    resp = client.post('/api/v1/auth/login', json={'email': 'stu@example.com', 'password': 'Passw0rd!'})
    assert resp.status_code == 429 and 'Retry-After' in resp.headers


def test_login_per_account_lockout_only_counts_failures(client, app, student):
    app.config['LOGIN_EMAIL_RATE_LIMIT'] = 3
    for _ in range(3):
        assert client.post('/api/v1/auth/login', json={'email': 'stu@example.com', 'password': 'bad-bad'}).status_code == 401
    # locked even with the right password...
    assert client.post('/api/v1/auth/login', json={'email': 'stu@example.com', 'password': 'Passw0rd!'}).status_code == 429
    # ...but other accounts are unaffected
    make_user('student', 'other@example.com')
    assert client.post('/api/v1/auth/login', json={'email': 'other@example.com', 'password': 'Passw0rd!'}).status_code == 200


def test_successful_login_resets_failure_counter(client, app, student):
    app.config['LOGIN_EMAIL_RATE_LIMIT'] = 3
    for _ in range(2):
        client.post('/api/v1/auth/login', json={'email': 'stu@example.com', 'password': 'bad-bad'})
    assert client.post('/api/v1/auth/login', json={'email': 'stu@example.com', 'password': 'Passw0rd!'}).status_code == 200
    assert ratelimit.current('login-email', 'stu@example.com')[0] == 0


def test_rate_limit_atomic_expiry_in_redis(app, fake_redis):
    ok, _ = ratelimit.hit('t', 'x', 5)
    assert ok
    assert fake_redis.ttl('ppa:rl:t:x') > 0      # a counter must never exist without an expiry


def test_role_enforced(client, student):
    token = login(client, 'stu@example.com')
    assert client.get('/api/v1/admin/dashboard', headers=bearer(token)).status_code == 403
    assert client.get('/api/v1/admin/dashboard').status_code == 401
