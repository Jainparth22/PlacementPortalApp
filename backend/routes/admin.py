import os
from flask import Blueprint, request, jsonify
from werkzeug.security import generate_password_hash
from models import db, User, CompanyProfile, StudentProfile, PlacementDrive, Application, DriveApproval, MonthlyReport, Notification, AsyncJob
from auth import role_required
from cache import cache_get, cache_set, cache_delete, cache_delete_pattern
from pagination import paginated_response
import datetime

admin_bp = Blueprint('admin', __name__)


# admin dashboard (cached)
@admin_bp.route('/api/admin/dashboard', methods=['GET'])
@role_required('admin')
def admin_dashboard(user):
    cached = cache_get('admin_stats')
    if cached:
        return jsonify(cached), 200

    stats = {
        'total_students': StudentProfile.query.count(),
        'total_companies': CompanyProfile.query.count(),
        'total_drives': PlacementDrive.query.count(),
        'pending_companies': CompanyProfile.query.filter_by(approval_status='pending').count(),
        'approved_companies': CompanyProfile.query.filter_by(approval_status='approved').count(),
        'pending_drives': PlacementDrive.query.filter_by(status='pending').count(),
        'approved_drives': PlacementDrive.query.filter_by(status='approved').count(),
        'total_applications': Application.query.count(),
        'selected_students': Application.query.filter_by(status='selected').count(),
        'active_students': User.query.filter_by(role='student', is_active=True).count(),
        'blacklisted_users': User.query.filter_by(is_blacklisted=True).count(),
        # Chart data: application status breakdown
        'chart_app_status': {
            'applied': Application.query.filter_by(status='applied').count(),
            'shortlisted': Application.query.filter_by(status='shortlisted').count(),
            'selected': Application.query.filter_by(status='selected').count(),
            'rejected': Application.query.filter_by(status='rejected').count(),
            'withdrawn': Application.query.filter_by(status='withdrawn').count(),
        },
        # Chart data: drives by status
        'chart_drive_status': {
            'pending': PlacementDrive.query.filter_by(status='pending').count(),
            'approved': PlacementDrive.query.filter_by(status='approved').count(),
            'rejected': PlacementDrive.query.filter_by(status='rejected').count(),
            'closed': PlacementDrive.query.filter_by(status='closed').count(),
        },
    }
    cache_set('admin_stats', stats, ttl=300)
    return jsonify(stats), 200


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
    notification = Notification(
        user_id=company.user_id,
        message=f'Your company "{company.company_name}" has been approved! You can now create placement drives.',
        channel='in-app', is_sent=True,
    )
    db.session.add(notification)
    db.session.commit()
    cache_delete('admin_stats')
    return jsonify({'message': 'Company approved', 'company': company.to_dict()}), 200


@admin_bp.route('/api/admin/companies/<int:id>/reject', methods=['PUT'])
@role_required('admin')
def reject_company(user, id):
    company = CompanyProfile.query.get_or_404(id)
    company.approval_status = 'rejected'
    data = request.get_json(silent=True)
    remarks = data.get('remarks', '') if data else ''
    notification = Notification(
        user_id=company.user_id,
        message=f'Your company "{company.company_name}" registration was rejected. {remarks}',
        channel='in-app', is_sent=True,
    )
    db.session.add(notification)
    db.session.commit()
    cache_delete('admin_stats')
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
    cache_delete('admin_stats')
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
    notification = Notification(
        user_id=drive.company.user_id,
        message=f'Your placement drive "{drive.drive_name}" has been approved!',
        channel='in-app', is_sent=True,
    )
    db.session.add(approval)
    db.session.add(notification)
    db.session.commit()
    cache_delete('admin_stats')
    cache_delete('approved_drives')
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
    notification = Notification(
        user_id=drive.company.user_id,
        message=f'Your placement drive "{drive.drive_name}" was rejected. {remarks}',
        channel='in-app', is_sent=True,
    )
    db.session.add(approval)
    db.session.add(notification)
    db.session.commit()
    cache_delete('admin_stats')
    return jsonify({'message': 'Drive rejected', 'drive': drive.to_dict()}), 200


@admin_bp.route('/api/admin/drives/<int:id>/close', methods=['PUT'])
@role_required('admin')
def close_drive(user, id):
    drive = PlacementDrive.query.get_or_404(id)
    drive.status = 'closed'
    db.session.commit()
    cache_delete('admin_stats')
    cache_delete('approved_drives')
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
    cache_delete('admin_stats')
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
    cache_delete('admin_stats')
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
def trigger_monthly_report(user):
    from tasks import generate_monthly_report
    from cache import get_redis
    job = AsyncJob(
        user_id=user.id,
        job_type='generate_monthly_report',
        status='pending',
    )
    db.session.add(job)
    db.session.commit()
    # Try Celery async; fallback to sync if Redis/worker unavailable (single-web deploy)
    try:
        # If Redis down, run sync directly
        if get_redis() is None:
            raise RuntimeError("Redis unavailable — running sync")
        generate_monthly_report.delay(job.id)
    except Exception as e:
        print(f"[!] Celery delay failed ({e}), falling back to sync report generation")
        try:
            # Run synchronously so 202 job still completes even without worker
            generate_monthly_report(job.id)
        except Exception as se:
            print(f"[!] Sync report also failed: {se}")
    return jsonify({'message': 'Monthly report generation started', 'job_id': job.id}), 202


@admin_bp.route('/api/admin/reports/download/<int:id>', methods=['GET'])
@role_required('admin')
def download_report(user, id):
    from flask import send_file
    report = MonthlyReport.query.get_or_404(id)
    fmt = request.args.get('format', 'pdf')
    if fmt == 'pdf':
        pdf_path = report.report_path.replace('.html', '.pdf') if report.report_path else None
        if pdf_path and os.path.exists(pdf_path):
            return send_file(pdf_path, as_attachment=True, download_name=f'report_{report.month}.pdf')
    if report.report_path and os.path.exists(report.report_path):
        return send_file(report.report_path, as_attachment=True, download_name=f'report_{report.month}.html')
    return jsonify({'error': 'Report file not found'}), 404

