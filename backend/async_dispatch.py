"""Run a Celery task asynchronously when the queue is usable, otherwise inline.

"Usable" means: durable Redis (the broker) reachable AND at least one worker answering pings
(result cached 15s so we don't ping on every request). This removes the old "job stays pending
forever" failure mode where Redis was up but no worker was running.
"""
import logging

from flask import current_app

from cache import cache_get, cache_set, get_state_redis
import metrics

log = logging.getLogger(__name__)

_WORKERS_KEY = 'ppa:workers_alive'


def worker_count(use_cache=True):
    """Number of Celery workers answering a ping (0 if broker/workers are down)."""
    if use_cache:
        cached = cache_get(_WORKERS_KEY)
        if cached is not None:
            return int(cached)
    count = 0
    if get_state_redis() is not None:
        try:
            from celery_worker import celery
            replies = celery.control.inspect(timeout=0.8).ping() or {}
            count = len(replies)
        except Exception as e:  # noqa: BLE001
            log.warning('worker_ping_failed', extra={'event': 'worker_ping_failed', 'error': str(e)[:200]})
    cache_set(_WORKERS_KEY, count, ttl=15)
    return count


def dispatch(task, *args, **kwargs):
    """Queue ``task`` if possible, else run it synchronously. Returns 'queued' or 'sync'."""
    if not current_app.config.get('FORCE_SYNC_TASKS') and worker_count() > 0:
        try:
            task.apply_async(args=args, kwargs=kwargs)
            return 'queued'
        except Exception as e:  # noqa: BLE001 - broker died between check and publish
            log.warning('queue_publish_failed_fallback_sync',
                        extra={'event': 'queue_publish_failed_fallback_sync', 'task': task.name, 'error': str(e)[:200]})
            cache_set(_WORKERS_KEY, 0, ttl=15)
    else:
        log.warning('no_worker_fallback_sync', extra={'event': 'no_worker_fallback_sync', 'task': task.name})
    metrics.inc(metrics.TASK_FALLBACKS)
    try:
        task(*args, **kwargs)
    except Exception:  # noqa: BLE001
        log.exception('sync_task_failed', extra={'event': 'sync_task_failed', 'task': task.name})
    return 'sync'
