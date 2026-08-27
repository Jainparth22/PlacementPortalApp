from flask import Blueprint, request, jsonify
from werkzeug.security import generate_password_hash
from models import db, User, CompanyProfile, PlacementDrive, Application, Interview, Notification
from auth import login_required, role_required
from cache import cache_delete, cache_delete_pattern
from pagination import paginated_response
from datetime import datetime
from validators import validate_email, validate_password, validate_phone, validate_url, validate_cgpa, validate_year, validate_name

company_bp = Blueprint('company', __name__)


# register company
@company_bp.route('/api/companies/register', methods=['POST'])
def register_company():
    data = request.json
    if not data:
        return jsonify({'error': 'No data provided'}), 400

    email = data.get('email', '').strip()
    password = data.get('password', '').strip()
    company_name = data.get('company_name', '').strip()

    if not all([email, password, company_name]):
        return jsonify({'error': 'Email, password, and company name are required'}), 400

    # validate inputs
    if not validate_email(email):
        return jsonify({'error': 'Please enter a valid email address'}), 400
    ok, err = validate_password(password)
    if not ok:
        return jsonify({'error': err}), 400
    ok, err = validate_name(company_name, 'Company name')
    if not ok:
        return jsonify({'error': err}), 400
    ok, err = validate_phone(data.get('hr_phone', ''))
    if not ok:
        return jsonify({'error': err}), 400
    ok, err = validate_url(data.get('website', ''))
    if not ok:
        return jsonify({'error': err}), 400
    if data.get('hr_email') and not validate_email(data['hr_email']):
        return jsonify({'error': 'HR email is not valid'}), 400

    if User.query.filter_by(email=email).first():
        return jsonify({'error': 'Email already registered'}), 409

    user = User(
        email=email,
        password_hash=generate_password_hash(password),
        role='company',
    )
    db.session.add(user)
    db.session.flush()

    company = CompanyProfile(
        user_id=user.id,
        company_name=company_name,
        hr_name=data.get('hr_name', ''),
        hr_email=data.get('hr_email', email),
        hr_phone=data.get('hr_phone', ''),
        website=data.get('website', ''),
        description=data.get('description', ''),
        industry=data.get('industry', ''),
        company_size=data.get('company_size', ''),
        approval_status='pending',
    )
    db.session.add(company)

    # Notify admin
    admin = User.query.filter_by(role='admin').first()
    if admin:
        notification = Notification(
            user_id=admin.id,
            message=f'New company "{company_name}" registered and awaiting approval.',
            channel='in-app', is_sent=True,
        )
        db.session.add(notification)

    db.session.commit()
    cache_delete('admin_stats')
    return jsonify({'message': 'Company registered successfully. Awaiting admin approval.', 'company': company.to_dict()}), 201


# company profile
@company_bp.route('/api/companies/profile', methods=['GET'])
@role_required('company')
def get_company_profile(user):
    company = CompanyProfile.query.filter_by(user_id=user.id).first()
    if not company:
        return jsonify({'error': 'Company profile not found'}), 404
    return jsonify(company.to_dict()), 200


@company_bp.route('/api/companies/profile', methods=['PUT'])
@role_required('company')
def update_company_profile(user):
    company = CompanyProfile.query.filter_by(user_id=user.id).first()
    if not company:
        return jsonify({'error': 'Company profile not found'}), 404

    data = request.json
    if data.get('company_name'):
        ok, err = validate_name(data['company_name'], 'Company name')
        if not ok:
            return jsonify({'error': err}), 400
        company.company_name = data['company_name']
    if data.get('hr_name'):
        company.hr_name = data['hr_name']
    if data.get('hr_email'):
        if not validate_email(data['hr_email']):
            return jsonify({'error': 'HR email is not valid'}), 400
        company.hr_email = data['hr_email']
    if data.get('hr_phone'):
        ok, err = validate_phone(data['hr_phone'])
        if not ok:
            return jsonify({'error': err}), 400
        company.hr_phone = data['hr_phone']
    if data.get('website'):
        ok, err = validate_url(data['website'])
        if not ok:
            return jsonify({'error': err}), 400
        company.website = data['website']
    if data.get('description'):
        company.description = data['description']
    if data.get('industry'):
        company.industry = data['industry']
    if data.get('company_size'):
        company.company_size = data['company_size']

    db.session.commit()
    return jsonify({'message': 'Profile updated', 'company': company.to_dict()}), 200


