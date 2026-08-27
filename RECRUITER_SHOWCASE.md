# 🎯 A Quick Guide for Recruiters

Hi! I'm Parth Jain, a student in the IIT Madras BS program. I built the Placement Portal Application (PPA) because I wanted to solve a real problem on campus, rather than just building another tutorial project.

This isn't your standard CRUD app. I built it to demonstrate my ability to design, develop, deploy, and bullet-proof a full-stack, multi-role platform from scratch. 

If you have a few minutes to explore the live link or the codebase, here is a quick guide on what to look for, the technical decisions I made, and how I approached problem-solving.

---

## 1. Taking Ownership: From Concept to Production

When building this, my goal was to show that I can take a product through its entire lifecycle. 
- **End-to-End Delivery:** I handled everything from designing the database schema to writing the API, building the frontend, setting up caching and async queues, and deploying it securely.
- **Engineering Mindset:** Every tool in the stack was chosen for a specific reason. More importantly, I intentionally built robust fallbacks for critical components so the app doesn't just crash if a service goes down.
- **User Experience Matters:** I made sure the live app is instantly testable. It's pre-seeded with demo accounts and features a 1-click login so you can jump right in without reading any docs.

---

## 2. Core Engineering Skills Demonstrated

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

---

## 3. Architecture Decisions & Fallbacks

I didn't just pick tools because they are popular; I picked them to solve specific problems. Here is my thought process:

| Decision | Why I Chose It | The Fallback I Built |
|----------|----------------|----------------------|
| **Flask over Django** | I wanted explicit control over 53 endpoints using Blueprints, keeping the architecture lean and modular. | — |
| **Vue 3 CDN over React** | I wanted a reactive SPA without the overhead of a build step (`npm run build`). | — |
| **Postgres (Prod) + SQLite (Local)** | Railway automatically provisions Postgres for production, while SQLite makes local development zero-setup. | If the `DATABASE_URL` is missing, it safely falls back to local SQLite. |
| **Redis vs In-Memory** | A true distributed cache is needed for rate-limiting and token blacklisting across multiple workers. | If Redis fails to connect, the app gracefully degrades to an in-memory dictionary so it doesn't crash. |
| **Celery vs Threading** | Celery provides a true queue for heavy report generation and scheduled reminders. | If Celery/Redis is down, the code catches it and runs the task synchronously so the user still gets their report. |
| **Railway Volumes** | Heroku-style ephemeral filesystems wipe user uploads on redeploy. I mounted a persistent `/data` volume. | If the volume isn't found, it falls back to a relative `backend/uploads` directory. |

---

## 4. Problem Solving in the Trenches

Here are a few real roadblocks I hit during development and how I solved them:

- **The Security Hole:** I realized that standard stateless JWTs remain valid even after a user logs out. 
  *Fix:* I implemented a stateful logout by generating a unique `jti` (JWT ID) for each token. On logout, the `jti` is stored in Redis with a TTL matching its expiration. The token decoder now checks this blacklist first, guaranteeing a secure `401 Unauthorized` on reuse.
  
- **The "Pending Forever" Bug:** When running the app locally without a Celery worker spun up, background tasks would stay pending forever. 
  *Fix:* I added a check before dispatching tasks. If the broker is unreachable, the application falls back to running the heavy function synchronously directly in the request lifecycle. 

- **The Sleeping AI Model:** The HuggingFace API I used for the ATS resume parsing sleeps after inactivity, causing 20-second timeouts. 
  *Fix:* I aggressively cached successful ATS results for 10 minutes. If the API times out, I catch the error and return a graceful fallback score based on the user's plain-text profile instead of throwing a `500 Server Error`.

---

## 5. A Guide to Testing the Live App

If you'd like to test the app, here are a few things to try out, ranging from obvious UI features to subtle backend safety checks.

### The Quick Tour (30 Seconds)
1. **Zero-Typing Login:** On the login screen, click the "Admin", "TechNova", or "Kavya" pills. It will auto-fill the credentials. Click Login. 
2. **The Look and Feel:** Notice the custom emerald theme, the dark mode toggle in the header, and the smooth floating toast alerts.
3. **Demo Modal:** Click "View all 8 accounts" to see a quick modal of all seeded users with 1-click copy buttons.

### Digging Deeper (2 Minutes)
4. **Admin Approval Flow:** Go to Companies -> Approve/Reject. Notice how the cache invalidates instantly and the lists update across the app.
5. **Data Protections:** Log in as a Company and try to edit a Placement Drive that has already been marked 'Closed'. The API will block it.
6. **Smart Validation:** Log in as a Student and apply for a drive. If your CGPA doesn't meet the drive's cutoff, the API actively rejects the application. 

### The Subtle Engineering Details 
7. **Rate Limiting:** Try rapidly clicking the Login button 6 times with a wrong password. You'll hit my custom `429 Too Many Requests` rate limiter.
8. **File Guardrails:** Go to Profile -> Resume and try uploading a `.docx` file. The backend explicitly rejects it (`400 Bad Request`), strictly enforcing a 5MB PDF-only policy.
9. **Asynchronous Polling:** As an Admin, go to Reports -> Generate. Watch the UI automatically poll the `/jobs/<id>` endpoint every 3 seconds until the backend finishes generating the PDF and serves the download. 
10. **Stateful Logout:** Log out, then try to manually hit an API endpoint with your old Bearer token in Postman. The server will reject it immediately because the token ID was added to the Redis blacklist.
11. **API Documentation:** Hit `/api/docs` in your browser. You'll see a complete, auto-generated ReDoc page powered by my `api.yaml` specification.

---

## 6. The 30-Second Elevator Pitch

"I built a 53-endpoint campus placement system that’s actually demo-ready: it has 8 seeded accounts, 1-click login, strict PDF-only resume guards, eligibility checks, global pagination, IP rate limiting, and JTI-blacklisted logouts. It runs on a Redis cache with three distinct fallback layers, a Celery task queue that gracefully degrades to synchronous execution, and a Volume-aware storage system. You can test the AI resume parser, or try to break the app—going to `page=999` returns an empty list rather than crashing, duplicate applications throw a 409, and the health check stays green even if the cache goes down."
