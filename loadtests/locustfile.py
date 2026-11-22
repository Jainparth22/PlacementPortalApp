"""Load test: how does the async queue absorb a spike of report generations?

    pip install -r requirements-dev.txt
    docker compose up -d --build                      # worker + redis + web
    locust -f loadtests/locustfile.py --host http://localhost:5001 --headless -u 50 -r 10 -t 60s --html loadtests/report.html

What to look at in the results / Flower (http://localhost:5555):
  * POST /reports/generate should stay fast (it only enqueues -> 202) even with 50 users,
    the heavy PDF work happens in the worker, not the web process.
  * per-user rate limit (HEAVY_ENDPOINT_RATE_LIMIT, default 10/min) returns 429 + Retry-After
    to anyone hammering the endpoint - those 429s are *expected* and are counted as successes here.
  * browse/dashboard reads are cache hits after the first request (see GET /health -> cache.hit_rate).

Credentials come from the seeded demo accounts (override with env vars).
"""
import os
import random

from locust import HttpUser, between, task

ADMIN = (os.environ.get('LOAD_ADMIN_EMAIL', 'jainparth7040@gmail.com'), os.environ.get('LOAD_ADMIN_PASSWORD', 'admin123'))
STUDENT = (os.environ.get('LOAD_STUDENT_EMAIL', 'rahul.verma@student.com'), os.environ.get('LOAD_STUDENT_PASSWORD', 'Rahul@123'))
API = '/api/v1'
SKIP_HEAVY = os.environ.get('LOAD_SKIP_HEAVY') == '1'   # skip report/export (needs a Celery worker to be meaningful)


class _Base(HttpUser):
    abstract = True
    wait_time = between(0.5, 2)
    creds = ADMIN

    def on_start(self):
        # Login is rate-limited per IP (20/min by default): raise LOGIN_RATE_LIMIT for big runs.
        with self.client.post(f'{API}/auth/login', json={'email': self.creds[0], 'password': self.creds[1]},
                              name='POST /auth/login', catch_response=True) as r:
            if r.status_code == 200:
                self.headers = {'Authorization': f"Bearer {r.json()['token']}"}
                r.success()
            else:
                self.headers = {}
                r.failure(f'login failed: {r.status_code}')


class AdminUser(_Base):
    weight = 1
    creds = ADMIN

    @task(5)
    def dashboard(self):
        self.client.get(f'{API}/admin/dashboard', headers=self.headers, name='GET /admin/dashboard (cached)')

    @task(3)
    def generate_report(self):
        if SKIP_HEAVY:
            return
        with self.client.post(f'{API}/admin/reports/generate', headers=self.headers, name='POST /admin/reports/generate', catch_response=True) as r:
            if r.status_code in (202, 429):      # 429 = per-user rate limit doing its job
                r.success()

    @task(1)
    def list_companies(self):
        self.client.get(f'{API}/admin/companies?page={random.randint(1, 3)}', headers=self.headers, name='GET /admin/companies')


class StudentUser(_Base):
    weight = 4
    creds = STUDENT

    @task(6)
    def browse(self):
        qs = random.choice(['', '?search=engineer', '?branch=CSE', '?page=2'])
        self.client.get(f'{API}/student/drives{qs}', headers=self.headers, name='GET /student/drives (cached)')

    @task(2)
    def my_applications(self):
        self.client.get(f'{API}/student/applications', headers=self.headers, name='GET /student/applications')

    @task(1)
    def export(self):
        if SKIP_HEAVY:
            return
        with self.client.post(f'{API}/student/export-applications', headers=self.headers, name='POST /student/export-applications', catch_response=True) as r:
            if r.status_code in (202, 429):
                r.success()
