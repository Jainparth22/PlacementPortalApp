#!/usr/bin/env python
"""Reproducible micro-benchmarks for the optimisations in this project (no server or Redis needed).

    python scripts/benchmark.py                 # prints a markdown table
    python scripts/benchmark.py --write         # also writes docs/PERFORMANCE_BENCHMARK.md
    python scripts/benchmark.py --students 5000 --drives 1000 --applications 40000

It builds a throw-away SQLite database with realistic volumes, then measures end-to-end latency through the
Flask stack (JWT auth, routing, ORM, JSON) with Flask's test client, and DB-level cost / statement counts with
SQLAlchemy events. What it compares:
  * admin dashboard: ~20 separate COUNT queries (old) vs 3 GROUP BYs (new), and cold vs cached request
  * company dashboard: 1 + N counts (old) vs one grouped query (new)
  * browse drives: cache miss (database) vs cache hit
  * per-request auth overhead (GET /auth/me)
NOTE: numbers depend on your machine; the *ratios* are what matter. The cache here is the in-process fallback
(no Redis); a Redis hit adds one network round trip (typically 0.2-1 ms on localhost / same-region).
"""
import argparse
import os
import platform
import statistics
import sys
import tempfile
import time

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..')
sys.path.insert(0, os.path.join(ROOT, 'backend'))

ap = argparse.ArgumentParser()
ap.add_argument('--students', type=int, default=2000)
ap.add_argument('--companies', type=int, default=200)
ap.add_argument('--drives', type=int, default=400)
ap.add_argument('--applications', type=int, default=12000)
ap.add_argument('--iterations', type=int, default=300)
ap.add_argument('--write', action='store_true')
args = ap.parse_args()

tmp = tempfile.mkdtemp(prefix='ppa-bench-')
os.environ.update({
    'DATABASE_URL': 'sqlite:///' + os.path.join(tmp, 'bench.db').replace(os.sep, '/'),
    'AUTO_SEED': '0', 'AUTO_MIGRATE': '0', 'LOG_LEVEL': 'ERROR', 'REDIS_URL': '', 'STATE_REDIS_URL': '',
    'UPLOAD_FOLDER': os.path.join(tmp, 'u'), 'REPORTS_FOLDER': os.path.join(tmp, 'r'), 'EXPORTS_FOLDER': os.path.join(tmp, 'e'),
    'LOGIN_RATE_LIMIT': '100000', 'LOGIN_EMAIL_RATE_LIMIT': '100000', 'ADMIN_PASSWORD': 'bench-admin-pw',
})

import random  # noqa: E402
from datetime import datetime, timedelta  # noqa: E402

from sqlalchemy import event  # noqa: E402
from werkzeug.security import generate_password_hash  # noqa: E402

import app as appmod  # noqa: E402
import cache  # noqa: E402
from models import (db, User, StudentProfile, CompanyProfile, PlacementDrive, Application)  # noqa: E402

app = appmod.app
app.config.update(TESTING=True, FORCE_SYNC_TASKS=True, REDIS_URL='', STATE_REDIS_URL='')


# ----------------------------------------------------------------------------- data
def build_data():
    random.seed(7)
    pw = generate_password_hash('Bench@123')
    now = datetime.now()
    with app.app_context():
        db.drop_all()
        db.create_all()
        db.session.add(User(id=1, email='admin@bench.test', password_hash=pw, role='admin'))
        users, students, companies = [], [], []
        uid = 2
        for i in range(args.students):
            users.append({'id': uid, 'email': f's{i}@bench.test', 'password_hash': 'x', 'role': 'student', 'is_active': True, 'is_blacklisted': False})
            students.append({'id': i + 1, 'user_id': uid, 'full_name': f'Student {i}', 'department': random.choice(['CSE', 'ECE', 'IT', 'ME']),
                             'cgpa': round(random.uniform(5, 10), 2), 'graduation_year': 2026})
            uid += 1
        for i in range(args.companies):
            users.append({'id': uid, 'email': f'c{i}@bench.test', 'password_hash': pw if i == 0 else 'x', 'role': 'company', 'is_active': True, 'is_blacklisted': False})
            companies.append({'id': i + 1, 'user_id': uid, 'company_name': f'Company {i}', 'approval_status': random.choice(['approved'] * 8 + ['pending', 'rejected'])})
            uid += 1
        db.session.bulk_insert_mappings(User, users)
        db.session.bulk_insert_mappings(StudentProfile, students)
        db.session.bulk_insert_mappings(CompanyProfile, companies)
        # student 1 gets a real password so we can log in as a student
        db.session.query(User).filter_by(id=2).update({'password_hash': pw})
        drives = [{'id': i + 1, 'company_id': random.randint(1, args.companies), 'drive_name': f'Drive {i}', 'job_title': random.choice(['SDE', 'Analyst', 'QA', 'DevOps']),
                   'eligibility_branch': random.choice(['All', 'CSE,IT', 'ECE']), 'min_cgpa': random.choice([0, 6, 7, 8]),
                   'status': random.choice(['approved'] * 7 + ['pending', 'closed', 'rejected']), 'application_deadline': now + timedelta(days=random.randint(1, 60)),
                   'location': random.choice(['Remote', 'Bengaluru', 'Chennai']), 'created_at': now} for i in range(args.drives)]
        db.session.bulk_insert_mappings(PlacementDrive, drives)
        pairs = set()
        while len(pairs) < args.applications:
            pairs.add((random.randint(1, args.students), random.randint(1, args.drives)))
        statuses = ['applied'] * 6 + ['shortlisted', 'selected', 'rejected', 'withdrawn']
        db.session.bulk_insert_mappings(Application, [{'student_id': s, 'drive_id': d, 'status': random.choice(statuses), 'application_date': now} for s, d in pairs])
        db.session.commit()