# company dashboard
@company_bp.route('/api/company/dashboard', methods=['GET'])
@role_required('company')
def company_dashboard(user):
    company = CompanyProfile.query.filter_by(user_id=user.id).first()
    if not company:
        return jsonify({'error': 'Company not found'}), 404

    drives = PlacementDrive.query.filter_by(company_id=company.id).all()
    total_applicants = sum(d.applications.count() for d in drives)

    return jsonify({
        'company': company.to_dict(),
        'total_drives': len(drives),
        'total_applicants': total_applicants,
        'drives_summary': [
            {
                'id': d.id,
                'drive_name': d.drive_name,
                'status': d.status,
                'applicants': d.applications.count(),
            }
            for d in drives
        ],
    }), 200


# placement drives — paginated
@company_bp.route('/api/company/drives', methods=['GET'])
@role_required('company')
def list_company_drives(user):
    company = CompanyProfile.query.filter_by(user_id=user.id).first()
    if not company:
        return jsonify({'error': 'Company not found'}), 404
    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 6, type=int)
    query = PlacementDrive.query.filter_by(company_id=company.id).order_by(PlacementDrive.id.desc())
    return jsonify(paginated_response(query, page, per_page)), 200


@company_bp.route('/api/company/drives', methods=['POST'])
@role_required('company')
def create_drive(user):
    company = CompanyProfile.query.filter_by(user_id=user.id).first()
    if not company:
        return jsonify({'error': 'Company not found'}), 404
    if company.approval_status != 'approved':
        return jsonify({'error': 'Company must be approved by admin before creating drives'}), 403

    data = request.json
    if not data:
        return jsonify({'error': 'No data provided'}), 400

    drive_name = data.get('drive_name', '').strip()
    job_title = data.get('job_title', '').strip()
    if not drive_name or not job_title:
        return jsonify({'error': 'Drive name and job title are required'}), 400

    # validate drive fields
    if data.get('min_cgpa'):
        ok, err = validate_cgpa(data['min_cgpa'])
        if not ok:
            return jsonify({'error': err}), 400
    if data.get('eligible_year'):
        ok, err = validate_year(data['eligible_year'])
        if not ok:
            return jsonify({'error': err}), 400

    deadline = None
    if data.get('application_deadline'):
        try:
            deadline = datetime.fromisoformat(data['application_deadline'])
            if deadline < datetime.utcnow():
                return jsonify({'error': 'Deadline must be in the future'}), 400
        except ValueError:
            return jsonify({'error': 'Invalid deadline format'}), 400

    drive = PlacementDrive(
        company_id=company.id,
        drive_name=drive_name,
        job_title=job_title,
        job_description=data.get('job_description', ''),
        eligibility_branch=data.get('eligibility_branch', ''),
        min_cgpa=float(data.get('min_cgpa', 0)),
        eligible_year=int(data.get('eligible_year', 0)) if data.get('eligible_year') else None,
        application_deadline=deadline,
        location=data.get('location', ''),
        salary=data.get('salary', ''),
        job_type=data.get('job_type', 'Full-time'),
        status='pending',
    )
    db.session.add(drive)

    # Notify admin
    admin = User.query.filter_by(role='admin').first()
    if admin:
        notification = Notification(
            user_id=admin.id,
            message=f'New placement drive "{drive_name}" by {company.company_name} awaiting approval.',
            channel='in-app', is_sent=True,
        )
        db.session.add(notification)

    db.session.commit()
    cache_delete('admin_stats')
    return jsonify({'message': 'Drive created. Awaiting admin approval.', 'drive': drive.to_dict()}), 201


