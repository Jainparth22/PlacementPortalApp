import os
from celery import Celery

# Railway: REDIS_URL is set by Redis plugin; fallback to CELERY_* for local
_redis_url = os.environ.get('REDIS_URL', 'redis://localhost:6379/0')
_broker = os.environ.get('CELERY_BROKER_URL', _redis_url.replace('/0', '/1') if _redis_url.endswith('/0') else os.environ.get('REDIS_URL', 'redis://localhost:6379/1'))
_backend = os.environ.get('CELERY_RESULT_BACKEND', _broker)

celery = Celery(
    'ppa',
    broker=_broker,
    backend=_backend,
    include=['tasks']
)

celery.conf.update(
    task_serializer='json',
    accept_content=['json'],
    result_serializer='json',
    timezone='Asia/Kolkata',
    enable_utc=True,
    beat_schedule={
        'daily-reminders': {
            'task': 'tasks.send_daily_reminders',
            'schedule': 360,  # every 24 hours (360*240 ~ 24h check)
        },
        'monthly-report': {
            'task': 'tasks.generate_monthly_report',
            'schedule': 120,  # ~30 days (demo: 120s)
        },
    },
)


def init_celery(app):
    # set up celery to use flask app context — sync broker from Flask config (which already handles REDIS_URL fallback)
    celery.conf.update(
        broker_url=app.config.get('CELERY_BROKER_URL', _broker),
        result_backend=app.config.get('CELERY_RESULT_BACKEND', _backend),
    )

    class ContextTask(celery.Task):
        abstract = True

        def __call__(self, *args, **kwargs):
            with app.app_context():
                return self.run(*args, **kwargs)

    celery.Task = ContextTask
    return celery


# When running as celery worker (not via Flask), create the app context
# This ensures tasks can access db.session, current_app, etc.
try:
    from app import create_app
    _flask_app = create_app()
    init_celery(_flask_app)
except Exception:
    pass  # will be initialized by Flask when running as web server
