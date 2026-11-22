import logging
from flask import Blueprint, request, jsonify
from sqlalchemy import func
from models import db, User, CompanyProfile, StudentProfile, PlacementDrive, Application, DriveApproval, MonthlyReport, AsyncJob
from events import notify
from auth import role_required
from cache import cache_get_or_set, make_key, invalidate, cache_stats
from ratelimit import rate_limit
from idempotency import idempotent
from storage import get_storage
from pagination import paginated_response

admin_bp = Blueprint('admin', __name__)
log = logging.getLogger(__name__)


def _build_admin_stats():
    """All dashboard numbers with a handful of grouped queries (was ~20 separate COUNTs)."""
    app_counts = dict(db.session.query(Application.status, func.count(Application.id)).group_by(Application.status).all())
    drive_counts = dict(db.session.query(PlacementDrive.status, func.count(PlacementDrive.id)).group_by(PlacementDrive.status).all())
    company_counts = dict(db.session.query(CompanyProfile.approval_status, func.count(CompanyProfile.id)).group_by(CompanyProfile.approval_status).all())
    return {
        'total_students': StudentProfile.query.count(),
        'total_companies': sum(company_counts.values()),
        'total_drives': sum(drive_counts.values()),
        'pending_companies': company_counts.get('pending', 0),
        'approved_companies': company_counts.get('approved', 0),
        'pending_drives': drive_counts.get('pending', 0),
        'approved_drives': drive_counts.get('approved', 0),
        'total_applications': sum(app_counts.values()),
        'selected_students': app_counts.get('selected', 0),
        'active_students': User.query.filter_by(role='student', is_active=True).count(),
        'blacklisted_users': User.query.filter_by(is_blacklisted=True).count(),
        'chart_app_status': {k: app_counts.get(k, 0) for k in ('applied', 'shortlisted', 'selected', 'rejected', 'withdrawn')},
        'chart_drive_status': {k: drive_counts.get(k, 0) for k in ('pending', 'approved', 'rejected', 'closed')},
    }


# admin dashboard (cached, stampede-protected; invalidated by the 'stats' namespace)
@admin_bp.route('/api/admin/dashboard', methods=['GET'])
@role_required('admin')
def admin_dashboard(user):
    stats = cache_get_or_set(make_key('stats', 'admin'), _build_admin_stats, ttl=300)
    return jsonify(stats), 200


@admin_bp.route('/api/admin/cache-stats', methods=['GET'])
@role_required('admin')
def admin_cache_stats(user):
    return jsonify(cache_stats()), 200


# search
@admin_bp.route('/api/admin/search', methods=['GET'])
@role_required('admin')
def admin_search(user):
    q = request.args.get('q', '').strip()
    search_type = request.args.get('type', 'all')  # all, students, companies

    results = {'students': [], 'companies': []}

    if search_type in ('all', 'students'):
        students = StudentProfile.query.filter(
            (StudentProfile.full_name.ilike(f'%{q}%')) |
            (StudentProfile.department.ilike(f'%{q}%'))
        ).limit(20).all()
        results['students'] = [s.to_dict() for s in students]

    if search_type in ('all', 'companies'):
        companies = CompanyProfile.query.filter(
            (CompanyProfile.company_name.ilike(f'%{q}%')) |
            (CompanyProfile.industry.ilike(f'%{q}%'))
        ).limit(20).all()
        results['companies'] = [c.to_dict() for c in companies]

    return jsonify(results), 200


# company management — paginated (page, per_page, status)
@admin_bp.route('/api/admin/companies', methods=['GET'])
@role_required('admin')
def list_companies(user):
    status_filter = request.args.get('status', None)
    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 6, type=int)
    query = CompanyProfile.query
    if status_filter:
        query = query.filter_by(approval_status=status_filter)
    query = query.order_by(CompanyProfile.id.desc())
    # Return paginated if requested, else fallback to array for backward compat
    if 'page' in request.args or 'per_page' in request.args:
        return jsonify(paginated_response(query, page, per_page)), 200
    # Default paginated (new behavior)
    return jsonify(paginated_response(query, page, per_page)), 200


@admin_bp.route('/api/admin/companies/pending', methods=['GET'])
@role_required('admin')
def pending_companies(user):
    companies = CompanyProfile.query.filter_by(approval_status='pending').all()
    return jsonify([c.to_dict() for c in companies]), 200