# ----------------------------------------------------------------------------- legacy implementations (for comparison)
def legacy_admin_stats():
    """What the dashboard did before: one COUNT per number."""
    return {
        'total_students': StudentProfile.query.count(), 'total_companies': CompanyProfile.query.count(), 'total_drives': PlacementDrive.query.count(),
        'pending_companies': CompanyProfile.query.filter_by(approval_status='pending').count(),
        'approved_companies': CompanyProfile.query.filter_by(approval_status='approved').count(),
        'pending_drives': PlacementDrive.query.filter_by(status='pending').count(),
        'approved_drives': PlacementDrive.query.filter_by(status='approved').count(),
        'total_applications': Application.query.count(), 'selected_students': Application.query.filter_by(status='selected').count(),
        'active_students': User.query.filter_by(role='student', is_active=True).count(), 'blacklisted_users': User.query.filter_by(is_blacklisted=True).count(),
        **{f'app_{k}': Application.query.filter_by(status=k).count() for k in ('applied', 'shortlisted', 'selected', 'rejected', 'withdrawn')},
        **{f'drive_{k}': PlacementDrive.query.filter_by(status=k).count() for k in ('pending', 'approved', 'rejected', 'closed')},
    }


def legacy_company_dashboard(company_id):
    drives = PlacementDrive.query.filter_by(company_id=company_id).all()
    return {'total': sum(d.applications.count() for d in drives), 'summary': [{'id': d.id, 'n': d.applications.count()} for d in drives]}


# ----------------------------------------------------------------------------- measuring
def timeit(fn, n):
    fn()                                              # warm-up
    samples = []
    for _ in range(n):
        t = time.perf_counter()
        fn()
        samples.append((time.perf_counter() - t) * 1000)
    samples.sort()
    return {'p50': statistics.median(samples), 'p95': samples[int(len(samples) * .95) - 1], 'p99': samples[int(len(samples) * .99) - 1],
            'mean': statistics.fmean(samples), 'n': n}


class StatementCounter:
    def __init__(self):
        self.n = 0

    def __enter__(self):
        event.listen(db.engine, 'before_cursor_execute', self._cb)
        return self

    def __exit__(self, *a):
        event.remove(db.engine, 'before_cursor_execute', self._cb)

    def _cb(self, *a):
        self.n += 1


