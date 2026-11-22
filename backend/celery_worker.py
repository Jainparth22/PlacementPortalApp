"""Celery application (Redis broker).

Reliability settings
* acks_late + reject_on_worker_lost : a task is only acknowledged after it finishes, so a worker
  crash re-queues it instead of losing it.
* visibility_timeout (2h)           : Redis re-delivers un-acked messages after this; it must be
  longer than the longest task + retry countdown, otherwise long PDF jobs are run twice.
* prefetch_multiplier=1             : no hoarding of messages by a busy worker.
* retries with exponential backoff  : see tasks.py (transient errors only).
* dead-letter queue                 : a task that exhausts its retries (or fails permanently) is
  pushed to a Redis list ``ppa:dead_letter`` (see dead_letter.py) for inspection / replay.
* Graceful shutdown                 : on SIGTERM the worker stops consuming and finishes the
  current task (warm shutdown). Give containers a stop grace period > task_time_limit.

The Flask app is only created here when this module is loaded by a Celery process
(worker / beat / flower); the web process wires itself up through ``init_celery(app)``.
"""
import logging
import sys

from celery import Celery
from celery.schedules import crontab
from celery.signals import before_task_publish, task_prerun, task_postrun

from config import Config
from logging_config import request_id_var

log = logging.getLogger(__name__)

celery = Celery('ppa', include=['tasks'])

celery.conf.update(
    broker_url=Config.CELERY_BROKER_URL,
    result_backend=Config.CELERY_RESULT_BACKEND,

    task_serializer='json',
    accept_content=['json'],
    result_serializer='json',
    timezone='Asia/Kolkata',
    enable_utc=True,

    task_default_queue='ppa',
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    worker_prefetch_multiplier=1,
    task_time_limit=600,
    task_soft_time_limit=540,
    task_ignore_result=True,        # job state lives in the AsyncJob table, not the result backend
    result_expires=3600,

    broker_connection_retry_on_startup=True,
    broker_connection_timeout=3,
    broker_transport_options={
        'visibility_timeout': 7200,
        'socket_timeout': 5,
        'socket_connect_timeout': 2,
        'health_check_interval': 30,
        'retry_on_timeout': True,
    },
    # Fail fast when publishing with the broker down so the web request can fall back to sync.
    task_publish_retry=True,
    task_publish_retry_policy={'max_retries': 1, 'interval_start': 0, 'interval_step': 0.2, 'interval_max': 0.5},

    # Events for monitoring (Flower)
    worker_send_task_events=True,
    task_send_sent_event=True,

    # crontab, not "every N seconds": interval schedules restart from zero whenever beat restarts,
    # so a "30 day" interval would effectively never fire.
    beat_schedule={
        'daily-reminders': {
            'task': 'tasks.send_daily_reminders',
            'schedule': crontab(hour=8, minute=0),
        },
        'relay-outbox': {
            'task': 'tasks.relay_outbox',
            'schedule': 30.0,
        },
        'housekeeping': {
            'task': 'tasks.housekeeping',
            'schedule': crontab(hour=3, minute=30),
        },
        'monthly-report': {
            'task': 'tasks.generate_monthly_report',
            'schedule': crontab(day_of_month=1, hour=1, minute=0),
        },
    },
)


# --------------------------------------------------------------------------- request-id propagation
@before_task_publish.connect
def _inject_request_id(headers=None, **kwargs):
    rid = request_id_var.get()
    if headers is not None and rid and rid != '-':
        headers['request_id'] = rid


@task_prerun.connect
def _restore_request_id(task=None, **kwargs):
    rid = getattr(getattr(task, 'request', None), 'request_id', None)
    request_id_var.set(rid or '-')


@task_postrun.connect
def _clear_request_id(**kwargs):
    request_id_var.set('-')


# --------------------------------------------------------------------------- flask integration
def init_celery(app):
    """Make every task run inside the Flask app context and record permanent failures (DLQ)."""

    class PPATask(celery.Task):
        abstract = True

        def __call__(self, *args, **kwargs):
            with app.app_context():
                return self.run(*args, **kwargs)

        def on_failure(self, exc, task_id, args, kwargs, einfo):
            # Reached only when the task is finished for good (retries exhausted / non-retryable).
            from dead_letter import push_dead_letter
            with app.app_context():
                push_dead_letter(self.name, task_id, args, kwargs, exc)

    celery.Task = PPATask
    celery.conf.update(
        broker_url=app.config.get('CELERY_BROKER_URL', Config.CELERY_BROKER_URL),
        result_backend=app.config.get('CELERY_RESULT_BACKEND', Config.CELERY_RESULT_BACKEND),
    )
    return celery


# When loaded by a Celery process (worker / beat / flower) build the Flask app so tasks can use
# db.session & current_app. Importing ``app`` creates it and calls init_celery() exactly once.
if 'celery' in (sys.argv[0] or '').lower():
    try:
        import app as _flask_module  # noqa: F401
    except Exception:  # pragma: no cover
        log.exception('celery_flask_app_init_failed')
        raise
