# Measured performance

Everything here was **measured on one developer laptop** (Windows 11, Python 3.14, SQLite, no Redis, Flask's
threaded dev server). Absolute numbers will differ on your machine and on PostgreSQL + Redis; the *ratios* and
the *shape* of the results are what matter. Run-to-run noise on this machine was roughly ±2×, so I report the
statement counts (deterministic) next to the timings. Reproduce everything with the commands below.

## 1. Micro-benchmarks — what each optimisation buys (`python scripts/benchmark.py`)

Dataset: 2,000 students · 200 companies · 400 drives · 12,000 applications. Full table with p50/p95/p99:
[PERFORMANCE_BENCHMARK.md](PERFORMANCE_BENCHMARK.md).

| Change | Before | After | Notes |
|---|---|---|---|
| Admin dashboard queries | **20** SQL statements | **6** | `GROUP BY` instead of one `COUNT` per number; ~2.8× less DB time |
| Company dashboard queries | **1 + 2N** statements (17 for N=8 drives) | **1** | grows with N before, constant after |
| `GET /admin/dashboard` | miss ≈ 3.5 ms | hit ≈ 0.8 ms | ~4× (p50) |
| `GET /student/drives?search=…` | miss ≈ 7.5 ms | hit ≈ 0.85 ms | ~9× (p50); the gap grows with table size because a miss is a `LIKE` scan |
| Auth overhead per request | — | ≈ 1.5 ms | JWT verify + blacklist check + user lookup (`/auth/me`); framework floor (`/health`) ≈ 0.5 ms |

Caveat: the cache here is the in-process fallback. With Redis a hit costs one extra network round trip
(≈0.2–1 ms on the same host/region) — still far cheaper than a miss on a real dataset, and shared by every worker.

## 2. HTTP load test — 25 concurrent users, 40 s (`locust`)

Setup: Locust → Flask dev server (threaded, **single process**), SQLite, demo seed data (small), in-process cache,
`LOAD_SKIP_HEAVY=1` (report/export need a Celery worker to be meaningful, which this run did not have).

| Endpoint | Requests | Failures | p50 | p95 | p99 |
|---|---:|---:|---:|---:|---:|
| `GET /student/drives` (cached) | 420 | 0 | 5 ms | 20 ms | 25 ms |
| `GET /admin/dashboard` (cached) | 93 | 0 | 5 ms | 22 ms | 210 ms |
| `GET /student/applications` | 132 | 0 | 8 ms | 34 ms | 250 ms |
| `GET /admin/companies` | 15 | 0 | 7 ms | 16 ms | 16 ms |
| `POST /auth/login` | 25 | 0 | **630 ms** | 1,100 ms | 1,200 ms |
| **All** | **685** | **0** | **6 ms** | 100 ms | 830 ms |

How to read it honestly
- **0 failures, aggregate p50 = 6 ms** with 25 users sharing a single-process Python server.
- The ~17 req/s is bounded by Locust's think time (0.5–2 s between actions per user), **not** by server capacity.
  This test shows the system is healthy at that concurrency; it does **not** find the breaking point.
- **Login is slow on purpose**: Werkzeug hashes passwords with scrypt (memory-hard) and 25 users logged in within
  one second on a single CPU. That cost is why brute-forcing a stolen hash is expensive, and why login has its own
  per-IP and per-account rate limits. The tail (p99 of other endpoints) in the first seconds is that CPU contention.
- Not measured here (needs the Docker stack): queue absorption of report generation with a real worker, Redis
  hit latency, PostgreSQL behaviour, multi-process gunicorn. `docker compose up --build`, then:

```bash
locust -f loadtests/locustfile.py --host http://localhost:5001 --headless -u 100 -r 20 -t 120s --html loadtests/report.html
```
Watch Grafana (`--profile observability`): request rate, p95, cache hit ratio, queue depth, workers online.

## 3. What I would measure next
1. Same test against the compose stack (PostgreSQL + Redis + gunicorn gthread + worker) at 100–500 users to find the knee.
2. A *spike* test (0 → 500 users in 10 s) at an application deadline, with and without the cache warm.
3. `POST /reports/generate` with a worker: web p95 should stay flat while queue depth rises and drains.
4. SSE capacity: how many open streams per web container before latency degrades (`SSE_MAX_CONNECTIONS`).