@admin_bp.route('/api/admin/companies/<int:id>/approve', methods=['PUT'])
@role_required('admin')
def approve_company(user, id):
    company = CompanyProfile.query.get_or_404(id)
    company.approval_status = 'approved'
    notify(company.user_id, f'Your company "{company.company_name}" has been approved! You can now create placement drives.')
    db.session.commit()
    invalidate('stats')
    return jsonify({'message': 'Company approved', 'company': company.to_dict()}), 200


@admin_bp.route('/api/admin/companies/<int:id>/reject', methods=['PUT'])
@role_required('admin')
def reject_company(user, id):
    company = CompanyProfile.query.get_or_404(id)
    company.approval_status = 'rejected'
    data = request.get_json(silent=True)
    remarks = data.get('remarks', '') if data else ''
    notify(company.user_id, f'Your company "{company.company_name}" registration was rejected. {remarks}')
    db.session.commit()
    invalidate('stats')
    return jsonify({'message': 'Company rejected', 'company': company.to_dict()}), 200


@admin_bp.route('/api/admin/companies/<int:id>/blacklist', methods=['PUT'])
@role_required('admin')
def blacklist_company(user, id):
    company = CompanyProfile.query.get_or_404(id)
    company_user = User.query.get(company.user_id)
    data = request.get_json(silent=True)
    action = data.get('action', 'blacklist') if data else 'blacklist'

    if action == 'unblacklist':
        company_user.is_blacklisted = False
        msg = f'Company "{company.company_name}" has been un-blacklisted.'
    else:
        company_user.is_blacklisted = True
        msg = f'Company "{company.company_name}" has been blacklisted.'

    db.session.commit()
    invalidate('stats')
    return jsonify({'message': msg, 'company': company.to_dict()}), 200


# drive management — paginated
@admin_bp.route('/api/admin/drives', methods=['GET'])
@role_required('admin')
def list_drives(user):
    status_filter = request.args.get('status', None)
    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 6, type=int)
    query = PlacementDrive.query
    if status_filter:
        query = query.filter_by(status=status_filter)
    query = query.order_by(PlacementDrive.id.desc())
    return jsonify(paginated_response(query, page, per_page)), 200


@admin_bp.route('/api/admin/drives/pending', methods=['GET'])
@role_required('admin')
def pending_drives(user):
    drives = PlacementDrive.query.filter_by(status='pending').all()
    return jsonify([d.to_dict() for d in drives]), 200


@admin_bp.route('/api/admin/drives/<int:id>/approve', methods=['PUT'])
@role_required('admin')
def approve_drive(user, id):
    drive = PlacementDrive.query.get_or_404(id)
    drive.status = 'approved'
    data = request.get_json(silent=True)
    approval = DriveApproval(
        drive_id=drive.id, admin_id=user.id,
        action='approved', remarks=data.get('remarks', '') if data else '',
    )
    notify(drive.company.user_id, f'Your placement drive "{drive.drive_name}" has been approved!')
    db.session.add(approval)
    db.session.commit()
    invalidate('stats', 'drives')
    return jsonify({'message': 'Drive approved', 'drive': drive.to_dict()}), 200


@admin_bp.route('/api/admin/drives/<int:id>/reject', methods=['PUT'])
@role_required('admin')
def reject_drive(user, id):
    drive = PlacementDrive.query.get_or_404(id)
    drive.status = 'rejected'
    data = request.get_json(silent=True)
    remarks = data.get('remarks', '') if data else ''
    approval = DriveApproval(
        drive_id=drive.id, admin_id=user.id,
        action='rejected', remarks=remarks,
    )
    notify(drive.company.user_id, f'Your placement drive "{drive.drive_name}" was rejected. {remarks}')
    db.session.add(approval)
    db.session.commit()
    invalidate('stats')
    return jsonify({'message': 'Drive rejected', 'drive': drive.to_dict()}), 200


@admin_bp.route('/api/admin/drives/<int:id>/close', methods=['PUT'])
@role_required('admin')
def close_drive(user, id):
    drive = PlacementDrive.query.get_or_404(id)
    drive.status = 'closed'
    db.session.commit()
    invalidate('stats', 'drives')
    return jsonify({'message': 'Drive closed', 'drive': drive.to_dict()}), 200


# student management — paginated
@admin_bp.route('/api/admin/students', methods=['GET'])
@role_required('admin')
def list_students(user):
    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 6, type=int)
    query = StudentProfile.query.order_by(StudentProfile.id.desc())
    return jsonify(paginated_response(query, page, per_page)), 200