@company_bp.route('/api/company/drives/<int:id>', methods=['PUT'])
@role_required('company')
def update_drive(user, id):
    company = CompanyProfile.query.filter_by(user_id=user.id).first()
    drive = PlacementDrive.query.get_or_404(id)
    if drive.company_id != company.id:
        return jsonify({'error': 'Unauthorized'}), 403
    if drive.status in ('closed', 'rejected'):
        return jsonify({'error': 'Cannot edit a closed or rejected drive'}), 400

    data = request.json
    if data.get('drive_name'):
        drive.drive_name = data['drive_name']
    if data.get('job_title'):
        drive.job_title = data['job_title']
    if data.get('job_description'):
        drive.job_description = data['job_description']
    if data.get('eligibility_branch'):
        drive.eligibility_branch = data['eligibility_branch']
    if 'min_cgpa' in data:
        drive.min_cgpa = float(data['min_cgpa'])
    if data.get('eligible_year'):
        drive.eligible_year = int(data['eligible_year'])
    if data.get('application_deadline'):
        try:
            drive.application_deadline = datetime.fromisoformat(data['application_deadline'])
        except ValueError:
            pass
    if data.get('location'):
        drive.location = data['location']
    if data.get('salary'):
        drive.salary = data['salary']
    if data.get('job_type'):
        drive.job_type = data['job_type']

    db.session.commit()
    cache_delete('approved_drives')
    return jsonify({'message': 'Drive updated', 'drive': drive.to_dict()}), 200


@company_bp.route('/api/company/drives/<int:id>', methods=['DELETE'])
@role_required('company')
def delete_drive(user, id):
    company = CompanyProfile.query.filter_by(user_id=user.id).first()
    drive = PlacementDrive.query.get_or_404(id)
    if drive.company_id != company.id:
        return jsonify({'error': 'Unauthorized'}), 403
    if drive.status == 'approved' and drive.applications.count() > 0:
        return jsonify({'error': 'Cannot delete drive with existing applications'}), 400

    db.session.delete(drive)
    db.session.commit()
    cache_delete('admin_stats')
    cache_delete('approved_drives')
    return jsonify({'message': 'Drive deleted'}), 200


# application management — paginated
@company_bp.route('/api/company/drives/<int:id>/applications', methods=['GET'])
@role_required('company')
def drive_applications(user, id):
    company = CompanyProfile.query.filter_by(user_id=user.id).first()
    drive = PlacementDrive.query.get_or_404(id)
    if drive.company_id != company.id:
        return jsonify({'error': 'Unauthorized'}), 403
    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 6, type=int)
    query = Application.query.filter_by(drive_id=id).order_by(Application.application_date.desc())
    return jsonify(paginated_response(query, page, per_page)), 200


@company_bp.route('/api/company/applications/<int:id>/status', methods=['PUT'])
@role_required('company')
def update_application_status(user, id):
    app = Application.query.get_or_404(id)
    company = CompanyProfile.query.filter_by(user_id=user.id).first()
    drive = PlacementDrive.query.get(app.drive_id)

    if not drive or drive.company_id != company.id:
        return jsonify({'error': 'Unauthorized'}), 403

    data = request.json
    new_status = data.get('status', '').strip()
    if new_status not in ('applied', 'shortlisted', 'selected', 'rejected'):
        return jsonify({'error': 'Invalid status'}), 400

    app.status = new_status
    app.remarks = data.get('remarks', app.remarks)

    # If selected, create placement history
    if new_status == 'selected':
        from models import PlacementHistory
        history = PlacementHistory(
            student_id=app.student_id,
            company_name=drive.company.company_name,
            job_title=drive.job_title,
            selection_date=datetime.utcnow(),
            salary=drive.salary,
            status='selected',
        )
        db.session.add(history)

    # Notify student
    notification = Notification(
        user_id=app.student.user_id,
        message=f'Your application for "{drive.drive_name}" has been updated to: {new_status}.',
        channel='in-app', is_sent=True,
    )
    db.session.add(notification)
    db.session.commit()
    return jsonify({'message': 'Application status updated', 'application': app.to_dict()}), 200


