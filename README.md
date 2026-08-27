# Placement Portal Application (PPA V5)

> **Production-grade campus placement system** — `Flask REST + Vue 3 SPA + Redis + Celery + Postgres/SQLite + HuggingFace ATS + Railway Volume`
>
> **Live:** `https://your-ppa.up.railway.app` · **API Docs:** `/api/docs` (ReDoc) · `/api/swagger` (Swagger UI) · **Spec:** `api.yaml` (53 endpoints) · **Health:** `/health` · **Auth:** `JWT + JTI blacklist` (stateful logout)

---

## Table of Contents
- [🎯 For Recruiters — Showcase](#-for-recruiters--showcase)
  - [1. About Me](#1-about-me)
  - [2. CS Skills Demonstrated](#2-cs-skills-demonstrated)
  - [3. Architecture Decisions](#3-architecture-decisions)
  - [4. Real-World Contributions](#4-real-world-contributions)
  - [5. Problem Solving Stories](#5-problem-solving-stories)
  - [6. Testing Guide (What to Notice)](#6-testing-guide-what-to-notice)
- [Problem & Vision](#problem--vision)
- [System Design Principles](#system-design-principles)
- [Architecture — With Fallbacks](#architecture--with-fallbacks)
- [DB Schema — 12 Tables](#db-schema--12-tables)
- [Interlinking — Role Lifecycles](#interlinking--role-lifecycles)
- [Role Deep-Dive](#role-deep-dive)
- [API — 53 Endpoints + Pagination + Docs](#api--53-endpoints--pagination--docs)
- [ATS System](#ats-system)
- [Frontend — 14 Pages + PWA](#frontend--14-pages--pwa)
- [Pagination](#pagination)
- [Security — Rate Limiter, Validation, Fallbacks](#security--rate-limiter-validation-fallbacks)
- [Offline vs Online Run](#offline-vs-online-run)
- [Project Structure](#project-structure)
- [Tech Stack & Rationale](#tech-stack--rationale)
- [Build Commands — Verified](#build-commands--verified)
- [Demo Credentials (8 Seeded)](#demo-credentials-8-seeded)
- [Run Locally — Windows](#run-locally--windows)
- [Deploy to Railway — 3-Service True Async](#deploy-to-railway--3-service-true-async)
- [Verification](#verification)
- [Limitations & Roadmap](#limitations--roadmap)

---

## 🎯 For Recruiters — Showcase

Hi! I'm Parth Jain, a student in the IIT Madras BS program. I built the Placement Portal Application (PPA) because I wanted to solve a real problem on campus, rather than just building another tutorial project.

This isn't your standard CRUD app. I built it to demonstrate my ability to design, develop, deploy, and bullet-proof a full-stack, multi-role platform from scratch. 

If you have a few minutes to explore the live link or the codebase, here is a quick guide on what to look for, the technical decisions I made, and how I approached problem-solving.

### 1. Taking Ownership: From Concept to Production
When building this, my goal was to show that I can take a product through its entire lifecycle. 
- **End-to-End Delivery:** I handled everything from designing the database schema to writing the API, building the frontend, setting up caching and async queues, and deploying it securely.
- **Engineering Mindset:** Every tool in the stack was chosen for a specific reason. More importantly, I intentionally built robust fallbacks for critical components so the app doesn't just crash if a service goes down.
- **User Experience Matters:** I made sure the live app is instantly testable. It's pre-seeded with demo accounts and features a 1-click login so you can jump right in without reading any docs.

### 2. Core Engineering Skills Demonstrated
Here’s where you can see my computer science fundamentals applied in practice:

| Skill | Where to See It | Why It Matters |
|-------|-----------------|----------------|
| **System Design** | 12 tables in `models.py`, `UniqueConstraint(student, drive)`, state machines for drives | Shows I know how to model complex, real-world relationships, going way beyond a simple `users` table. |
| **REST API Architecture** | 53 endpoints in `api.yaml`, consistent pattern (`decorator → validate → query → jsonify`), pagination | Proves I write consistent, predictable, and scalable APIs, rather than ad-hoc scripts. |
| **Auth & Access Control** | `@role_required` decorators, JWT expiration, **stateful JTI blacklisting** in `auth.py` | Shows a deep understanding of session management and token revocation, not just basic stateless JWTs. |
| **Security Best Practices** | Input validation, secure file uploads, 5MB file limits, **rate limiting (5/min)** via Redis | Demonstrates maturity in defense-in-depth and protecting infrastructure from abuse. |
| **Performance Optimization** | Redis Cache-Aside (`cache.py`), global pagination | Shows I build for scale so the database and DOM don't choke under load. |
| **Asynchronous Processing** | Celery + Beat in `tasks.py` for emails and heavy PDF reports, with a **sync fallback** | Proves I know when to offload heavy tasks to a background worker, and how to gracefully degrade if the worker is down. |
| **Resilient Data Handling** | Railway Volumes (`/data`), relative paths, ATS gracefully handling missing PDFs | Highlights my understanding of ephemeral filesystems in modern cloud deployments. |

### 3. Architecture Decisions & Fallbacks
I didn't just pick tools because they are popular; I picked them to solve specific problems. Here is my thought process:

| Decision | Why I Chose It | The Fallback I Built |
|----------|----------------|----------------------|
| **Flask over Django** | I wanted explicit control over 53 endpoints using Blueprints, keeping the architecture lean and modular. | — |
| **Vue 3 CDN over React** | I wanted a reactive SPA without the overhead of a build step (`npm run build`). | — |
| **Postgres (Prod) + SQLite (Local)** | Railway automatically provisions Postgres for production, while SQLite makes local development zero-setup. | If the `DATABASE_URL` is missing, it safely falls back to local SQLite. |
| **Redis vs In-Memory** | A true distributed cache is needed for rate-limiting and token blacklisting across multiple workers. | If Redis fails to connect, the app gracefully degrades to an in-memory dictionary so it doesn't crash. |
| **Celery vs Threading** | Celery provides a true queue for heavy report generation and scheduled reminders. | If Celery/Redis is down, the code catches it and runs the task synchronously so the user still gets their report. |
| **Railway Volumes** | Heroku-style ephemeral filesystems wipe user uploads on redeploy. I mounted a persistent `/data` volume. | If the volume isn't found, it falls back to a relative `backend/uploads` directory. |

### 4. Problem Solving in the Trenches
Here are a few real roadblocks I hit during development and how I solved them:

- **The Security Hole:** I realized that standard stateless JWTs remain valid even after a user logs out. 
  *Fix:* I implemented a stateful logout by generating a unique `jti` (JWT ID) for each token. On logout, the `jti` is stored in Redis with a TTL matching its expiration. The token decoder now checks this blacklist first, guaranteeing a secure `401 Unauthorized` on reuse.
  
- **The "Pending Forever" Bug:** When running the app locally without a Celery worker spun up, background tasks would stay pending forever. 
  *Fix:* I added a check before dispatching tasks. If the broker is unreachable, the application falls back to running the heavy function synchronously directly in the request lifecycle. 

- **The Sleeping AI Model:** The HuggingFace API I used for the ATS resume parsing sleeps after inactivity, causing 20-second timeouts. 
  *Fix:* I aggressively cached successful ATS results for 10 minutes. If the API times out, I catch the error and return a graceful fallback score based on the user's plain-text profile instead of throwing a `500 Server Error`.

### 5. A Guide to Testing the Live App
If you'd like to test the app, here are a few things to try out, ranging from obvious UI features to subtle backend safety checks.

**The Quick Tour (30 Seconds)**
1. **Zero-Typing Login:** On the login screen, click the "Admin", "TechNova", or "Kavya" pills. It will auto-fill the credentials. Click Login. 
2. **The Look and Feel:** Notice the custom emerald theme, the dark mode toggle in the header, and the smooth floating toast alerts.
3. **Demo Modal:** Click "View all 8 accounts" to see a quick modal of all seeded users with 1-click copy buttons.

**Digging Deeper (2 Minutes)**
4. **Admin Approval Flow:** Go to Companies -> Approve/Reject. Notice how the cache invalidates instantly and the lists update across the app.
5. **Data Protections:** Log in as a Company and try to edit a Placement Drive that has already been marked 'Closed'. The API will block it.
6. **Smart Validation:** Log in as a Student and apply for a drive. If your CGPA doesn't meet the drive's cutoff, the API actively rejects the application. 

**The Subtle Engineering Details**
7. **Rate Limiting:** Try rapidly clicking the Login button 6 times with a wrong password. You'll hit my custom `429 Too Many Requests` rate limiter.
8. **File Guardrails:** Go to Profile -> Resume and try uploading a `.docx` file. The backend explicitly rejects it (`400 Bad Request`), strictly enforcing a 5MB PDF-only policy.
9. **Asynchronous Polling:** As an Admin, go to Reports -> Generate. Watch the UI automatically poll the `/jobs/<id>` endpoint every 3 seconds until the backend finishes generating the PDF and serves the download. 
10. **Stateful Logout:** Log out, then try to manually hit an API endpoint with your old Bearer token in Postman. The server will reject it immediately because the token ID was added to the Redis blacklist.
11. **API Documentation:** Hit `/api/docs` in your browser. You'll see a complete, auto-generated ReDoc page powered by my `api.yaml` specification.

### 6. The 30-Second Elevator Pitch
"I built a 53-endpoint campus placement system that’s actually demo-ready: it has 8 seeded accounts, 1-click login, strict PDF-only resume guards, eligibility checks, global pagination, IP rate limiting, and JTI-blacklisted logouts. It runs on a Redis cache with three distinct fallback layers, a Celery task queue that gracefully degrades to synchronous execution, and a Volume-aware storage system. You can test the AI resume parser, or try to break the app—going to `page=999` returns an empty list rather than crashing, duplicate applications throw a 409, and the health check stays green even if the cache goes down."

---

## Problem & Vision
**Problem:** Spreadsheets, email approvals, no eligibility (CGPA/branch/year), duplicate applies, no ATS, no unified Admin/Company/Student view.
**Vision:** One auditable `Company(pending→approved) → Drive(pending→approved) → Student(browse→apply→eligible+unique→Company shortlist→Interview→History) → Admin reports` via **stateless JWT**, **cached**, **paginated (6/page)**, **rate-limited**, **async where slow**, with **fallbacks** for offline demo.

---

## System Design Principles

> **Every route follows the pattern:** `decorator → get data → validate → query → return jsonify` *(from `Startup.txt:42` — consistent across all 53 endpoints in `admin.py`/`company.py`/`student.py`/`app.py`)*

| Principle | Application |
|-----------|-------------|
| **Uniform Route Pattern** | **`decorator → get data → validate → query → return jsonify`** — every handler: `@role_required`/`@login_required` → `request.json/args` → `validators.py` → `query` → `jsonify` (e.g., `student.py:228` `apply_for_drive`, `admin.py:79` `list_companies`, `company.py:162` `list_company_drives`) |
| **Separation of Concerns** | `backend/` JSON only (`app.py:17` factory, blueprints `admin.py:9` `company.py:9` `student.py:11`), `frontend/` Vue SPA only |
| **REST + Stateful JWT (JTI blacklist)** | `decorator→validate→query→jsonify`, `@role_required` `auth.py:47`, `exp 3600` `config.py:40`, `jti:uuid4` `auth.py:32` → `POST /api/auth/logout` `app.py:188` blacklists `bl:<jti> TTL=exp-now` (Redis `setex` or in-memory fallback `_blacklisted_memory`), `decode_token` `auth.py:52` rejects blacklisted even if not expired |
| **Single-Table Inheritance** | `User.role` + `StudentProfile`/`CompanyProfile` (`models.py:7`) |
| **Normalized + FK Cascades** | 12 tables, `Unique(student,drive)` `models.py:158`, `cascade delete-orphan` |
| **Cache-Aside** | `cache.py:31` Redis singleton, `admin_stats 300s`, `approved_drives_paginated 600s`, fallback `None` |
| **Async-Where-Slow** | Celery `export/report/reminders` `tasks.py:35` + Beat, fallback sync if Redis down `admin.py:313` `student.py:367` |
| **Pagination Everywhere** | `pagination.py:4` `{items,total,pages}` on 12 lists `?page&per_page` (6, max 50), `app.js:166` `pg` meta |
| **Fail-Safe** | ATS `PyPDF2→profile fallback` `student.py:433`, storage relative paths + Volume `/data` |
| **Rate-Limited** | `app.py:103` `5/min per IP` `POST /api/auth/login` via Redis `INCR ratelimit:login:<ip> 60s` or in-memory `_login_attempts`, `429 Too many` |
| **12-Factor** | Env `DATABASE_URL/REDIS_URL/UPLOAD_FOLDER/PORT`, `railway.json`, `Dockerfile` `/data`, `AUTO_SEED` |

---

## Architecture — With Fallbacks
```mermaid
graph TD
  Browser[Vue 3 SPA<br/>app.js + index.html]
  Browser -- Bearer JWT<br/>app.js:138 --> API[Flask API<br/>app.py:create_app]
  API -- Blueprints --> Admin[admin.py 18]
  API -- Blueprints --> Company[company.py 10]
  API -- Blueprints --> Student[student.py 12]
  API -- ORM --> DB[(Postgres Railway<br/>↔ SQLite local<br/>config.py:_get_database_uri)]
  API -- Cache --> Redis[(Redis)]
  Redis -- fallback: None<br/>cache.py:31 --> API
  API -- Queue --> Celery[Celery+Beat<br/>celery_worker.py]
  Celery -- tasks --> Tasks[tasks.py<br/>report/CSV/reminders]
  Tasks -- fallback: sync<br/>admin.py:313 --> API
  API -- Storage --> Volume[/data/uploads<br/>Volume /data<br/>fallback: backend/uploads]
  API -- HF --> HF[HF Space parthjain/ResumeAnalyser]
  HF -- sleep fallback --> ATS[ATS fallback text<br/>student.py:470]
  API -- RateLimit --> RL[5/min IP<br/>app.py:103]
  API -- Health --> Health[/health<br/>db+redis]
  API -- Logout --> Blacklist[(JTI Blacklist<br/>Redis bl:<jti> TTL<br/>or memory<br/>auth.py:32)]
  Browser -- Docs --> DocsRoute[/api/docs ReDoc<br/>/api/swagger<br/>/api/openapi.yaml]
  style Redis fill:#fee,stroke:#f00,stroke-dasharray: 5 5
  style Celery fill:#efe,stroke:#0a0,stroke-dasharray: 5 5
```

**Fallbacks denoted dashed:**
- **Redis down** → `cache_get None`, reports/exports run **sync** `admin.py:313`, rate limiter uses in-memory dict, JTI blacklist uses memory `_blacklisted_memory`
- **HF sleeping** → `student.py:470` returns fallback text `ATS temporarily unavailable` + `200` not `500`, cached `600s`
- **Volume missing** → `UPLOAD_FOLDER` fallback to `backend/uploads`, ATS uses profile `Name/Skills/CGPA`
- **Celery worker missing (single-web)** → job runs sync, `202` still completes (was `pending forever` before fix)
- **Logout** → was stateless (token valid 1h), now **stateful** `app.py:188` `bl:<jti>` until `exp` — `decode_token` `auth.py:52` rejects blacklisted

---

## DB Schema — 12 Tables
```mermaid
erDiagram
  User ||--o| StudentProfile : "1-1"
  User ||--o| CompanyProfile : "1-1"
  User ||--o{ Notification : "1-N"
  User ||--o{ AsyncJob : "1-N"
  CompanyProfile ||--o{ PlacementDrive : "1-N"
  PlacementDrive ||--o{ Application : "1-N"
  PlacementDrive ||--o{ DriveApproval : "1-N"
  StudentProfile ||--o{ Application : "1-N"
  StudentProfile ||--o{ Skill : "1-N"
  StudentProfile ||--o{ PlacementHistory : "1-N"
  Application ||--o{ Interview : "1-N"
  User { int id PK; string email UK; string role; bool is_active; }
  StudentProfile { int user_id FK; string full_name; float cgpa; string resume_path; }
  CompanyProfile { int user_id FK; string company_name; string approval_status; }
  PlacementDrive { int company_id FK; string drive_name; string status; }
  Application { int student_id FK; int drive_id FK; string status; UK(student,drive); }
```

`backend/models.py:1` — `User` single-table, `StudentProfile.resume_path` relative, cascades.

---

## Interlinking — Role Lifecycles
```
Company Register → pending → Admin approve → Notify → Company POST drive → pending → Admin approve → cache_delete → Student browse (paginated, cached) → Apply (4 checks+unique) → Notify Company → Company GET apps paginated → PUT status → selected→History+Notify → schedule Interview → result → Notify → Student history/interviews/ATS/export → Admin reports generate→Celery→PDF→Notify+Email+GChat → download
```
**State Machines:** `Company pending→approved/rejected→blacklist`, `Drive pending→approved/rejected→closed` (edit blocked `company.py:247`), `Application applied→shortlisted→selected/rejected→withdrawn`, `Interview pending→passed/failed`.

---

## Role Deep-Dive
**Admin 18** `routes/admin.py:1`: Dashboard 8 stats+2 charts `admin.py:13` cached, Companies `?status&page` approve/reject/blacklist + search `ilike limit20`, Drives `?status` + detail `drive_id`, Students deactivate/blacklist, Applications `?status&drive_id`, Reports paginated `generate→poll /jobs → download`.

**Company 10** `routes/company.py:1`: Register validated `email/password/phone/url`, Dashboard `total_drives/applicants`, Drives CRUD paginated (edit blocked `closed/rejected` `company.py:247`, delete blocked if apps), Applications paginated → status → History, Interview `schedule`/`result`, Interviews list paginated.

**Student 12** `routes/student.py:1`: Register, Drives `?search&branch&page` cached, Detail `already_applied`, Apply 4 checks+unique `student.py:237`, My Apps paginated+withdraw, Interviews/History paginated, Upload PDF `secure_filename` `resume_<id>` → relative `student.py:166`, ATS, Export async→poll.

---

## API — 53 Endpoints + Pagination + Docs
**Paginated 12** → `{items,total,pages,page,per_page}` `pagination.py:4` (`?page=1&per_page=6` max 50) `app.js:181` unwrap.

| Group | Endpoints (★ paginated) |
|-------|------------------------|
| **Auth 3** | `POST /api/auth/login` *(rate-limited 5/min)*, `POST /api/auth/logout`, `GET /api/auth/me` |
| **Notify/Jobs 4** | `GET /api/notifications`★, `PUT /read`, `PUT /read-all`, `GET /api/jobs/<id>` |
| **Admin 18** | `GET /dashboard` cached, `GET /search`, `GET /companies`★, `pending`, `PUT approve/reject/blacklist`, `GET /drives`★, `pending`, `PUT approve/reject/close`, `GET /students`★, `PUT deactivate/blacklist`, `GET /applications`★, `GET /reports/monthly`★, `POST /reports/generate`→202, `GET /download/<id>` |
| **Company 10** | `POST /companies/register`, `GET/PUT /companies/profile`, `GET /company/dashboard`, `GET /company/drives`★ `POST`, `PUT/DELETE /drives/<id>`, `GET /drives/<id>/applications`★, `PUT /status`, `POST /schedule-interview`, `PUT /interview-result`, `GET /drives/<id>/interviews`★ |
| **Student 12** | `POST /students/register`, `GET/PUT /students/profile`, `POST /students/upload-resume` PDF, `GET /student/drives`★, `GET /drives/<id>`, `POST /apply/<id>`, `GET /applications`★, `PUT /withdraw`, `GET /history`★, `GET /interviews`★, `POST /export`→202, `GET /download-export/<id>`, `POST /ats-check` |

**Interesting `api.yaml` use — no extra deps:** `backend/app.py:217` adds `GET /api/openapi.yaml` (serves file), `GET /api/docs` (ReDoc CDN), `GET /api/swagger` (Swagger UI CDN). Open `https://your-ppa.up.railway.app/api/docs` to browse 53 endpoints (import `api.yaml` in Postman/Swagger too). `GET /health` for Railway healthcheck.

---

## ATS System
1. Build JD `job_title+description+branch+cgpa` `student.py:421`
2. Resolve resume `UPLOAD_FOLDER/basename` + fallback `student.py:433` `Name/Dept/CGPA/Skills/Bio` (works without PDF)
3. `gradio_client` `parthjain/ResumeAnalyser` `student.py:468` → cached `cache_get f"ats:{id}:{drive}:{hash}" 600s` `student.py:460`, fallback `200` on HF sleep `student.py:470`
4. Matrix `sample_test_data.md:342` `Kavya Intern 90% HIGH`, `Arjun Analyst 15% LOW`

---

## Frontend — 14 Pages + PWA
Vue 3 CDN `app.js:6` `currentPage` routing, Bootstrap 5, Chart.js. Pages: Login+ demo pills `fillDemo()` `app.js:336`, Admin Dashboard 8 cards+charts `renderAdminCharts`, Companies/Drives/Students/Applications/Reports (+detail), Company Dashboard/Drives/Profile/DriveApps, Student Dashboard/Drives/Detail/Apps/Interviews/History/Profile. Global pagination bar `index.html:1235`.

---

## Pagination
**Why:** Without, `GET /companies` fetched all → slow DOM. **Backend** `pagination.py:4` `paginate(error_out=False)` uniform. **Frontend** `pg` meta per list, `goPage` `app.js:191`, global bar `index.html:1235`. Clients `?page=2&per_page=6`. Extra seed 8 companies (was 2) `SampleDataSeed.py:371` makes bar visible.

---

## Security — Rate Limiter, Validation, Fallbacks
- **Rate Limiter (NEW):** `app.py:103` `POST /api/auth/login` `5/min per IP` → `429` via Redis `INCR ratelimit:login:<ip> 60s` or in-memory fallback (`_login_attempts`). Shows maturity, prevents brute force.
- **Validation:** `validators.py` `email/password 6+`, `phone`, `cgpa 0-10`, `year`, `url`, `name` + client `was-validated`.
- **Auth:** `Werkzeug hash`, `secure_filename`, `5MB`, `is_active/blacklisted` `auth.py:42`, `HS256 1h`, `CORS *`, JWT required `Bearer`.
- **Secrets:** `config.py:32` `_require_env()` fails hard in `RAILWAY_ENVIRONMENT`/`FLASK_ENV=production` if `SECRET_KEY/JWT/ADMIN_PASSWORD` missing (no weak fallback), `.env` gitignored `RILWAY`, must set Railway Variables.
- **Fallbacks:** As per architecture diagram.

---

## Offline vs Online Run
| Mode | How | Async | What happens |
|------|-----|-------|--------------|
| **Offline (Windows, single `web`)** | `Startup.txt` `python app.py` + optional `docker redis` | **Sync fallback** `admin.py:313` `student.py:367` detects `Redis==None` → runs `generate_monthly_report(job.id)` / `export_csv(...)` directly, `202` completes immediately, no polling forever. ATS falls back to profile text if PDF missing. Works without `worker`/`beat`. | For local dev, offline demo, recruiter quick test without 3 services |
| **Online (Railway, 3-service true async)** | `web` + `worker` (`celery worker --pool solo`) + `beat` + Redis+Postgres plugins, Volume `/data` | **True async** `delay()` enqueues to Redis → worker picks `5 interviews` etc., `GET /jobs/<id>` polls `3s` `app.js:650`, Beat `daily-reminders`/`monthly-report` cron | For production, concurrent, persistent, charts live |

Set `AUTO_SEED=1` auto-seeds if empty (8 companies now), `AUTO_SEED=0` to disable.

---

## Project Structure
```
PPA/
├── backend/
│   ├── app.py               # + /health + /api/docs + rate limiter + AUTO_SEED
│   ├── config.py            # _require_env() prod fail, _get_database_uri, Volume /data
│   ├── models.py            # 12 models
│   ├── pagination.py        # paginate_query()
│   ├── auth.py              # jwt + decorators
│   ├── cache.py             # Redis singleton
│   ├── validators.py
│   ├── celery_worker.py     # REDIS fallback
│   ├── tasks.py             # sync fallback email check
│   ├── SampleDataSeed.py    # 8 companies (was 2) for pagination
│   ├── routes/*.py          # + sync fallbacks
│   └── instance/ppa.db
├── frontend/
│   ├── templates/index.html # demo pills + global pagination
│   └── static/js/app.js     # pg, rate-limit handling
├── api.yaml                 # 53 + BearerAuth (served at /api/openapi.yaml)
├── seed.py                  # wrapper python seed.py (replaces 2 scripts, kept 1)
├── requirements.txt         # + psycopg2-binary
├── Procfile                 # workers 1 (free) — verified
├── Dockerfile               # 3.11-slim + /data — verified
├── railway.json             # nixpacks + workers 1 — verified
├── .env                     # gitignored, paste to Railway
├── .env.example
└── sample_test_data.md      # 5 resumes + ATS matrix (PDFs in Sample Resumes/*.pdf)
```

---

## Tech Stack & Rationale
`Flask` minimal REST, `SQLAlchemy2 paginate`, `Postgres↔SQLite`, `Redis`, `Celery`, `Vue3 CDN`, `Bootstrap5`, `xhtml2pdf`, `PyPDF2+gradio_client`, `gunicorn 1 worker`.

---

## Build Commands — Verified
| Builder | Build | Deploy | When |
|---------|-------|--------|------|
| **Nixpacks** (default) | `pip install -r requirements.txt` `railway.json:5` | `gunicorn --chdir backend --workers 1 --threads 2 --timeout 120 --bind 0.0.0.0:$PORT app:app` `railway.json:8` `Procfile:5` | Railway auto, fast |
| **Dockerfile** | `FROM python:3.11-slim + build-essential libpq-dev` `Dockerfile:10` → `pip install` | Same `CMD` `Dockerfile:29` | `Settings → Build → Dockerfile` |
| **Worker** | — | `celery --workdir backend -A celery_worker worker --pool solo --concurrency=1` `Procfile:7` | Separate service |
| **Beat** | — | `celery --workdir backend -A celery_worker beat` `Procfile:10` | Separate service |
Precedence: Service `Start Command` > `railway.json` > `Procfile` > `Dockerfile CMD`. All verified `python -m py_compile`.

---

## Demo Credentials (8 Seeded)
`backend/SampleDataSeed.py:39` auto on first boot. `seed.py` wrapper for manual `python seed.py`.

| Admin `jainparth7040@gmail.com`/`admin123` | TechNova `hr@technova.com`/`Tech@123` | GreenLeaf `careers@greenleaf.com`/`Green@123` | Rahul `rahul...`/`Rahul@123` CSE 8.5 | Kavya `kavya...`/`Kavya@123` 9.1 STAR | +3 more +6 extra pagination demo |

---

## Run Locally — Windows
```powershell
python -m venv .venv; .\.venv\Scripts\Activate; pip install -r requirements.txt
docker run -d --name redis-server -p 6379:6379 redis
cd backend; python app.py # :5001
# T3 worker, T4 beat, T5 cloudflared as Startup.txt, or single-web works via sync fallback
python seed.py # if not auto-seeded
```

---

## Deploy to Railway — 3-Service True Async
1. Push `main` → Railway `Deploy from GitHub` → Add `Postgres`+`Redis` plugins (auto `DATABASE_URL`/`REDIS_URL`)
2. Paste `.env` into `Variables` (Raw Editor) on `web/worker/beat` → set strong `SECRET_KEY/JWT/ADMIN_PASSWORD` (required in prod)
3. `Volumes → /data` + `UPLOAD_FOLDER=/data/uploads` `REPORTS_FOLDER=/data/reports` `EXPORTS_FOLDER=/data/exports` on all 3
4. Create 3 services override `Start Command` per above
5. Custom Domain `Settings → Networking → Generate/Custom` → add `CNAME` → TLS → `/health` verify

---

## Verification
`GET /health` `{status:ok,db:true,redis:true}` 200, `POST /login` 200 (6th in 60s → `429`), `POST /logout` → token blacklisted → `GET /auth/me` with old token → `401`, `GET /companies?page=1&per_page=6`→`{items,pages}`, `GET /api/docs` ReDoc + `GET /api/openapi.yaml`, ATS cached fallback, CSV poll sync fallback when Redis down.

**Break-check (automated):** `python -m py_compile backend/*.py` OK, login→blacklist→re-login flow verified (`in-memory` fallback when Redis down), pagination `{items,total,pages}` on 12 endpoints, `seed.py` wrapper, `workers 1` free tier, `.env` gitignored, `api.yaml` served at `/api/openapi.yaml`.

---

## Limitations & Roadmap
`logout → JTI blacklist` now stateful (TTL until `exp`), but distributed in-memory fallback not shared across multiple `gunicorn` workers — use Redis (`bl:<jti>`) for true multi-worker revocation. Search still client limit 20, move storage to S3, `WebSockets` for notifications.
