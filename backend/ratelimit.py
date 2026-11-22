"""Fixed-window rate limiter backed by durable (state) Redis, with in-memory fallback.

The Redis path is one atomic MULTI/EXEC (SET NX EX + INCR + TTL), so a crash can never leave a
counter without an expiry (the previous INCR-then-EXPIRE sequence could lock an IP out forever).
"""
import threading
import time
from functools import wraps

from flask import current_app, jsonify

from cache import _call
import metrics

_lock = threading.Lock()
_mem = {}   # key -> [count, reset_at]


def _mem_hit(key, window, increment=True):
    now = time.time()
    with _lock:
        if len(_mem) > 5000:  # opportunistic cleanup
            for k in [k for k, v in _mem.items() if v[1] <= now]:
                _mem.pop(k, None)
        entry = _mem.get(key)
        if not entry or entry[1] <= now:
            entry = [0, now + window]
            if increment:
                _mem[key] = entry
        if increment:
            entry[0] += 1
        return entry[0], max(1, int(entry[1] - now))


def _redis_hit(r, key, window):
    pipe = r.pipeline(transaction=True)
    pipe.set(key, 0, ex=window, nx=True)
    pipe.incr(key)
    pipe.ttl(key)
    _, count, ttl = pipe.execute()
    return int(count), max(1, int(ttl) if ttl and ttl > 0 else window)


def hit(scope, identifier, limit, window=60):
    """Record one request. Returns (allowed, retry_after_seconds)."""
    key = f"ppa:rl:{scope}:{identifier}"
    res, ok = _call('state', lambda r: _redis_hit(r, key, window))
    count, ttl = res if ok else _mem_hit(key, window)
    if count > limit:
        metrics.inc(metrics.RATE_LIMITED, scope)
    return count <= limit, ttl


def current(scope, identifier, window=60):
    """Current count without incrementing."""
    key = f"ppa:rl:{scope}:{identifier}"

    def _get(r):
        v = r.get(key)
        return int(v) if v else 0, r.ttl(key)

    res, ok = _call('state', _get)
    if ok:
        return res[0], max(1, res[1] if res[1] and res[1] > 0 else window)
    count, ttl = _mem_hit(key, window, increment=False)
    return count, ttl


def reset(scope, identifier):
    key = f"ppa:rl:{scope}:{identifier}"
    _call('state', lambda r: r.delete(key))
    with _lock:
        _mem.pop(key, None)


def clear_memory():
    with _lock:
        _mem.clear()


def too_many(retry_after, message='Too many requests. Please slow down.'):
    resp = jsonify({'error': message, 'retry_after': retry_after})
    resp.status_code = 429
    resp.headers['Retry-After'] = str(retry_after)
    return resp


def rate_limit(scope, config_key='HEAVY_ENDPOINT_RATE_LIMIT', window=60):
    """Per-user limiter for expensive endpoints. Use *below* @role_required/@login_required:

        @role_required('admin')
        @rate_limit('report')
        def handler(user): ...
    """
    def decorator(f):
        @wraps(f)
        def wrapper(user, *args, **kwargs):
            limit = current_app.config.get(config_key, 10)
            allowed, retry_after = hit(scope, user.id, limit, window)
            if not allowed:
                return too_many(retry_after, f'Rate limit exceeded ({limit}/{window}s). Try again in {retry_after}s.')
            return f(user, *args, **kwargs)
        return wrapper
    return decorator
