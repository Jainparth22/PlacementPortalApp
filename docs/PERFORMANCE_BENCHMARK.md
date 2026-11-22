# Benchmark results

Machine: Windows-11-10.0.26300-SP0 | Python 3.14.7 | SQLite | in-process cache (no Redis) | Flask test client, 1 thread
Data: 2000 students, 200 companies, 400 drives, 12000 applications | iterations: 300 (x3 for fast cases)

| Scenario | p50 ms | p95 ms | p99 ms | mean ms | SQL statements |
|---|---:|---:|---:|---:|---:|
| Admin dashboard - DB work, old (separate COUNTs) | 6.59 | 8.84 | 12.75 | 7.04 | 20 |
| Admin dashboard - DB work, new (GROUP BY) | 2.33 | 4.12 | 4.71 | 2.67 | 6 |
| GET /admin/dashboard - cache MISS (full request) | 3.53 | 6.17 | 8.94 | 3.98 |  |
| GET /admin/dashboard - cache HIT (full request) | 0.80 | 1.62 | 2.10 | 0.93 | 0 |
| Company dashboard - old (1 + 2N counts, N=8 drives) | 6.16 | 8.34 | 10.75 | 6.58 | 17 |
| GET /company/dashboard - new, cache MISS (grouped query) | 1.76 | 3.80 | 4.38 | 2.08 |  |
| GET /company/dashboard - new, cache HIT | 1.64 | 3.14 | 3.61 | 1.87 | 0 |
| GET /student/drives?search=... - cache MISS (LIKE + paginate) | 7.53 | 12.27 | 13.60 | 8.14 |  |
| GET /student/drives?search=... - cache HIT | 0.85 | 1.62 | 2.24 | 0.99 | 0 |
| GET /auth/me (JWT verify + blacklist check + user load) | 1.50 | 2.93 | 3.50 | 1.76 |  |
| GET /health (framework floor) | 0.48 | 0.86 | 1.24 | 0.53 |  |

**Summary**
- Admin dashboard DB work: 20 statements -> 6; p50 6.59 ms -> 2.33 ms (2.8x faster).
- Admin dashboard request: cache hit is 4.4x faster than a miss at p50.
- Browse drives request: cache hit is 8.9x faster than a miss at p50.
