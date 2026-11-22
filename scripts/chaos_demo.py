#!/usr/bin/env python
"""Chaos demo (script for the 2-minute video): kill Redis, show the app keeps working.

Prereq:   docker compose up -d --build        (web on :5001, seeded demo data)
Run:      python scripts/chaos_demo.py [--base http://localhost:5001] [--admin EMAIL] [--password PW]

Story it walks through (record your screen while it runs, with Flower open if you like):
  1. Redis healthy + worker alive  -> report job is QUEUED and processed by the Celery worker
  2. docker compose stop redis-queue redis-cache   (chaos!)
  3. /health degrades gracefully; cache falls back to in-process memory
  4. Generate another report        -> runs SYNCHRONOUSLY inside the request, still completes
  5. Bring Redis back               -> back to queued/async automatically (circuit breaker closes)
"""
import argparse
import subprocess
import sys
import time

import requests


def say(msg):
    print(f'\n\033[1;36m▶ {msg}\033[0m')


def health(base):
    d = requests.get(f'{base}/health', timeout=10).json()
    print(f"   status={d['status']}  redis={d['redis']}  celery={d['celery']}  cache.backend={d['cache']['backend']}")
    return d


def generate_and_wait(base, headers):
    r = requests.post(f'{base}/api/v1/admin/reports/generate', headers=headers, timeout=60)
    body = r.json()
    print(f"   POST /reports/generate -> {r.status_code}  mode={body.get('mode')}  job_id={body.get('job_id')}")
    for _ in range(40):
        job = requests.get(f"{base}/api/v1/jobs/{body['job_id']}", headers=headers, timeout=10).json()
        if job['status'] in ('completed', 'failed'):
            print(f"   job {body['job_id']} -> {job['status']}")
            return job['status']
        time.sleep(1)
    print('   job still pending after 40s')
    return 'timeout'


def compose(*args):
    subprocess.run(['docker', 'compose', *args], check=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--base', default='http://localhost:5001')
    ap.add_argument('--admin', default='jainparth7040@gmail.com')
    ap.add_argument('--password', default='admin123')
    a = ap.parse_args()

    r = requests.post(f'{a.base}/api/v1/auth/login', json={'email': a.admin, 'password': a.password}, timeout=10)
    if r.status_code != 200:
        sys.exit(f'login failed: {r.status_code} {r.text}')
    headers = {'Authorization': f"Bearer {r.json()['token']}"}

    say('1/5  Healthy system: task goes through the Celery queue')
    health(a.base)
    ok1 = generate_and_wait(a.base, headers)

    say('2/5  CHAOS: stopping both Redis containers')
    compose('stop', 'redis-queue', 'redis-cache')
    time.sleep(3)

    say('3/5  /health degrades gracefully (no crash)')
    health(a.base)

    say('4/5  Trigger another task with Redis DOWN -> executes synchronously')
    try:
        # the JWT blacklist check is fail-open when Redis is down, so the existing token still works
        ok2 = generate_and_wait(a.base, headers)
    finally:
        say('5/5  Recovery: starting Redis again')
        compose('start', 'redis-queue', 'redis-cache')
    time.sleep(8)
    health(a.base)
    ok3 = generate_and_wait(a.base, headers)

    print(f'\nResult: before={ok1}  during-outage={ok2}  after-recovery={ok3}')
    sys.exit(0 if ok1 == ok2 == ok3 == 'completed' else 1)


if __name__ == '__main__':
    main()
