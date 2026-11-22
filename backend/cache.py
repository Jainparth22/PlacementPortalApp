"""Redis access layer: caching, durable state, and fallbacks.

Two logical Redis roles (see config.py):
  * cache  - disposable data (get_redis)        -> REDIS_URL
  * state  - JWT blacklist, rate limits, locks  -> STATE_REDIS_URL (durable, noeviction)
The Celery broker is configured separately but normally lives on the same instance as ``state``.

Design
------
* One connection pool per role, created lazily, with socket timeouts, TCP health checks and
  retry-with-exponential-backoff (redis-py Retry/ExponentialBackoff) for transient errors.
* A tiny circuit breaker: after a connection failure the role is considered "down" for a few
  seconds so requests don't each wait for a connect timeout. (The previous version PING-ed
  Redis before *every* command - one extra round-trip per cache access.)
* If Redis is down, a bounded in-process TTL/LRU cache (and in-memory counters) keep the app
  working - degraded (per-process), never crashing.
* Versioned keys: ``ppa:<CACHE_KEY_VERSION>:<namespace>:<params>`` holding ``{"v": <ns-token>, "d": data}``.
  - Bump CACHE_KEY_VERSION after changing a cached payload shape -> old keys are ignored.
  - ``invalidate("drives")`` replaces the namespace token (O(1), no KEYS/SCAN): every entry of that
    namespace is instantly invalid. A read is a single pipelined round trip (token + entry).
  - Race-safe: the token is read before the loader runs, so a result computed across an invalidation is
    stored with the old token and never served. Tokens are timestamps and are re-minted with SET NX if
    Redis evicts them, so eviction can't resurrect old entries.
  - Invalidations that happen while Redis is unreachable are replayed on reconnect, otherwise entries
    cached before the outage would come back as "fresh".
* Cache stampede protection: ``get_or_set`` takes a short NX lock so only one worker rebuilds
  an expired hot key; the others briefly wait for it.
* Every cache key has a TTL (hard-capped by MAX_TTL, jittered +-10%) - see scripts/redis_ttl_audit.py.
"""
import hashlib
import json
import logging
import random
import threading
import time
import uuid
from collections import OrderedDict

import redis
from flask import current_app
from redis.backoff import ExponentialBackoff
from redis.exceptions import ConnectionError as RedisConnectionError
from redis.exceptions import RedisError, TimeoutError as RedisTimeoutError
from redis.retry import Retry

from config import Config
import metrics

log = logging.getLogger(__name__)

MAX_TTL = 6 * 3600          # hard cap for any cache entry
NS_VERSION_TTL = 7 * 86400  # namespace counters (must outlive MAX_TTL)
BREAKER_SECONDS = 5         # first back-off after a connection failure; doubles per consecutive failure
BREAKER_MAX_SECONDS = 60    # ...up to this (a dead Redis is probed at most once a minute)


# --------------------------------------------------------------------------- config helpers
def _cfg(key, default=None):
    try:
        return current_app.config.get(key, default)
    except RuntimeError:  # outside app context (scripts, tests)
        return getattr(Config, key, default)


# --------------------------------------------------------------------------- client handles
class _Role:
    """Lazy redis client for one role, with a circuit breaker."""

    def __init__(self, name, url_key):
        self.name = name
        self.url_key = url_key
        self.client = None
        self.url = None
        self.down_until = 0.0
        self.failures = 0
        self.lock = threading.Lock()

    def reset(self):
        with self.lock:
            self.client = None
            self.down_until = 0.0
            self.failures = 0

    def mark_down(self, exc=None):
        self.failures += 1
        self.down_until = time.monotonic() + min(BREAKER_SECONDS * 2 ** (self.failures - 1), BREAKER_MAX_SECONDS)
        self.client = None
        log.warning('redis_down', extra={'event': 'redis_down', 'role': self.name, 'error': str(exc)[:200] if exc else None})

    def get(self):
        if self.client is not None:
            return self.client
        if time.monotonic() < self.down_until:
            return None
        with self.lock:
            if self.client is not None:
                return self.client
            url = _cfg(self.url_key)
            if not url:
                return None
            try:
                client = redis.Redis.from_url(
                    url,
                    decode_responses=True,
                    socket_connect_timeout=1.0,
                    socket_timeout=2,
                    health_check_interval=30,
                    max_connections=int(_cfg('REDIS_MAX_CONNECTIONS', 30)),
                    retry=Retry(ExponentialBackoff(cap=0.3, base=0.05), 1),
                    retry_on_error=[RedisConnectionError, RedisTimeoutError],
                )
                client.ping()
                self.client = client
                self.url = url
                self.failures = 0
                if self.name == 'cache':
                    _flush_pending(client)      # apply invalidations missed during the outage
                return client
            except Exception as e:  # noqa: BLE001 - any failure => degrade
                self.mark_down(e)
                return None


