# Hosting PPA for free (honest guide)

> Prices and free tiers change. Everything below was checked against Microsoft's pages in November 2026 — **re-check the
> linked pages before you click "create"**, and set a spending alert/budget the first day.

## Is Azure free?

**Partly, and mostly for a limited time.** Microsoft's [Azure free account](https://azure.microsoft.com/en-us/pricing/purchase-options/azure-account) gives:

| What | Limit | Catch |
|---|---|---|
| **$200 credit** | 30 days | After that (or when credit is used) you must upgrade to pay-as-you-go to keep using anything; free amounts continue, other usage is billed. |
| **12 months of free monthly amounts** for ~20+ services, e.g. a small **Linux/Windows VM** (750 h/month of B1s / B2pts v2 / B2ats v2 — the exact sizes differ between Microsoft's pages, check the current list), **PostgreSQL Flexible Server B1ms** (750 h, 32 GB), Blob storage (5 GB) | 12 months | New Azure customers only; one free account per person. |
| **Always-free services** (65+), e.g. **Azure Container Apps** free grant (180,000 vCPU-s, 360,000 GiB-s, 2 M requests per month), Azure Functions, Static Web Apps, Key Vault operations | no expiry | Free *amounts*, not free everything; usage above the grant is billed. |
| **[Azure for Students](https://azure.microsoft.com/en-us/free/students)** | $100 credit, no credit card | Needs verification through your *academic* email; whether your institution qualifies is decided by Microsoft's verification, not a public list. Try it — it's the easiest route if you're eligible. |

Things to know
- A normal free account **asks for a credit card** (identity check). Azure doesn't silently charge you past the free amounts
  if you stay on the *free* subscription, but you can be billed if you upgrade to pay-as-you-go. Set a **budget alert**.
- **Azure Cache for Redis is not in the free lists I found.** Run Redis as a container on the same VM instead.
- Free amounts are *monthly and don't roll over*.

## Three realistic free setups (pick one)

### A — One free VM running docker compose (simplest, works anywhere)
This is how most people host hobby/portfolio apps for free. Candidates:
- **Azure free VM** (12 months; check the current free sizes — a 1 GB RAM B1s is *tight* for Postgres + Redis + web + worker; prefer the 2 GB sizes if free, or drop Flower/Grafana/Jaeger).
- **Oracle Cloud "Always Free" ARM VM** (up to 4 OCPU / 24 GB — plenty for the whole compose stack, no expiry; capacity is sometimes hard to get, and you must watch for inactivity reclamation rules).

Steps (same on any Linux VM):
1. Create an Ubuntu VM, open ports 80/443 only.
2. `curl -fsSL https://get.docker.com | sh`, `git clone` your repo.
3. Create `.env` with **real secrets** (`SECRET_KEY`, `JWT_SECRET_KEY`, `ADMIN_PASSWORD`, `COOKIE_SECURE=1`, `METRICS_TOKEN`, `TRUSTED_PROXY_COUNT=1`).
4. Put **Caddy** in front for automatic HTTPS (a free Let's Encrypt certificate) — `deploy/Caddyfile` and `docker-compose.prod.yml` in this repo:
   ```bash
   docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d --build
   ```
5. A free domain: a subdomain from [DuckDNS](https://www.duckdns.org) or `nip.io`, or a cheap domain later. Point an A record at the VM's IP; Caddy fetches the certificate by itself.
6. Backups: nightly `docker compose exec postgres pg_dump -U ppa ppa | gzip > backup.sql.gz` to a free object bucket (see B).

### B — Add free object storage so the app is "multi-replica ready"
- **Cloudflare R2**: 10 GB free storage, no egress fees, S3-compatible → `STORAGE_BACKEND=s3`, `S3_ENDPOINT_URL=https://<account>.r2.cloudflarestorage.com`.
- or **Azure Blob** (5 GB free for 12 months) → `STORAGE_BACKEND=azure`.
See [STORAGE.md](STORAGE.md). With files off the VM you can later move web/worker to a container platform without data loss.

### C — Fully managed (more moving parts, good Azure story)
- **Azure Container Apps** (free grant) for `web` + `worker` (+ a single-replica app for `beat`), 
- **Azure Database for PostgreSQL Flexible Server B1ms** (free 12 months),
- **Redis**: a small container app / VM (managed Redis isn't free), 
- **Blob Storage** for files, **Key Vault** for secrets, **Application Insights** via the OpenTelemetry endpoint.
Container Apps scale-to-zero means a cold start of a few seconds on the first request, and Celery workers need at
least one replica (or a scale rule). Expect to tune it; it is the most "enterprise-like" option and a strong interview talking point.

## Free-tier traps to avoid
- **Idle timeouts / sleeping apps**: free web tiers often sleep (cold start 10–60 s). A VM doesn't sleep.
- **Disk is not backed up** by default on a free VM — take your own `pg_dump`.
- **Don't expose Postgres/Redis ports** to the internet. Only 80/443 (Caddy). The compose file keeps them on the internal network.
- **Never commit `.env`** (it's git-ignored). Rotate any secret that has ever been pushed.
- **Budget alert** on day one; delete resources you stop using — a forgotten Redis/VM is how "free" turns into a bill.

## Pre-flight checklist (any option)
- [ ] `APP_ENV=production`, strong secrets, `AUTO_SEED=0` (or change demo passwords!)
- [ ] `COOKIE_SECURE=1` (requires HTTPS), `TRUSTED_PROXY_COUNT=1` behind Caddy
- [ ] `STATE_REDIS_URL` on an instance with persistence + `noeviction`
- [ ] `flask db upgrade` ran once (the entrypoint does it for `web`)
- [ ] exactly **one** `beat` instance
- [ ] `METRICS_TOKEN` set (or `/metrics` stays disabled in production)
- [ ] backups + a tested restore
- [ ] budget alert

Sources: [Azure free account](https://azure.microsoft.com/en-us/pricing/purchase-options/azure-account) ·
[Free Azure services](https://azure.microsoft.com/en-us/pricing/free-services) ·
[Container Apps pricing](https://azure.microsoft.com/en-us/pricing/details/container-apps/) ·
[Azure for Students](https://azure.microsoft.com/en-us/free/students)
