# File storage — why it matters and what had to change

## The problem (why "uploads on a local volume" blocks more than one replica)

Before this change the app wrote files to a directory on the machine it ran on (`UPLOAD_FOLDER`, `REPORTS_FOLDER`,
`EXPORTS_FOLDER`) and stored **filesystem paths** in the database. That works with exactly one process on one host.
It breaks in three concrete ways as soon as you scale or deploy normally:

| Scenario | What happens |
|---|---|
| **2 web replicas** behind a load balancer | Student uploads a résumé → saved on replica A. The ATS check lands on replica B → *file not found*. |
| **Worker ≠ web host** (always true in containers / on Azure) | The Celery worker generates `report_2026-11.pdf` on its own disk. The admin's download request hits the web container → *file not found*. |
| **Redeploy / container replaced** | A container's filesystem is ephemeral; every upload since the last deploy is gone, unless a volume is attached — and a single-host volume can't be shared by containers on different hosts. |

Also: a database row that holds `C:\...\uploads\resume_3.pdf` (an absolute path) is not even portable between your
laptop and a Linux container.

## The fix: an abstraction + keys instead of paths

`backend/storage.py` defines one interface; the application never touches the filesystem directly any more.

```
Storage.put_bytes(key, data, content_type)   Storage.get_bytes(key)    Storage.exists(key)
Storage.delete(key)                          Storage.send(key, download_name)   # streaming download response
```

Backends, chosen with `STORAGE_BACKEND`:

| Value | Where bytes live | Use when |
|---|---|---|
| `local` (default) | directories on disk (atomic writes) | dev, single host |
| `s3` | any **S3-compatible** bucket: AWS S3, **Cloudflare R2**, MinIO, Backblaze B2 | production; R2 has a free tier |
| `azure` | **Azure Blob Storage** (connection string, or managed identity) | Azure deployments |

The database now stores **keys** such as `resumes/resume_3_cv.pdf`, `reports/report_2026-11.pdf`,
`exports/applications_3_job12.csv` — meaningful on every backend and every machine.
Keys are validated (`^(resumes|reports|exports)/[A-Za-z0-9._-]+$`, no `..`) so user input can never choose a path.

### What changed in the code
- `routes/student.py` — résumé upload writes to storage (after the PDF magic-byte check); ATS reads the PDF from storage;
  export download streams from storage.
- `routes/admin.py` — report download streams from storage.
- `tasks.py` — reports (HTML + PDF) and CSV exports are built in memory and written with `put_bytes`, so a worker on
  another host produces files the web tier can serve. (Idempotent: deterministic key per job.)
- `config.py` — `STORAGE_BACKEND`, `S3_*`, `AZURE_STORAGE_*`.
- `scripts/migrate_storage.py` — copies existing local files to the new backend and rewrites DB values to keys
  (`--dry-run` first). Legacy values (absolute or `uploads/resumes/x.pdf`) still resolve on the local backend, so nothing breaks mid-migration.
- `tests/test_storage.py` — one contract test-suite run against local disk, S3 (moto) and Azure (fake client), plus the
  scenario that motivated all this: *a "worker" writes an export, a different "web" process downloads it*.

## What you need to do to use it in production

1. **Create a bucket / container** and keep it **private** (no public access). Downloads go through the app, which
   checks the user's role and ownership first.
2. **Credentials**
   - S3/R2: `S3_BUCKET`, `S3_ENDPOINT_URL` (for R2/MinIO), `S3_REGION`, plus `AWS_ACCESS_KEY_ID` / `AWS_SECRET_ACCESS_KEY`.
   - Azure: `AZURE_STORAGE_CONNECTION_STRING`, **or** `AZURE_STORAGE_ACCOUNT_URL` + a managed identity (no secret to leak).
   - Grant the minimum: read/write/delete on that bucket only.
3. Set `STORAGE_BACKEND=s3|azure` on **web and worker** (both must point at the same bucket).
4. Run `python scripts/migrate_storage.py --dry-run`, then for real, once.
5. Optional hardening: bucket lifecycle rule (expire `exports/` after 30 days), server-side encryption (on by default for
   S3/R2/Azure), versioning for `resumes/`, antivirus scan on upload (ClamAV or the cloud provider's scanner).
6. Remove the volume mounts you no longer need.

## Design notes / trade-offs (good interview material)
- **Why proxy downloads through the app instead of presigned URLs?** Authorisation stays in one place (role + ownership
  check), no URL can be shared after logout, and the bucket stays fully private. Cost: bytes pass through the web tier.
  For large files switch `send()` to return a short-lived presigned URL (a 302) — a 10-line change per backend.
- **Why `put_bytes` (whole file in memory)?** Résumés are capped at 5 MB and reports/exports are small. For big files
  use multipart/streaming upload.
- **Eventual consistency:** S3 is strongly consistent for read-after-write today; older S3-compatible stores may not be.
- **Two-phase problem:** writing the object and the DB row is not atomic. Order is "write object, then commit row", so a
  crash leaves an orphan object (harmless, collectable by a lifecycle rule) rather than a row pointing at nothing.