_ROLES = {'cache': _Role('cache', 'REDIS_URL'), 'state': _Role('state', 'STATE_REDIS_URL')}


def get_redis():
    """Redis client for disposable cache data, or None when unavailable."""
    return _ROLES['cache'].get()


def get_state_redis():
    """Redis client for durable state (blacklist, rate limits, locks, DLQ), or None."""
    return _ROLES['state'].get()


def use_redis_clients(cache=None, state=None):
    """Inject clients (tests / fakeredis). Pass None to clear."""
    for role, client in (('cache', cache), ('state', state)):
        _ROLES[role].client = client
        _ROLES[role].down_until = 0.0
        if client is None:
            _ROLES[role].reset()


def reset_redis():
    for r in _ROLES.values():
        r.reset()


def _call(role, fn, default=None):
    """Run ``fn(client)`` against a role; on connection trouble trip the breaker and return default."""
    handle = _ROLES[role]
    client = handle.get()
    if client is None:
        return default, False
    try:
        return fn(client), True
    except (RedisConnectionError, RedisTimeoutError) as e:
        handle.mark_down(e)
    except RedisError as e:
        log.warning('redis_error', extra={'event': 'redis_error', 'role': role, 'error': str(e)[:200]})
    return default, False


# --------------------------------------------------------------------------- memory fallback
class _MemoryStore:
    """Thread-safe TTL + LRU dict used when Redis is unavailable."""

    def __init__(self, max_items=512):
        self.max_items = max_items
        self.data = OrderedDict()   # key -> (expires_at, value)
        self.lock = threading.Lock()

    def get(self, key):
        with self.lock:
            item = self.data.get(key)
            if not item:
                return None
            if item[0] <= time.time():
                self.data.pop(key, None)
                return None
            self.data.move_to_end(key)
            return item[1]

    def set(self, key, value, ttl):
        with self.lock:
            self.data[key] = (time.time() + ttl, value)
            self.data.move_to_end(key)
            while len(self.data) > self.max_items:
                self.data.popitem(last=False)

    def set_nx(self, key, value, ttl):
        with self.lock:
            item = self.data.get(key)
            if item and item[0] > time.time():
                return False
            self.data[key] = (time.time() + ttl, value)
            return True

    def delete(self, key):
        with self.lock:
            self.data.pop(key, None)

    def delete_prefix(self, prefix):
        with self.lock:
            for k in [k for k in self.data if k.startswith(prefix)]:
                self.data.pop(k, None)

    def clear(self):
        with self.lock:
            self.data.clear()

    def __len__(self):
        return len(self.data)


_memory = _MemoryStore()
_ns_memory = {}   # namespace -> version (fallback only)

# stats (per process)
_stats = {'hits': 0, 'misses': 0, 'memory_hits': 0, 'sets': 0, 'invalidations': 0, 'stampede_waits': 0}


def cache_stats():
    total = _stats['hits'] + _stats['misses']
    redis_ok = get_redis() is not None
    return {
        **_stats,
        'hit_rate': round(_stats['hits'] / total, 3) if total else None,
        'backend': 'redis' if redis_ok else 'memory',
        'memory_items': len(_memory),
    }


# --------------------------------------------------------------------------- keys & namespace versions
# Entry layout in Redis for namespaced keys:   ppa:<ver>:<ns>:<params>  ->  {"v": <ns-version>, "d": <data>}
# Namespace version key:                        ppa:<ver>:nsv:<ns>       ->  opaque token (time_ns)
#
# * Reading = ONE round trip (pipeline of GET nsv + GET entry); the entry is valid only if its stored
#   version equals the current one. (The first design needed a separate GET for the version first.)
# * invalidate(ns) replaces the token. Old entries become invalid immediately and are simply
#   overwritten on the next miss (no orphaned keys piling up).
# * The version is captured BEFORE the loader runs and stored with the entry, so a write that raced with an
#   invalidation (loader read old DB rows, invalidate fired, then set) is stored with a stale version and
#   is never served.
# * Tokens are timestamps, not small counters, and a missing token is re-created with SET NX: if Redis
#   evicts the token (allkeys-lru) the namespace gets a brand-new version instead of falling back to "0"
#   and resurrecting old entries.
_pending_invalidations = set()   # invalidations that could not reach Redis (outage) - replayed on reconnect
MEMORY_TTL_CAP = 30              # while Redis is down each process has its own copy: keep it short