def main():
    print(f'building data: {args.students} students, {args.companies} companies, {args.drives} drives, {args.applications} applications ...', flush=True)
    t0 = time.time()
    build_data()
    print(f'  done in {time.time() - t0:.1f}s', flush=True)

    c = app.test_client()
    with app.app_context():
        db.session.query(User).filter_by(id=1).update({'password_hash': generate_password_hash('Bench@123')})
        db.session.commit()
    admin_tok = c.post('/api/v1/auth/login', json={'email': 'admin@bench.test', 'password': 'Bench@123'}).get_json()['token']
    stud_tok = c.post('/api/v1/auth/login', json={'email': 's0@bench.test', 'password': 'Bench@123'}).get_json()['token']
    comp_tok = c.post('/api/v1/auth/login', json={'email': 'c0@bench.test', 'password': 'Bench@123'}).get_json()['token']
    H = lambda t: {'Authorization': f'Bearer {t}'}  # noqa: E731
    n = args.iterations
    rows = []

    # --- admin dashboard -------------------------------------------------------------------------------------------
    with app.app_context():
        with StatementCounter() as q_old:
            legacy_admin_stats()
        with StatementCounter() as q_new:
            appmod_admin = __import__('routes.admin', fromlist=['_build_admin_stats'])._build_admin_stats
            appmod_admin()
        old = timeit(legacy_admin_stats, n)
        new = timeit(appmod_admin, n)
    rows.append(('Admin dashboard - DB work, old (separate COUNTs)', old, q_old.n))
    rows.append(('Admin dashboard - DB work, new (GROUP BY)', new, q_new.n))

    def dash_cold():
        with app.app_context():
            cache.invalidate('stats')
        c.get('/api/v1/admin/dashboard', headers=H(admin_tok))

    rows.append(('GET /admin/dashboard - cache MISS (full request)', timeit(dash_cold, n), None))
    rows.append(('GET /admin/dashboard - cache HIT (full request)', timeit(lambda: c.get('/api/v1/admin/dashboard', headers=H(admin_tok)), n * 3), 0))

    # --- company dashboard -----------------------------------------------------------------------------------------
    with app.app_context():
        cid = max((d.company_id for d in PlacementDrive.query.limit(400)), key=lambda x: PlacementDrive.query.filter_by(company_id=x).count())
        with StatementCounter() as q_old:
            legacy_company_dashboard(cid)
        old = timeit(lambda: legacy_company_dashboard(cid), n)
        n_drives = PlacementDrive.query.filter_by(company_id=cid).count()
    rows.append((f'Company dashboard - old (1 + 2N counts, N={n_drives} drives)', old, q_old.n))

    def comp_cold():
        with app.app_context():
            cache.invalidate('cdash1')
        c.get('/api/v1/company/dashboard', headers=H(comp_tok))

    rows.append(('GET /company/dashboard - new, cache MISS (grouped query)', timeit(comp_cold, n), None))
    rows.append(('GET /company/dashboard - new, cache HIT', timeit(lambda: c.get('/api/v1/company/dashboard', headers=H(comp_tok)), n * 3), 0))

    # --- browse drives ---------------------------------------------------------------------------------------------
    def browse_cold():
        with app.app_context():
            cache.invalidate('drives')
        c.get('/api/v1/student/drives?search=drive&page=2', headers=H(stud_tok))

    rows.append(('GET /student/drives?search=... - cache MISS (LIKE + paginate)', timeit(browse_cold, n), None))
    rows.append(('GET /student/drives?search=... - cache HIT', timeit(lambda: c.get('/api/v1/student/drives?search=drive&page=2', headers=H(stud_tok)), n * 3), 0))

    # --- auth overhead ---------------------------------------------------------------------------------------------
    rows.append(('GET /auth/me (JWT verify + blacklist check + user load)', timeit(lambda: c.get('/api/v1/auth/me', headers=H(stud_tok)), n * 3), None))
    rows.append(('GET /health (framework floor)', timeit(lambda: c.get('/health'), n * 3), None))

    # --- report -----------------------------------------------------------------------------------------------------
    def fmt(v):
        return f'{v:.2f}'

    lines = [
        '| Scenario | p50 ms | p95 ms | p99 ms | mean ms | SQL statements |', '|---|---:|---:|---:|---:|---:|',
    ]
    for name, r, q in rows:
        lines.append(f"| {name} | {fmt(r['p50'])} | {fmt(r['p95'])} | {fmt(r['p99'])} | {fmt(r['mean'])} | {'' if q is None else q} |")
    table = '\n'.join(lines)

    def ratio(a, b):
        return f'{a["p50"] / b["p50"]:.1f}x'

    lookup = {name: r for name, r, _ in rows}
    miss = lookup['GET /admin/dashboard - cache MISS (full request)']
    hit = lookup['GET /admin/dashboard - cache HIT (full request)']
    bmiss = lookup['GET /student/drives?search=... - cache MISS (LIKE + paginate)']
    bhit = lookup['GET /student/drives?search=... - cache HIT']
    summary = [
        f"- Admin dashboard DB work: {rows[0][2]} statements -> {rows[1][2]}; p50 {fmt(rows[0][1]['p50'])} ms -> {fmt(rows[1][1]['p50'])} ms ({ratio(rows[0][1], rows[1][1])} faster).",
        f"- Admin dashboard request: cache hit is {ratio(miss, hit)} faster than a miss at p50.",
        f"- Browse drives request: cache hit is {ratio(bmiss, bhit)} faster than a miss at p50.",
    ]
    meta = (f"Machine: {platform.platform()} | Python {platform.python_version()} | SQLite | in-process cache (no Redis) | Flask test client, 1 thread\n"
            f"Data: {args.students} students, {args.companies} companies, {args.drives} drives, {args.applications} applications | iterations: {n} (x3 for fast cases)")
    out = f"# Benchmark results\n\n{meta}\n\n{table}\n\n**Summary**\n" + '\n'.join(summary) + '\n'
    print('\n' + out)
    if args.write:
        path = os.path.join(ROOT, 'docs', 'PERFORMANCE_BENCHMARK.md')
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, 'w', encoding='utf-8') as f:
            f.write(out)
        print(f'wrote {os.path.abspath(path)}')


if __name__ == '__main__':
    main()
