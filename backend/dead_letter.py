"""Dead-letter queue: permanently failed Celery tasks are parked in a Redis list for inspection/replay."""
import json
import logging
import time

from cache import _call

log = logging.getLogger(__name__)

DLQ_KEY = 'ppa:dead_letter'
DLQ_MAX = 1000

# Fallback when the state Redis is down at failure time (process-local, best-effort).
_memory = []


def push_dead_letter(task_name, task_id, args, kwargs, exc):
    entry = {
        'task': task_name,
        'task_id': task_id,
        'args': list(args or []),
        'kwargs': dict(kwargs or {}),
        'error': f'{type(exc).__name__}: {exc}'[:500],
        'failed_at': time.time(),
    }
    log.error('task_dead_lettered', extra={'event': 'task_dead_lettered', 'task': task_name, 'task_id': task_id, 'error': entry['error']})
    payload = json.dumps(entry, default=str)

    def _push(r):
        pipe = r.pipeline()
        pipe.lpush(DLQ_KEY, payload)
        pipe.ltrim(DLQ_KEY, 0, DLQ_MAX - 1)
        pipe.execute()
        return True

    _, ok = _call('state', _push)
    if not ok:
        _memory.insert(0, entry)
        del _memory[DLQ_MAX:]
    return entry


def list_dead_letters(limit=50):
    res, ok = _call('state', lambda r: r.lrange(DLQ_KEY, 0, limit - 1))
    items = [json.loads(x) for x in res] if ok and res else []
    return items + _memory[:max(0, limit - len(items))]


def replay_dead_letter(task_id):
    """Re-enqueue a dead-lettered task and remove it from the DLQ. Returns True if found."""
    from celery_worker import celery

    def _find(r):
        for raw in r.lrange(DLQ_KEY, 0, -1):
            if json.loads(raw).get('task_id') == task_id:
                return raw
        return None

    raw, ok = _call('state', _find)
    entry = json.loads(raw) if raw else next((e for e in _memory if e['task_id'] == task_id), None)
    if not entry:
        return False
    celery.send_task(entry['task'], args=entry['args'], kwargs=entry['kwargs'])
    if raw:
        _call('state', lambda r: r.lrem(DLQ_KEY, 1, raw))
    else:
        _memory.remove(entry)
    log.warning('task_replayed', extra={'event': 'task_replayed', 'task': entry['task'], 'task_id': task_id})
    return True
