"""Test harness: isolated SQLite DB, no real Redis (memory fallback) unless a test asks for fakeredis."""
import os
import sys
import tempfile
from datetime import datetime, timedelta

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, 'backend'))

_TMP = tempfile.mkdtemp(prefix='ppa-tests-')
os.environ.update({
    'DATABASE_URL': 'sqlite:///' + os.path.join(_TMP, 'test.db').replace(os.sep, '/'),
    'AUTO_MIGRATE': '0',
    'AUTO_SEED': '0',
    'UPLOAD_FOLDER': os.path.join(_TMP, 'uploads'),
    'REPORTS_FOLDER': os.path.join(_TMP, 'reports'),
    'EXPORTS_FOLDER': os.path.join(_TMP, 'exports'),
    'LOG_LEVEL': 'ERROR',
    'FLASK_ENV': 'development',
    'APP_ENV': 'development',
})
os.environ.pop('SENTRY_DSN', None)

import pytest  # noqa: E402
import fakeredis  # noqa: E402
from werkzeug.security import generate_password_hash  # noqa: E402

import app as app_module  # noqa: E402
import cache  # noqa: E402
import ratelimit  # noqa: E402
import auth  # noqa: E402
import events  # noqa: E402
import idempotency  # noqa: E402
from models import db, User, StudentProfile, CompanyProfile, PlacementDrive  # noqa: E402


@pytest.fixture()
def app():
    flask_app = app_module.app
    flask_app.config.update(
        TESTING=True, FORCE_SYNC_TASKS=True, REDIS_URL='', STATE_REDIS_URL='',
        LOGIN_RATE_LIMIT=20, LOGIN_EMAIL_RATE_LIMIT=10, HEAVY_ENDPOINT_RATE_LIMIT=10,
    )
    with flask_app.app_context():
        db.drop_all()
        db.create_all()
        cache.use_redis_clients(None, None)
        cache._memory.clear()
        cache._once_memory.clear()
        cache._ns_memory.clear()
        cache._pending_invalidations.clear()
        for k in cache._stats:
            cache._stats[k] = 0
        ratelimit.clear_memory()
        auth._blacklisted_memory.clear()
        events.memory_streams.clear()
        events._active = 0
        idempotency.clear_memory()
        yield flask_app
        db.session.remove()
    cache.use_redis_clients(None, None)


@pytest.fixture()
def client(app):
    return app.test_client()


@pytest.fixture()
def fake_redis(app):
    """Both Redis roles backed by one in-memory fakeredis server."""
    server = fakeredis.FakeServer()
    cache_r = fakeredis.FakeRedis(server=server, decode_responses=True)
    state_r = fakeredis.FakeRedis(server=server, decode_responses=True)
    cache.use_redis_clients(cache_r, state_r)
    yield cache_r
    cache.use_redis_clients(None, None)


@pytest.fixture(params=['memory', 'redis'])
def backend(request, app):
    """Run a test against both the in-process fallback and (fake) Redis."""
    if request.param == 'redis':
        server = fakeredis.FakeServer()
        cache.use_redis_clients(fakeredis.FakeRedis(server=server, decode_responses=True),
                                fakeredis.FakeRedis(server=server, decode_responses=True))
    yield request.param
    cache.use_redis_clients(None, None)


# ----------------------------------------------------------------------------- data helpers
def make_user(role, email, password='Passw0rd!', **profile):
    user = User(email=email, password_hash=generate_password_hash(password), role=role)
    db.session.add(user)
    db.session.flush()
    if role == 'student':
        db.session.add(StudentProfile(user_id=user.id, full_name=profile.get('full_name', 'Test Student'),
                                      department=profile.get('department', 'CSE'), cgpa=profile.get('cgpa', 8.0),
                                      graduation_year=profile.get('graduation_year', 2026)))
    elif role == 'company':
        db.session.add(CompanyProfile(user_id=user.id, company_name=profile.get('company_name', 'Acme'),
                                      approval_status=profile.get('approval_status', 'approved')))
    db.session.commit()
    return user


def login(client, email, password='Passw0rd!'):
    resp = client.post('/api/v1/auth/login', json={'email': email, 'password': password})
    assert resp.status_code == 200, resp.get_json()
    return resp.get_json()['token']


def bearer(token):
    return {'Authorization': f'Bearer {token}'}


def make_drive(company, **kw):
    drive = PlacementDrive(
        company_id=company.id, drive_name=kw.get('drive_name', 'Drive'), job_title=kw.get('job_title', 'SDE'),
        eligibility_branch=kw.get('eligibility_branch', 'All'), min_cgpa=kw.get('min_cgpa', 0.0),
        eligible_year=kw.get('eligible_year'), status=kw.get('status', 'approved'),
        application_deadline=kw.get('deadline', datetime.utcnow() + timedelta(days=5)),
    )
    db.session.add(drive)
    db.session.commit()
    return drive


@pytest.fixture()
def admin(app):
    return make_user('admin', 'admin@example.com')


@pytest.fixture()
def company(app):
    user = make_user('company', 'hr@acme.com', company_name='Acme')
    return user.company_profile


@pytest.fixture()
def student(app):
    return make_user('student', 'stu@example.com', cgpa=8.0, department='CSE', graduation_year=2026)


def csrf_headers(client, token=None):
    """Headers a browser would send for cookie-authenticated calls (double-submit CSRF token)."""
    cookie = client.get_cookie('ppa_csrf', path='/api/')
    headers = {'X-CSRF-Token': cookie.value} if cookie else {}
    if token:
        headers['Authorization'] = f'Bearer {token}'
    return headers
