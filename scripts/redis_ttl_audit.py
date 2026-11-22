#!/usr/bin/env python
"""Redis key-expiration audit: every key should have a TTL, otherwise it leaks memory forever.

Usage:
    python scripts/redis_ttl_audit.py                       # uses REDIS_URL / STATE_REDIS_URL / CELERY_BROKER_URL
    python scripts/redis_ttl_audit.py redis://localhost:6379/0 redis://localhost:6379/2

Exit code 1 if any application key (prefix ppa: or bl:) has no TTL. Celery's own bookkeeping keys
(queues, unacked, kombu bindings) are persistent by design and are reported separately, not as failures.

Equivalent one-liner:  redis-cli --scan | xargs -I{} sh -c 'echo "{} $(redis-cli TTL {})"'
"""
import os
import sys

import redis

APP_PREFIXES = ('ppa:', 'bl:')
CELERY_PREFIXES = ('_kombu', 'unacked', 'celery', 'ppa\x06\x16', 'ppa')   # queue lists / bindings


def audit(url):
    r = redis.from_url(url, decode_responses=True)
    bad, ok, celery_keys = [], 0, 0
    for key in r.scan_iter(count=500):
        ttl = r.ttl(key)
        if key.startswith(APP_PREFIXES):
            if ttl == -1:
                bad.append(key)
            else:
                ok += 1
        elif key.startswith(CELERY_PREFIXES) or r.type(key) in ('list', 'set', 'zset', 'hash') and ttl == -1:
            celery_keys += 1
    print(f'{url}\n   app keys with TTL: {ok}   WITHOUT TTL: {len(bad)}   celery/broker keys (persistent by design): {celery_keys}')
    for key in bad[:20]:
        print(f'   !! no TTL: {key}')
    return len(bad)


def main():
    urls = sys.argv[1:] or sorted({
        os.environ.get('REDIS_URL', 'redis://localhost:6379/0'),
        os.environ.get('STATE_REDIS_URL', 'redis://localhost:6379/2'),
    })
    failures = sum(audit(u) for u in urls)
    sys.exit(1 if failures else 0)


if __name__ == '__main__':
    main()
