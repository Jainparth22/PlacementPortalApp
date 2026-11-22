import json

import cache


def test_set_get_delete(backend):
    assert cache.cache_get('k1') is None
    cache.cache_set('k1', {'a': 1}, ttl=60)
    assert cache.cache_get('k1') == {'a': 1}
    cache.cache_delete('k1')
    assert cache.cache_get('k1') is None


def test_namespace_invalidation_is_instant(backend):
    key = cache.make_key('drives', 'page', 1)
    cache.cache_set(key, ['old'])
    assert cache.cache_get(key) == ['old']
    cache.invalidate('drives')
    assert cache.cache_get(key) is None          # same key, but its version token is stale
    cache.cache_set(key, ['new'])
    assert cache.cache_get(key) == ['new']


def test_other_namespaces_untouched(backend):
    k = cache.make_key('stats', 'admin')
    cache.cache_set(k, {'x': 1})
    cache.invalidate('drives')
    assert cache.cache_get(cache.make_key('stats', 'admin')) == {'x': 1}


def test_keys_are_versioned(app, backend):
    key = cache.make_key('stats', 'admin')
    assert key.startswith('ppa:v1:stats:')
    app.config['CACHE_KEY_VERSION'] = 'v2'
    try:
        assert cache.make_key('stats', 'admin').startswith('ppa:v2:stats:')
    finally:
        app.config['CACHE_KEY_VERSION'] = 'v1'


def test_long_or_unsafe_key_parts_are_hashed(app):
    key = cache.make_key('drives', 'search with spaces *', 'x' * 200)
    assert ' ' not in key and '*' not in key and len(key) < 120


def test_every_redis_key_has_a_ttl(fake_redis):
    cache.cache_set('plain', 1)
    cache.cache_set('plain2', 1, ttl=10 ** 9)        # absurd ttl is capped
    cache.invalidate('drives')
    for key in fake_redis.scan_iter('*'):
        ttl = fake_redis.ttl(key)
        assert ttl > 0, f'{key} has no TTL'
    assert fake_redis.ttl('plain2') <= cache.MAX_TTL * 1.1


def test_ttl_jitter_stays_in_bounds(app):
    values = {cache._effective_ttl(100) for _ in range(200)}
    assert min(values) >= 90 and max(values) <= 110 and len(values) > 1


def test_get_or_set_runs_loader_once(backend):
    calls = []

    def loader():
        calls.append(1)
        return {'v': len(calls)}

    assert cache.cache_get_or_set('hot', loader, ttl=30) == {'v': 1}
    assert cache.cache_get_or_set('hot', loader, ttl=30) == {'v': 1}
    assert len(calls) == 1


def test_get_or_set_releases_lock_on_loader_error(fake_redis):
    def boom():
        raise RuntimeError('db down')

    try:
        cache.cache_get_or_set('k', boom)
    except RuntimeError:
        pass
    assert not fake_redis.exists('k:lock')


def test_delete_pattern_uses_scan(fake_redis):
    for i in range(5):
        cache.cache_set(f'tmp:{i}', i)
    cache.cache_set('keep', 1)
    cache.cache_delete_pattern('tmp:*')
    assert cache.cache_get('keep') == 1
    assert all(cache.cache_get(f'tmp:{i}') is None for i in range(5))


def test_once_is_first_caller_only(backend):
    assert cache.once('job-x', 60) is True
    assert cache.once('job-x', 60) is False


def test_memory_fallback_is_bounded(app):
    store = cache._MemoryStore(max_items=3)
    for i in range(10):
        store.set(f'k{i}', i, 60)
    assert len(store) == 3 and store.get('k9') == 9 and store.get('k0') is None


def test_degrades_to_memory_when_redis_dies(app, fake_redis, monkeypatch):
    from redis.exceptions import ConnectionError as RConn
    cache.cache_set('a', 1)

    def dead(*a, **k):
        raise RConn('boom')

    monkeypatch.setattr(fake_redis, 'get', dead)
    monkeypatch.setattr(fake_redis, 'set', dead)
    # no exception: falls back to the in-process store and the circuit breaker opens
    cache.cache_set('b', 2)
    assert cache.cache_get('b') == 2
    assert cache._ROLES['cache'].down_until > 0