@admin_bp.route('/api/admin/students/<int:id>/deactivate', methods=['PUT'])
@role_required('admin')
def deactivate_student(user, id):
    student = StudentProfile.query.get_or_404(id)
    student_user = User.query.get(student.user_id)
    data = request.get_json(silent=True)
    action = data.get('action', 'deactivate') if data else 'deactivate'

    if action == 'activate':
        student_user.is_active = True
        msg = f'Student "{student.full_name}" has been activated.'
    else:
        student_user.is_active = False
        msg = f'Student "{student.full_name}" has been deactivated.'

    db.session.commit()
    invalidate('stats')
    return jsonify({'message': msg}), 200


@admin_bp.route('/api/admin/students/<int:id>/blacklist', methods=['PUT'])
@role_required('admin')
def blacklist_student(user, id):
    student = StudentProfile.query.get_or_404(id)
    student_user = User.query.get(student.user_id)
    data = request.get_json(silent=True)
    action = data.get('action', 'blacklist') if data else 'blacklist'

    if action == 'unblacklist':
        student_user.is_blacklisted = False
        msg = f'Student "{student.full_name}" has been un-blacklisted.'
    else:
        student_user.is_blacklisted = True
        msg = f'Student "{student.full_name}" has been blacklisted.'

    db.session.commit()
    invalidate('stats')
    return jsonify({'message': msg}), 200


# applications — paginated (status, drive_id, page, per_page)
@admin_bp.route('/api/admin/applications', methods=['GET'])
@role_required('admin')
def list_applications(user):
    drive_id = request.args.get('drive_id', None, type=int)
    status_filter = request.args.get('status', None)
    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 6, type=int)
    query = Application.query
    if drive_id:
        query = query.filter_by(drive_id=drive_id)
    if status_filter:
        query = query.filter_by(status=status_filter)
    query = query.order_by(Application.application_date.desc())
    return jsonify(paginated_response(query, page, per_page)), 200


# reports — paginated
@admin_bp.route('/api/admin/reports/monthly', methods=['GET'])
@role_required('admin')
def monthly_reports(user):
    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 6, type=int)
    query = MonthlyReport.query.order_by(MonthlyReport.id.desc())
    return jsonify(paginated_response(query, page, per_page)), 200


@admin_bp.route('/api/admin/reports/generate', methods=['POST'])
@role_required('admin')
@idempotent
@rate_limit('report-generate')
def trigger_monthly_report(user):
    from tasks import generate_monthly_report
    from async_dispatch import dispatch
    job = AsyncJob(user_id=user.id, job_type='generate_monthly_report', status='pending')
    db.session.add(job)
    db.session.commit()
    # Queue on Celery when a worker is alive, otherwise run inline so the job still completes.
    mode = dispatch(generate_monthly_report, job.id)
    return jsonify({'message': 'Monthly report generation started', 'job_id': job.id, 'mode': mode}), 202


# dead-letter queue: tasks that failed permanently
@admin_bp.route('/api/admin/dead-letters', methods=['GET'])
@role_required('admin')
def list_dead_letters_route(user):
    from dead_letter import list_dead_letters
    limit = min(100, max(1, request.args.get('limit', 50, type=int)))
    return jsonify({'items': list_dead_letters(limit)}), 200


@admin_bp.route('/api/admin/dead-letters/<task_id>/replay', methods=['POST'])
@role_required('admin')
def replay_dead_letter_route(user, task_id):
    from dead_letter import replay_dead_letter
    if replay_dead_letter(task_id):
        return jsonify({'message': 'Task re-queued'}), 202
    return jsonify({'error': 'Dead-letter entry not found'}), 404


@admin_bp.route('/api/admin/reports/download/<int:id>', methods=['GET'])
@role_required('admin')
def download_report(user, id):
    report = db.get_or_404(MonthlyReport, id)
    if not report.report_path:
        return jsonify({'error': 'Report file not found'}), 404
    storage = get_storage()
    html_key = report.report_path
    pdf_key = html_key[:-5] + '.pdf' if html_key.endswith('.html') else html_key
    try:
        if request.args.get('format', 'pdf') == 'pdf' and storage.exists(pdf_key):
            return storage.send(pdf_key, f'report_{report.month}.pdf', 'application/pdf')
        return storage.send(html_key, f'report_{report.month}.html', 'text/html')
    except (FileNotFoundError, ValueError):
        return jsonify({'error': 'Report file not found'}), 404