def _prefix():
    return f"ppa:{_cfg('CACHE_KEY_VERSION', 'v1')}"


def _ns_version_key(ns):
    return f"{_prefix()}:nsv:{ns}"


def _new_token():
    return str(time.time_ns())


def _ns_of(key):
    """Namespace of a key built by make_key(), else None (plain keys are not versioned)."""
    pre = _prefix() + ':'
    if key.startswith(pre):
        parts = key[len(pre):].split(':', 1)
        if len(parts) == 2 and parts[0] != 'nsv':
            return parts[0]
    return None


def make_key(ns, *parts):
    """Namespaced key (pure function - no Redis round trip). Long/unsafe parts are hashed."""
    raw = ':'.join(str(p) for p in parts)
    if len(raw) > 60 or any(c in raw for c in ' *?[]\n'):
        raw = hashlib.sha1(raw.encode('utf-8')).hexdigest()
    return f"{_prefix()}:{ns}:{raw}"


def _redis_read(r, key, ns):
    """-> (found, data, version). One round trip."""
    if ns is None:
        raw = r.get(key)
        return (raw is not None), (json.loads(raw) if raw is not None else None), None
    pipe = r.pipeline(transaction=False)
    pipe.get(_ns_version_key(ns))
    pipe.get(key)
    version, raw = pipe.execute()
    if version is None:                       # first use, or evicted: mint a new version
        token = _new_token()
        r.set(_ns_version_key(ns), token, nx=True, ex=NS_VERSION_TTL)
        version = r.get(_ns_version_key(ns))
        return False, None, version
    if raw is None:
        return False, None, version
    entry = json.loads(raw)
    if isinstance(entry, dict) and entry.get('v') == version:
        return True, entry.get('d'), version
    return False, None, version               # stale version


def _read(key):
    """-> (found, data, version-at-read-time). Falls back to the in-process store when Redis is down."""
    ns = _ns_of(key)
    res, ok = _call('cache', lambda r: _redis_read(r, key, ns))
    if ok:
        return res
    local = _memory.get(key)
    version = _ns_memory.get(ns, 0) if ns else None
    if local is not None:
        if ns is None:
            return True, local, None
        if local.get('v') == version:
            return True, local.get('d'), version
    return False, None, version


def _write(key, data, ttl, version):
    ns = _ns_of(key)
    ttl = _effective_ttl(ttl)
    _stats['sets'] += 1

    def _set(r):
        if ns is None:
            payload = json.dumps(data, default=str)
        else:
            ver = version
            if ver is None:                   # standalone cache_set(): use the current version
                ver = r.get(_ns_version_key(ns))
                if ver is None:
                    r.set(_ns_version_key(ns), _new_token(), nx=True, ex=NS_VERSION_TTL)
                    ver = r.get(_ns_version_key(ns))
            payload = json.dumps({'v': ver, 'd': data}, default=str)
        r.set(key, payload, ex=ttl)
        return True

    _, ok = _call('cache', _set)
    if ok:
        return True
    mem_ver = version if isinstance(version, int) else (_ns_memory.get(ns, 0) if ns else None)
    _memory.set(key, data if ns is None else {'v': mem_ver, 'd': data}, min(ttl, MEMORY_TTL_CAP))
    return False


def ns_version(ns):
    """Current namespace token (for diagnostics/tests)."""
    res, ok = _call('cache', lambda r: r.get(_ns_version_key(ns)))
    return res if ok else _ns_memory.get(ns, 0)


def invalidate(*namespaces):
    """Invalidate whole namespaces in O(1) by replacing their version token."""
    for ns in namespaces:
        _stats['invalidations'] += 1
        _ns_memory[ns] = _ns_memory.get(ns, 0) + 1          # always bump the local copy too
        _memory.delete_prefix(f"{_prefix()}:{ns}:")
        _, ok = _call('cache', lambda r, ns=ns: r.set(_ns_version_key(ns), _new_token(), ex=NS_VERSION_TTL))
        if not ok:
            # Redis unreachable: entries cached there BEFORE the outage would be served as fresh after it
            # recovers. Remember to invalidate them as soon as we reconnect (see _flush_pending).
            _pending_invalidations.add(ns)