# schedule interview
@company_bp.route('/api/company/applications/<int:id>/schedule-interview', methods=['POST'])
@role_required('company')
def schedule_interview(user, id):
    app = Application.query.get_or_404(id)
    company = CompanyProfile.query.filter_by(user_id=user.id).first()
    drive = PlacementDrive.query.get(app.drive_id)

    if not drive or drive.company_id != company.id:
        return jsonify({'error': 'Unauthorized'}), 403

    data = request.json
    interview_date = None
    if data.get('interview_date'):
        try:
            interview_date = datetime.fromisoformat(data['interview_date'])
        except ValueError:
            return jsonify({'error': 'Invalid date format'}), 400

    interview = Interview(
        application_id=app.id,
        interview_date=interview_date,
        mode=data.get('mode', 'Online'),
        venue=data.get('venue', ''),
        result='pending',
    )
    db.session.add(interview)

    app.status = 'shortlisted'
    app.interview_type = data.get('mode', 'Online')

    notification = Notification(
        user_id=app.student.user_id,
        message=f'Interview scheduled for "{drive.drive_name}" on {interview_date.strftime("%Y-%m-%d %H:%M") if interview_date else "TBD"}. Mode: {data.get("mode", "Online")}.',
        channel='in-app', is_sent=True,
    )
    db.session.add(notification)
    db.session.commit()
    return jsonify({'message': 'Interview scheduled', 'interview': interview.to_dict()}), 201


# update interview result
@company_bp.route('/api/company/applications/<int:id>/interview-result', methods=['PUT'])
@role_required('company')
def update_interview_result(user, id):
    app = Application.query.get_or_404(id)
    company = CompanyProfile.query.filter_by(user_id=user.id).first()
    drive = PlacementDrive.query.get(app.drive_id)

    if not drive or drive.company_id != company.id:
        return jsonify({'error': 'Unauthorized'}), 403

    # Get the most recent interview for this application
    interview = Interview.query.filter_by(application_id=app.id).order_by(Interview.id.desc()).first()
    if not interview:
        return jsonify({'error': 'No interview found for this application'}), 404

    data = request.get_json(silent=True)
    if not data or data.get('result') not in ('passed', 'failed'):
        return jsonify({'error': 'Result must be "passed" or "failed"'}), 400

    interview.result = data['result']

    # Notify student
    notification = Notification(
        user_id=app.student.user_id,
        message=f'Your interview for "{drive.drive_name}" result: {data["result"].upper()}.',
        channel='in-app', is_sent=True,
    )
    db.session.add(notification)
    db.session.commit()
    return jsonify({'message': 'Interview result updated', 'interview': interview.to_dict()}), 200


# drive interviews — paginated (manual list pagination)
@company_bp.route('/api/company/drives/<int:id>/interviews', methods=['GET'])
@role_required('company')
def drive_interviews(user, id):
    company = CompanyProfile.query.filter_by(user_id=user.id).first()
    drive = PlacementDrive.query.get_or_404(id)
    if drive.company_id != company.id:
        return jsonify({'error': 'Unauthorized'}), 403
    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 6, type=int)
    apps = Application.query.filter_by(drive_id=id).all()
    result = []
    for app in apps:
        for interview in app.interviews.all():
            result.append({
                **interview.to_dict(),
                'student_name': app.student.full_name if app.student else None,
                'student_email': app.student.user.email if app.student and app.student.user else None,
                'drive_name': drive.drive_name,
            })
    # manual pagination on list
    total = len(result)
    start = (page - 1) * per_page
    end = start + per_page
    paged = result[start:end]
    return jsonify({
        'items': paged,
        'total': total,
        'pages': (total + per_page - 1) // per_page if total else 1,
        'page': page,
        'per_page': per_page,
        'has_next': end < total,
        'has_prev': start > 0
    }), 200

