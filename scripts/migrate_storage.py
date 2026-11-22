#!/usr/bin/env python
"""Move existing local files to the configured storage backend and rewrite DB values to storage keys.

    # 1. configure the TARGET backend (e.g. STORAGE_BACKEND=s3 S3_BUCKET=... ) and the old local folders
    # 2. dry run first:
    python scripts/migrate_storage.py --dry-run
    # 3. for real:
    python scripts/migrate_storage.py

What it touches
    student_profiles.resume_path   -> resumes/<file>
    monthly_reports.report_path    -> reports/<file>.html   (+ the sibling .pdf is uploaded too)
    async_jobs.file_path           -> reports/... or exports/...
Safe to re-run: rows that already hold a key whose object exists are skipped; local files are NOT deleted.
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'backend'))
os.environ.setdefault('AUTO_SEED', '0')

from app import app  # noqa: E402
from models import db, StudentProfile, MonthlyReport, AsyncJob  # noqa: E402
from storage import LocalStorage, get_storage, CATEGORIES  # noqa: E402

TYPES = {'.pdf': 'application/pdf', '.html': 'text/html', '.csv': 'text/csv'}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--dry-run', action='store_true')
    args = ap.parse_args()

    with app.app_context():
        target = get_storage()
        source = LocalStorage({
            'resumes': os.path.join(app.config['UPLOAD_FOLDER'], 'resumes'),
            'reports': app.config['REPORTS_FOLDER'],
            'exports': app.config['EXPORTS_FOLDER'],
        })
        print(f'target backend: {target.name}   dry-run: {args.dry_run}')
        moved = skipped = missing = 0

        def migrate(obj, attr, category, with_pdf_sibling=False):
            nonlocal moved, skipped, missing
            old = getattr(obj, attr)
            if not old:
                return
            base = os.path.basename(old)
            key = f'{category}/{base}'
            if old == key and target.exists(key):
                skipped += 1
                return
            keys = [(old, key)]
            if with_pdf_sibling and base.endswith('.html'):
                keys.append((old[:-5] + '.pdf', key[:-5] + '.pdf'))
            for src_ref, dst_key in keys:
                if not source.exists(src_ref):
                    if src_ref == old:
                        print(f'  MISSING local file for {type(obj).__name__}#{obj.id}: {old}')
                        missing += 1
                    continue
                print(f'  {src_ref} -> {dst_key}')
                if not args.dry_run:
                    ext = os.path.splitext(dst_key)[1]
                    target.put_bytes(dst_key, source.get_bytes(src_ref), TYPES.get(ext))
            if not args.dry_run and source.exists(old):
                setattr(obj, attr, key)
            moved += 1

        for sp in StudentProfile.query.filter(StudentProfile.resume_path.isnot(None)):
            migrate(sp, 'resume_path', 'resumes')
        for r in MonthlyReport.query.filter(MonthlyReport.report_path.isnot(None)):
            migrate(r, 'report_path', 'reports', with_pdf_sibling=True)
        for j in AsyncJob.query.filter(AsyncJob.file_path.isnot(None)):
            migrate(j, 'file_path', 'exports' if (j.file_path or '').endswith('.csv') else 'reports')

        if not args.dry_run:
            db.session.commit()
        print(f'done: {moved} migrated, {skipped} already migrated, {missing} missing source files '
              f'(categories: {", ".join(CATEGORIES)})')


if __name__ == '__main__':
    main()
