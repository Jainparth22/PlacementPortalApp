import os

BASE_DIR = os.path.abspath(os.path.dirname(__file__))


def _get_database_uri():
    """
    Railway deployment: use Postgres if DATABASE_URL is set.
    Local dev: use SQLite. Uncomment/comment section below to switch.

    Railway Postgres plugin auto-sets DATABASE_URL=postgresql://...
    For SQLite local test, just unset DATABASE_URL or set USE_SQLITE=1
    """
    # --- PRODUCTION: Postgres on Railway (RECOMMENDED) ---
    # Railway injects DATABASE_URL when you add Postgres plugin.
    # Handles both postgres:// (old) and postgresql:// (new) schemes.
    db_url = os.environ.get('DATABASE_URL')
    if db_url:
        # SQLAlchemy 2.0 requires postgresql:// not postgres://
        if db_url.startswith('postgres://'):
            db_url = db_url.replace('postgres://', 'postgresql://', 1)
        return db_url

    # --- LOCAL DEV: SQLite fallback ---
    # Uncomment below for local Windows dev with SQLite, comment out for prod test
    return 'sqlite:///' + os.path.join(BASE_DIR, 'instance', 'ppa.db')

    # --- ALTERNATIVE: Force SQLite even if DATABASE_URL exists (for local testing on Railway clone) ---
    # return 'sqlite:///' + os.path.join(BASE_DIR, 'instance', 'ppa.db')


def _require_env(key, fallback_dev, description=""):
    """Return env var or dev fallback; fail hard in production (RAILWAY_ENVIRONMENT or FLASK_ENV=production)."""
    val = os.environ.get(key)
    if val:
        return val
    # In production on Railway, require explicit env — no weak fallback
    if os.environ.get('RAILWAY_ENVIRONMENT') or os.environ.get('FLASK_ENV') == 'production':
        raise RuntimeError(f"{key} must be set in production env. {description}")
    # Local dev fallback (not pushed as secure) — .env provides real values
    return fallback_dev

class Config:
    SECRET_KEY = _require_env('SECRET_KEY', 'dev-only-zaxscdvfbgnhmj-change-me', 'Set strong 32+ char secret')
    SQLALCHEMY_DATABASE_URI = os.environ.get('SQLALCHEMY_DATABASE_URI', _get_database_uri())
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    # Use psycopg2 for Postgres (add psycopg2-binary to requirements.txt if using Postgres)
    SQLALCHEMY_ENGINE_OPTIONS = {'pool_pre_ping': True} if 'postgresql' in SQLALCHEMY_DATABASE_URI else {}

    # JWT — must be strong in prod
    JWT_SECRET_KEY = _require_env('JWT_SECRET_KEY', 'dev-only-aqswdefrgthyjukilo-change-me', 'Set strong JWT secret')
    JWT_ACCESS_TOKEN_EXPIRES = 3600  # 1 hour in seconds
    JWT_TOKEN_LOCATION = ['headers']

    # Redis — Railway Redis plugin sets REDIS_URL
    REDIS_URL = os.environ.get('REDIS_URL', 'redis://localhost:6379/0')

    # Celery — fallback to REDIS_URL if CELERY_* not set (Railway only gives REDIS_URL)
    CELERY_BROKER_URL = os.environ.get('CELERY_BROKER_URL', os.environ.get('REDIS_URL', 'redis://localhost:6379/1'))
    CELERY_RESULT_BACKEND = os.environ.get('CELERY_RESULT_BACKEND', os.environ.get('REDIS_URL', 'redis://localhost:6379/1'))

    # Mail (for reports) — dev fallback still uses your gmail, but prod should set via env
    MAIL_SERVER = os.environ.get('MAIL_SERVER', 'smtp.gmail.com')
    MAIL_PORT = int(os.environ.get('MAIL_PORT', 587))
    MAIL_USE_TLS = True
    MAIL_USERNAME = os.environ.get('MAIL_USERNAME', 'jainparth7040@gmail.com')
    # In prod, require explicit password; dev uses .env value (gitignored)
    MAIL_PASSWORD = os.environ.get('MAIL_PASSWORD', 'dev-only-veqnorhgnnjtlrif' if not os.environ.get('RAILWAY_ENVIRONMENT') else None)
    if os.environ.get('RAILWAY_ENVIRONMENT') and not os.environ.get('MAIL_PASSWORD'):
        # Allow empty in prod if email disabled, but warn
        MAIL_PASSWORD = None
    MAIL_DEFAULT_SENDER = os.environ.get('MAIL_DEFAULT_SENDER', 'jainparth7040@gmail.com')

    # Google Chat Webhook — optional, dev fallback for demo
    GCHAT_WEBHOOK_URL = os.environ.get('GCHAT_WEBHOOK_URL', 'https://chat.googleapis.com/v1/spaces/AAQAN-Z3YRA/messages?key=AIzaSyDdI0hCZtE6vySjMm-WEfRq3CPzqKqqsHI&token=RkEOko5j0OnLtJ6SYRCGawcNx63Aw6VuydT13QPI-jU' if not os.environ.get('RAILWAY_ENVIRONMENT') else '')

    # Upload — Railway Volume mount at /data (set UPLOAD_FOLDER=/data/uploads on Railway)
    # Local: backend/uploads/ | Railway with Volume: /data/uploads
    UPLOAD_FOLDER = os.environ.get('UPLOAD_FOLDER', os.path.join(BASE_DIR, 'uploads'))
    # Reports/Exports also volume-aware — set to /data if volume exists
    REPORTS_FOLDER = os.environ.get('REPORTS_FOLDER', os.path.join(BASE_DIR, 'reports'))
    EXPORTS_FOLDER = os.environ.get('EXPORTS_FOLDER', os.path.join(BASE_DIR, 'exports'))
    MAX_CONTENT_LENGTH = 5 * 1024 * 1024  # 5 MB

    # Admin credentials — dev default admin123, prod must override via Railway Variables
    ADMIN_EMAIL = os.environ.get('ADMIN_EMAIL', 'jainparth7040@gmail.com')
    ADMIN_PASSWORD = _require_env('ADMIN_PASSWORD', 'admin123', 'Set strong admin password for prod') if os.environ.get('RAILWAY_ENVIRONMENT') else os.environ.get('ADMIN_PASSWORD', 'admin123')