def test_stats_report_hit_rate(backend):
    cache.cache_get('missing')
    cache.cache_set('present', 1)
    cache.cache_get('present')
    stats = cache.cache_stats()
    assert stats['hits'] == 1 and stats['misses'] == 1 and stats['hit_rate'] == 0.5
    assert stats['backend'] in ('redis', 'memory')


def test_values_are_json_in_redis(fake_redis):
    cache.cache_set('j', {'a': [1, 2]})
    assert json.loads(fake_redis.get('j')) == {'a': [1, 2]}


# ----------------------------------------------------------------------------- hardening (race / outage / eviction)
def test_invalidation_during_loader_is_not_served(backend):
    """Loader read old rows, an invalidation fired before the write: the stale result must never be served."""
    key = cache.make_key('drives', 'race')

    def loader():
        cache.invalidate('drives')       # concurrent writer changed the data while we were computing
        return ['computed-from-old-rows']

    assert cache.cache_get_or_set(key, loader) == ['computed-from-old-rows']    # caller still gets its value
    assert cache.cache_get(key) is None                                         # ...but it was not cached as fresh


def test_invalidation_during_redis_outage_is_replayed_on_reconnect(app, fake_redis):
    import time
    key = cache.make_key('drives', 'outage')
    cache.cache_set(key, ['cached-before-outage'])
    # --- outage: nothing reachable
    cache.use_redis_clients(None, None)
    cache._ROLES['cache'].down_until = time.monotonic() + 100
    cache.invalidate('drives')                       # data changed while Redis was away
    assert 'drives' in cache._pending_invalidations
    # --- Redis is back (same server, entry still there)
    cache.use_redis_clients(fake_redis, None)
    cache._flush_pending(fake_redis)
    assert not cache._pending_invalidations
    assert cache.cache_get(key) is None              # old entry must NOT be served as fresh


def test_evicted_version_token_cannot_resurrect_old_entries(fake_redis):
    key = cache.make_key('drives', 'evict')
    cache.cache_set(key, ['v1-data'])
    cache.invalidate('drives')                       # v1-data is now stale
    fake_redis.delete(cache._ns_version_key('drives'))   # allkeys-lru evicts the token
    assert cache.cache_get(key) is None              # a fresh token is minted; stale entry stays dead
    assert fake_redis.ttl(cache._ns_version_key('drives')) > 0


def test_read_is_a_single_pipelined_round_trip(fake_redis, monkeypatch):
    key = cache.make_key('stats', 'one-trip')
    cache.cache_set(key, {'a': 1})
    executed = []
    real_pipeline = fake_redis.pipeline

    def spy(*a, **k):
        pipe = real_pipeline(*a, **k)
        real_execute = pipe.execute
        pipe.execute = lambda *x, **y: executed.append(1) or real_execute(*x, **y)
        return pipe

    monkeypatch.setattr(fake_redis, 'pipeline', spy)
    assert cache.cache_get(key) == {'a': 1}
    assert len(executed) == 1


def test_memory_fallback_ttl_is_capped_while_degraded(app):
    import time
    key = cache.make_key('stats', 'degraded')
    cache.cache_set(key, 1, ttl=3600)
    expires_at = cache._memory.data[key][0]
    assert expires_at - time.time() <= cache.MEMORY_TTL_CAP + 1


def test_stampede_lock_is_only_released_by_its_owner(fake_redis):
    key = cache.make_key('stats', 'lock-owner')

    def loader():
        fake_redis.set(f'{key}:lock', 'someone-else')    # our lock expired and another worker took it
        return 1

    cache.cache_get_or_set(key, loader)
    assert fake_redis.get(f'{key}:lock') == 'someone-else'


def test_corrupt_redis_value_is_a_miss_not_an_error(fake_redis):
    key = cache.make_key('stats', 'corrupt')
    fake_redis.set(key, '{not json')
    assert cache.cache_get(key) is None
    assert cache.cache_get_or_set(key, lambda: {'ok': True}) == {'ok': True}


def test_hit_counted_once_per_get_or_set(backend):
    key = cache.make_key('stats', 'count')
    cache.cache_get_or_set(key, lambda: 1)
    cache.cache_get_or_set(key, lambda: 1)
    s = cache.cache_stats()
    assert s['misses'] == 1 and s['hits'] == 1


def test_plain_keys_are_not_versioned(fake_redis):
    cache.cache_set('plain', {'x': 1})
    assert json.loads(fake_redis.get('plain')) == {'x': 1}       # no wrapper for non-namespaced keys
