import os
import re

BASE_DIR = os.path.abspath(os.path.dirname(__file__))

try:  # load a local .env (dev convenience); real environment variables always win
    from dotenv import load_dotenv
    load_dotenv(os.path.join(BASE_DIR, '..', '.env'))
except ImportError:
    pass


def _is_production():
    return (os.environ.get('APP_ENV') or os.environ.get('FLASK_ENV') or '').lower() == 'production'


def _get_database_uri():
    """Postgres if DATABASE_URL is set, otherwise a local SQLite file (zero-setup dev)."""
    db_url = os.environ.get('DATABASE_URL')
    if db_url:
        # SQLAlchemy 2.0 requires postgresql:// not postgres://
        if db_url.startswith('postgres://'):
            db_url = db_url.replace('postgres://', 'postgresql://', 1)
        return db_url
    return 'sqlite:///' + os.path.join(BASE_DIR, 'instance', 'ppa.db')


def _require_env(key, fallback_dev, description=""):
    """Return env var or dev fallback; fail hard in production if it is missing."""
    val = os.environ.get(key)
    if val:
        return val
    if _is_production():
        raise RuntimeError(f"{key} must be set in production env. {description}")
    return fallback_dev


def _with_db(url, db_number):
    """Return a redis URL pointing at a different logical database number."""
    if re.search(r'/\d+$', url):
        return re.sub(r'/\d+$', f'/{db_number}', url)
    return url.rstrip('/') + f'/{db_number}'


# ---------------------------------------------------------------------------
# Redis topology
#   cache  (REDIS_URL)          - disposable data. Safe to evict / lose.
#   broker (CELERY_BROKER_URL)  - Celery queue. Must NOT be evicted (noeviction + AOF).
#   state  (STATE_REDIS_URL)    - JWT blacklist + rate-limit counters. Durable, same
#                                 instance as the broker by default (different DB number).
# Locally one Redis serves all three (DB 0/1/2); docker-compose runs two instances.
# ---------------------------------------------------------------------------
_REDIS_URL = os.environ.get('REDIS_URL', 'redis://localhost:6379/0')
_BROKER_URL = os.environ.get('CELERY_BROKER_URL', _with_db(_REDIS_URL, 1))
_STATE_URL = os.environ.get('STATE_REDIS_URL', _with_db(_BROKER_URL, 2))