def _flush_pending(client):
    """Called when the cache role (re)connects: apply invalidations that happened during the outage."""
    if not _pending_invalidations:
        return
    for ns in list(_pending_invalidations):
        try:
            client.set(_ns_version_key(ns), _new_token(), ex=NS_VERSION_TTL)
            _pending_invalidations.discard(ns)
        except RedisError:
            return


# --------------------------------------------------------------------------- basic ops
def _effective_ttl(ttl):
    ttl = int(ttl if ttl else _cfg('CACHE_DEFAULT_TTL', 300))
    ttl = max(1, min(ttl, MAX_TTL))
    return max(1, int(ttl * random.uniform(0.9, 1.1)))   # jitter avoids synchronized expiry


def cache_get(key):
    try:
        found, data, _ = _read(key)
    except ValueError:                      # corrupt JSON in Redis: treat as a miss
        found, data = False, None
    if found:
        _stats['hits'] += 1
        metrics.inc(metrics.CACHE, 'hit')
        if not _ROLES['cache'].client:
            _stats['memory_hits'] += 1
        return data
    _stats['misses'] += 1
    metrics.inc(metrics.CACHE, 'miss')
    return None


def cache_set(key, value, ttl=None):
    return _write(key, value, ttl, None)


def cache_delete(key):
    _call('cache', lambda r: r.delete(key))
    _memory.delete(key)
    return True


def cache_delete_pattern(pattern):
    """Delete keys matching a glob using SCAN (non-blocking, unlike KEYS)."""
    def _scan(r):
        batch = []
        for k in r.scan_iter(match=pattern, count=200):
            batch.append(k)
            if len(batch) >= 200:
                r.unlink(*batch)
                batch = []
        if batch:
            r.unlink(*batch)
        return True

    _call('cache', _scan)
    _memory.delete_prefix(pattern.rstrip('*'))
    return True


def cache_get_or_set(key, loader, ttl=None, lock_seconds=10, wait_seconds=2.0):
    """Cache-aside with stampede protection and race-safe writes.

    On a miss exactly one caller takes an NX lock and runs ``loader()``; concurrent callers wait briefly
    for the cached value instead of hammering the database. The namespace version is captured *before*
    the loader runs, so if an invalidation happens meanwhile the (now stale) result is stored under the
    old version and is never served.
    """
    try:
        found, data, version = _read(key)
    except ValueError:
        found, data, version = False, None, None
    if found:
        _stats['hits'] += 1
        metrics.inc(metrics.CACHE, 'hit')
        return data
    _stats['misses'] += 1
    metrics.inc(metrics.CACHE, 'miss')

    lock_key = f"{key}:lock"
    token = uuid.uuid4().hex
    got_lock, ok = _call('cache', lambda r: r.set(lock_key, token, nx=True, ex=lock_seconds))
    if ok and not got_lock:
        deadline = time.monotonic() + wait_seconds
        while time.monotonic() < deadline:
            time.sleep(0.05)
            _stats['stampede_waits'] += 1
            try:
                found, data, _ = _read(key)
            except ValueError:
                found = False
            if found:
                _stats['hits'] += 1
                return data
    try:
        value = loader()
        _write(key, value, ttl, version)
        return value
    finally:
        if ok and got_lock:
            # only release OUR lock (it may have expired and been taken by someone else meanwhile)
            _call('cache', lambda r: r.delete(lock_key) if r.get(lock_key) == token else 0)


# --------------------------------------------------------------------------- durable helpers
_once_memory = _MemoryStore(max_items=2048)


def once(key, ttl):
    """True the first time ``key`` is seen within ``ttl`` seconds (SET NX EX), else False.

    Used for idempotency guards (e.g. "email this monthly report only once").
    Uses durable state Redis, falls back to process memory.
    """
    full = f"ppa:once:{key}"
    res, ok = _call('state', lambda r: r.set(full, '1', nx=True, ex=ttl))
    if ok:
        return bool(res)
    return _once_memory.set_nx(full, '1', ttl)


def redis_health():
    """Per-role connectivity for /health."""
    out = {}
    for name in ('cache', 'state'):
        value, ok = _call(name, lambda r: r.ping())
        out[name] = 'connected' if ok and value else 'down'
    return out
