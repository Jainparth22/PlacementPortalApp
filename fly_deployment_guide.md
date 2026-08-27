# Fly.io Deployment & Architecture Guide

This document is your ultimate cheat sheet for deploying the Placement Portal Application (PPA) to Fly.io from scratch. It is based on the exact troubleshooting and architecture decisions we made to get the app running flawlessly on Fly.io's free tier.

---

## Part 1: The "From Scratch" Deployment Script

If you ever need to tear down the project and deploy it again, follow these steps exactly.

### 1. Initial Setup
```powershell
# 1. Login to Fly.io
fly auth login
```

### 2. Launch the App (But Don't Deploy Yet)
```powershell
# We use --no-deploy because we need to set up databases and secrets first!
fly launch --no-deploy
```
*When prompted:*
* *Would you like to copy its configuration to the new app?* **Yes**
* *Do you want to tweak these settings before proceeding?* **No**

### 3. Provision Databases
Fly's `bom` region is deprecated for new resources, so we use `sin` (Singapore).
```powershell
# Create Postgres Cluster
fly postgres create --name ppa-db --region sin --initial-cluster-size 1 --vm-size shared-cpu-1x --volume-size 1

# Create Upstash Redis Database
fly redis create --name ppa-redis --region sin
```

### 4. Attach Databases & Create Persistent Volume
```powershell
# Attach Postgres (this automatically sets the DATABASE_URL secret in your app)
fly postgres attach --app ppa-v5 ppa-db

# Create the persistent volume for storing resumes and PDF reports
fly volumes create ppa_data --region sin --size 1 --app ppa-v5
```

### 5. Set Environment Secrets
*Critically important: Do NOT leave spaces at the end of the URLs inside the quotes!* We set `AUTO_SEED="0"` to prevent multi-process race conditions on boot.
```powershell
# 1. Set the Redis URL (Copy the URL given to you when you ran 'fly redis create')
fly secrets set REDIS_URL="redis://default:xxx@fly-ppa-redis.upstash.io:6379" --app ppa-v5

# 2. Set App Secrets & Passwords
fly secrets set SECRET_KEY="your-strong-secret-key" JWT_SECRET_KEY="your-jwt-key" ADMIN_EMAIL="jainparth7040@gmail.com" ADMIN_PASSWORD="admin123" --app ppa-v5

# 3. Set Gmail SMTP for outgoing emails
fly secrets set MAIL_USERNAME="jainparth7040@gmail.com" MAIL_PASSWORD="your-app-password" --app ppa-v5

# 4. Set Folder Paths and disable Auto-Seed
fly secrets set UPLOAD_FOLDER="/data/uploads" REPORTS_FOLDER="/data/reports" EXPORTS_FOLDER="/data/exports" AUTO_SEED="0" --app ppa-v5
```

### 6. Deploy the Application
Now that the infrastructure is ready, we push the code.
```powershell
fly deploy
```

### 7. Seed the Database
Because we turned `AUTO_SEED` off, we manually trigger the seed script once the app is live.
```powershell
fly ssh console --app ppa-v5 -C "python seed.py"
```

### 8. Verification and Testing
Once everything is deployed, you should verify the architecture is working by hitting these key URLs:
1. **Health Check:** Go to `https://ppa-v5.fly.dev/health`. It should return a JSON response confirming both the DB and Redis are connected (`"db": true, "redis": true`).
2. **API Documentation:** Go to `https://ppa-v5.fly.dev/api/swagger` to see the beautiful Swagger UI rendering your `api.yaml` specification. *(Note: `/api/docs` might show a blank page on some browsers due to CDN/React version incompatibilities with Redoc, so Swagger is the recommended showcase link!)*
3. **Live App:** Go to `https://ppa-v5.fly.dev` and log in with the 1-click Admin pill to test the asynchronous Celery queue by clicking "Generate Report".

---

## Part 2: How The Architecture Works

Here is a breakdown of exactly how everything fits together so you can easily replicate this in your next project.

### 1. The Dockerfile
Your app is containerized using the `Dockerfile`. 
* **The OS Layer:** It uses `python:3.11-slim` as the base. It runs `apt-get install` to install C-compilers and system libraries (`build-essential`, `libpq-dev`). These are strictly required so that packages like `psycopg2` (for Postgres) and your PDF generators can compile correctly.
* **The Directories:** It explicitly runs `mkdir -p /data/...` to create empty folders. These act as "mount points" for the persistent volume.

### 2. The Database (Postgres)
Fly.io runs Postgres in a separate, isolated machine (a cluster). When you run `fly postgres attach`, Fly securely injects a network URL (the `DATABASE_URL`) directly into your app's environment variables. 
* *Your Code:* In `config.py`, your app detects `DATABASE_URL`, connects to the cluster, and uses SQLAlchemy to manage the tables.

### 3. Asynchronous Task Queue (Redis & Celery)
Normally, if a user clicks "Generate Report", the web server freezes until the PDF is finished. You avoided this by using an async architecture.
* **Redis:** Acts as the message broker. When the web server wants a PDF, it drops a sticky note in Redis saying "Please make a PDF". 
* **Celery Worker:** A background process that constantly watches Redis. When it sees the sticky note, it picks it up, runs the heavy machine learning task in the background, and saves the PDF file.
* **Celery Beat:** A cron-job scheduler that automatically drops sticky notes into Redis on a schedule (e.g., every 24 hours).

### 4. The Single-Machine Strategy (`fly.toml`)
This is the most critical technical modification we made. 
On Fly.io's free tier, a standard Persistent Volume (`ppa_data`) can only be attached to **one machine at a time**. 

If we ran the web server (`app`) and the background worker (`worker`) on two separate machines, the worker would generate the PDF, but the web server wouldn't be able to see it, causing your downloads to fail!

**The Solution:**
In your `fly.toml`, we combined all three processes to run concurrently on a single machine using a shell script:
```toml
[processes]
  app = 'sh -c "celery worker... & celery beat... & gunicorn app:app"'
```
By doing this:
1. You only use **1 machine** (saving your free tier limits).
2. The web server, the worker, and the scheduler all share the exact same `/data` hard drive.
3. The worker generates the PDF, saves it to `/data/reports`, and the web server instantly has access to it!

### 5. Persistent Volumes (The `/data` folder)
Docker containers are ephemeral (amnesiacs). If the machine restarts, any file saved inside the container is permanently deleted. 

To fix this, we created the `ppa_data` volume. In `fly.toml`, we mapped `ppa_data` to the `/data` folder inside the container. 
Now, when your app writes a resume to `/data/uploads`, it is actually writing to a physical, permanent SSD in Fly.io's data center that survives deployments and restarts.

### 6. The Multi-Process Race Condition (And How We Solved It)
When we combined Gunicorn, Celery Worker, and Celery Beat into a single machine, we accidentally triggered a classic distributed-systems race condition! 

**The Bug:** Because all three processes start at the exact same millisecond and load `app.py`, they all saw that `AUTO_SEED="1"` was set. They all attempted to seed the database at the exact same time. The first one succeeded, but the second one crashed the entire machine with a `UniqueViolation` because the admin email already existed. 

**The Fix:** This is why we set `AUTO_SEED="0"` in the production secrets. In a multi-process or multi-server production environment, you should never auto-seed on boot. We turned it off, let the machines boot cleanly, and then ran `fly ssh console -C "python seed.py"` manually to securely seed the production database once!