class Config:
    ENV_NAME = 'production' if _is_production() else 'development'

    SECRET_KEY = _require_env('SECRET_KEY', 'dev-only-zaxscdvfbgnhmj-change-me', 'Set strong 32+ char secret')
    SQLALCHEMY_DATABASE_URI = os.environ.get('SQLALCHEMY_DATABASE_URI', _get_database_uri())
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SQLALCHEMY_ENGINE_OPTIONS = {'pool_pre_ping': True} if 'postgresql' in SQLALCHEMY_DATABASE_URI else {}

    # JWT
    JWT_SECRET_KEY = _require_env('JWT_SECRET_KEY', 'dev-only-aqswdefrgthyjukilo-change-me', 'Set strong JWT secret')
    JWT_ACCESS_TOKEN_EXPIRES = int(os.environ.get('JWT_ACCESS_TOKEN_EXPIRES', 900))   # 15 min; renewed via refresh token
    REFRESH_TOKEN_DAYS = int(os.environ.get('REFRESH_TOKEN_DAYS', 7))
    REFRESH_REUSE_GRACE_SECONDS = int(os.environ.get('REFRESH_REUSE_GRACE_SECONDS', 10))   # tolerate two tabs refreshing at once
    COOKIE_SECURE = os.environ.get('COOKIE_SECURE', '1' if _is_production() else '0') == '1'   # needs HTTPS
    COOKIE_SAMESITE = os.environ.get('COOKIE_SAMESITE', 'Strict')
    JWT_TOKEN_LOCATION = ['headers']

    # Redis
    REDIS_URL = _REDIS_URL
    STATE_REDIS_URL = _STATE_URL
    CACHE_KEY_VERSION = os.environ.get('CACHE_KEY_VERSION', 'v1')   # bump to drop every cached entry
    CACHE_DEFAULT_TTL = int(os.environ.get('CACHE_DEFAULT_TTL', 300))
    CACHE_MEMORY_MAX_ITEMS = int(os.environ.get('CACHE_MEMORY_MAX_ITEMS', 512))

    # Celery
    CELERY_BROKER_URL = _BROKER_URL
    CELERY_RESULT_BACKEND = os.environ.get('CELERY_RESULT_BACKEND', _BROKER_URL)

    # Mail — email is skipped when credentials are unset
    MAIL_SERVER = os.environ.get('MAIL_SERVER', 'smtp.gmail.com')
    MAIL_PORT = int(os.environ.get('MAIL_PORT', 587))
    MAIL_USE_TLS = True
    MAIL_USERNAME = os.environ.get('MAIL_USERNAME')
    MAIL_PASSWORD = os.environ.get('MAIL_PASSWORD')
    MAIL_DEFAULT_SENDER = os.environ.get('MAIL_DEFAULT_SENDER', MAIL_USERNAME)

    # Google Chat webhook — optional; disabled when unset
    GCHAT_WEBHOOK_URL = os.environ.get('GCHAT_WEBHOOK_URL', '')

    # CORS — frontend is served same-origin, so cross-origin access is off by default.
    # Set CORS_ORIGINS to a comma-separated list to enable.
    CORS_ORIGINS = [o.strip() for o in os.environ.get('CORS_ORIGINS', '').split(',') if o.strip()]

    # Storage
    UPLOAD_FOLDER = os.environ.get('UPLOAD_FOLDER', os.path.join(BASE_DIR, 'uploads'))
    REPORTS_FOLDER = os.environ.get('REPORTS_FOLDER', os.path.join(BASE_DIR, 'reports'))
    EXPORTS_FOLDER = os.environ.get('EXPORTS_FOLDER', os.path.join(BASE_DIR, 'exports'))
    MAX_CONTENT_LENGTH = 5 * 1024 * 1024  # 5 MB

    # Storage backend: local | s3 (AWS S3, Cloudflare R2, MinIO...) | azure. See backend/storage.py.
    STORAGE_BACKEND = os.environ.get('STORAGE_BACKEND', 'local').lower()
    S3_BUCKET = os.environ.get('S3_BUCKET', '')
    S3_PREFIX = os.environ.get('S3_PREFIX', '')
    S3_ENDPOINT_URL = os.environ.get('S3_ENDPOINT_URL', '')     # set for R2 / MinIO / other S3-compatible
    S3_REGION = os.environ.get('S3_REGION', '')
    AZURE_STORAGE_CONTAINER = os.environ.get('AZURE_STORAGE_CONTAINER', 'ppa')
    AZURE_STORAGE_CONNECTION_STRING = os.environ.get('AZURE_STORAGE_CONNECTION_STRING', '')
    AZURE_STORAGE_ACCOUNT_URL = os.environ.get('AZURE_STORAGE_ACCOUNT_URL', '')   # with managed identity

    # Admin bootstrap credentials — production must override via env
    ADMIN_EMAIL = os.environ.get('ADMIN_EMAIL', 'jainparth7040@gmail.com')
    ADMIN_PASSWORD = _require_env('ADMIN_PASSWORD', 'admin123', 'Set strong admin password for prod')

    # Rate limits (requests per 60s window)
    LOGIN_RATE_LIMIT = int(os.environ.get('LOGIN_RATE_LIMIT', 20))            # per IP
    LOGIN_EMAIL_RATE_LIMIT = int(os.environ.get('LOGIN_EMAIL_RATE_LIMIT', 10))  # per target account
    HEAVY_ENDPOINT_RATE_LIMIT = int(os.environ.get('HEAVY_ENDPOINT_RATE_LIMIT', 10))  # per user (reports/export/ATS)

    # Server-Sent Events (live notifications). Each open stream holds one worker thread, so cap it per process.
    SSE_MAX_CONNECTIONS = int(os.environ.get('SSE_MAX_CONNECTIONS', 50))
    SSE_MAX_SECONDS = int(os.environ.get('SSE_MAX_SECONDS', 300))      # then the client reconnects with Last-Event-ID

    # Observability
    METRICS_ENABLED = os.environ.get('METRICS_ENABLED', '1') == '1'
    METRICS_TOKEN = os.environ.get('METRICS_TOKEN', '')       # Bearer token for /metrics; no token => open in dev, disabled in production
    LOG_LEVEL = os.environ.get('LOG_LEVEL', 'WARNING' if _is_production() else 'DEBUG').upper()
    LOG_JSON = os.environ.get('LOG_JSON', '1' if _is_production() else '0') == '1'
    SENTRY_DSN = os.environ.get('SENTRY_DSN', '')

    # Apply Alembic migrations automatically on boot (dev convenience). Production: run `flask db upgrade`.
    AUTO_MIGRATE = os.environ.get('AUTO_MIGRATE', '0' if _is_production() else '1') == '1'

    # Number of reverse-proxy hops to trust for client IP (0 = none)
    TRUSTED_PROXY_COUNT = int(os.environ.get('TRUSTED_PROXY_COUNT', 0))
