import redis
import json
from flask import current_app

_redis_client = None


def get_redis():
    """get redis client (singleton)"""
    global _redis_client
    if _redis_client is None:
        try:
            _redis_client = redis.from_url(
                current_app.config.get('REDIS_URL', 'redis://localhost:6379/0'),
                decode_responses=True,
                socket_connect_timeout=2
            )
            _redis_client.ping()
        except Exception as e:
            print(f'[!] Redis connection failed: {e}')
            _redis_client = None
    else:
        # check if connection is still alive
        try:
            _redis_client.ping()
        except Exception:
            _redis_client = None  # reset so it retries next time
    return _redis_client


def cache_get(key):
    r = get_redis()
    if r is None:
        return None
    try:
        data = r.get(key)
        if data:
            return json.loads(data)
    except Exception:
        pass
    return None


def cache_set(key, value, ttl=300):
    # default 5 min TTL
    r = get_redis()
    if r is None:
        return False
    try:
        r.setex(key, ttl, json.dumps(value))
        return True
    except Exception:
        return False


def cache_delete(key):
    r = get_redis()
    if r is None:
        return False
    try:
        r.delete(key)
        return True
    except Exception:
        return False


def cache_delete_pattern(pattern):
    # used for invalidating related cache entries
    r = get_redis()
    if r is None:
        return False
    try:
        keys = r.keys(pattern)
        if keys:
            r.delete(*keys)
        return True
    except Exception:
        return False
