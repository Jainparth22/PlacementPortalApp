#!/usr/bin/env python
"""Show query plans for the heaviest queries (admin stats, paginated browse, dashboards, notifications).

    python scripts/explain_queries.py

PostgreSQL: runs EXPLAIN (ANALYZE, BUFFERS). SQLite: EXPLAIN QUERY PLAN.
Look for 'Seq Scan' / 'SCAN <table>' on big tables - those need an index. The indexes added in
migrations/versions/0002_add_query_indexes.py cover the filters used below.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'backend'))
os.environ.setdefault('AUTO_SEED', '0')

from sqlalchemy import func  # noqa: E402

from app import app  # noqa: E402
from models import db, Application, PlacementDrive, CompanyProfile, Notification, User  # noqa: E402


def queries():
    return {
        'admin stats - applications by status': db.session.query(Application.status, func.count(Application.id)).group_by(Application.status),
        'admin stats - drives by status': db.session.query(PlacementDrive.status, func.count(PlacementDrive.id)).group_by(PlacementDrive.status),
        'admin stats - companies by approval': db.session.query(CompanyProfile.approval_status, func.count(CompanyProfile.id)).group_by(CompanyProfile.approval_status),
        'student browse (approved drives, by deadline)': PlacementDrive.query.filter_by(status='approved').order_by(PlacementDrive.application_deadline.asc()).limit(6),
        'company dashboard (applicants per drive)': (db.session.query(PlacementDrive.id, func.count(Application.id))
                                                     .outerjoin(Application, Application.drive_id == PlacementDrive.id)
                                                     .filter(PlacementDrive.company_id == 1).group_by(PlacementDrive.id)),
        'drive applications (company view)': Application.query.filter_by(drive_id=1).order_by(Application.application_date.desc()).limit(6),
        'notifications (user feed)': Notification.query.filter_by(user_id=1).order_by(Notification.created_at.desc()).limit(10),
        'admins lookup': User.query.filter_by(role='admin'),
    }


def main():
    with app.app_context():
        dialect = db.engine.dialect.name
        for name, q in queries().items():
            sql = str(q.statement.compile(dialect=db.engine.dialect, compile_kwargs={'literal_binds': True})) if hasattr(q, 'statement') \
                else str(q.compile(dialect=db.engine.dialect, compile_kwargs={'literal_binds': True}))
            prefix = 'EXPLAIN (ANALYZE, BUFFERS) ' if dialect == 'postgresql' else 'EXPLAIN QUERY PLAN '
            print(f'\n=== {name} ===')
            for row in db.session.execute(db.text(prefix + sql)):
                print('  ', ' | '.join(str(c) for c in row))


if __name__ == '__main__':
    main()
