# Railway Nixpacks Procfile — 3 services from same codebase
# Railway auto-detects Procfile. Create 3 services, each overrides startCommand.

# Web service (default) — Flask + Gunicorn (1 worker for Railway free 512MB)
web: gunicorn --chdir backend --workers 1 --threads 2 --timeout 120 --bind 0.0.0.0:$PORT app:app

# Worker service — Celery worker (create separate Railway service, set startCommand to below)
worker: celery --workdir backend -A celery_worker worker --loglevel=info --pool=solo --concurrency=1

# Beat service — Celery beat scheduler (create separate Railway service)
beat: celery --workdir backend -A celery_worker beat --loglevel=info
