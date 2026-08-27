from flask import Blueprint, request, jsonify, send_file, current_app
from werkzeug.security import generate_password_hash
from werkzeug.utils import secure_filename
from models import db, User, StudentProfile, PlacementDrive, Application, Notification, AsyncJob, Skill, PlacementHistory
from auth import login_required, role_required
from cache import cache_get, cache_set, cache_delete
from pagination import paginated_response
from datetime import datetime
import os
from validators import validate_email, validate_password, validate_phone, validate_cgpa, validate_year, validate_name

student_bp = Blueprint('student', __name__)

ALLOWED_EXTENSIONS = {'pdf'}


def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS


# register student
@student_bp.route('/api/students/register', methods=['POST'])
def register_student():
    data = request.json
    if not data:
        return jsonify({'error': 'No data provided'}), 400

    email = data.get('email', '').strip()
    password = data.get('password', '').strip()
    full_name = data.get('full_name', '').strip()

    if not all([email, password, full_name]):
        return jsonify({'error': 'Email, password, and full name are required'}), 400

    # validate inputs
    if not validate_email(email):
        return jsonify({'error': 'Please enter a valid email address'}), 400
    ok, err = validate_password(password)
    if not ok:
        return jsonify({'error': err}), 400
    ok, err = validate_name(full_name, 'Full name')
    if not ok:
        return jsonify({'error': err}), 400
    ok, err = validate_phone(data.get('phone', ''))
    if not ok:
        return jsonify({'error': err}), 400
    if data.get('cgpa'):
        ok, err = validate_cgpa(data['cgpa'])
        if not ok:
            return jsonify({'error': err}), 400
    if data.get('graduation_year'):
        ok, err = validate_year(data['graduation_year'])
        if not ok:
            return jsonify({'error': err}), 400

    if User.query.filter_by(email=email).first():
        return jsonify({'error': 'Email already registered'}), 409

    user = User(
        email=email,
        password_hash=generate_password_hash(password),
        role='student',
    )
    db.session.add(user)
    db.session.flush()

    student = StudentProfile(
        user_id=user.id,
        full_name=full_name,
        department=data.get('department', ''),
        cgpa=float(data.get('cgpa', 0)),
        graduation_year=int(data.get('graduation_year', 0)) if data.get('graduation_year') else None,
        phone=data.get('phone', ''),
        bio=data.get('bio', ''),
    )
    db.session.add(student)

    # Add skills
    skills = data.get('skills', [])
    for s in skills:
        skill = Skill(student_id=student.id, skill_name=s.strip())
        db.session.add(skill)

    db.session.commit()
    cache_delete('admin_stats')
    return jsonify({'message': 'Student registered successfully', 'student': student.to_dict()}), 201


# student profile
@student_bp.route('/api/students/profile', methods=['GET'])
@role_required('student')
def get_student_profile(user):
    student = StudentProfile.query.filter_by(user_id=user.id).first()
    if not student:
        return jsonify({'error': 'Student profile not found'}), 404
    return jsonify(student.to_dict()), 200


@student_bp.route('/api/students/profile', methods=['PUT'])
@role_required('student')
def update_student_profile(user):
    student = StudentProfile.query.filter_by(user_id=user.id).first()
    if not student:
        return jsonify({'error': 'Student profile not found'}), 404

    data = request.json
    if data.get('full_name'):
        ok, err = validate_name(data['full_name'], 'Full name')
        if not ok:
            return jsonify({'error': err}), 400
        student.full_name = data['full_name']
    if data.get('department'):
        student.department = data['department']
    if 'cgpa' in data:
        ok, err = validate_cgpa(data['cgpa'])
        if not ok:
            return jsonify({'error': err}), 400
        student.cgpa = float(data['cgpa'])
    if data.get('graduation_year'):
        ok, err = validate_year(data['graduation_year'])
        if not ok:
            return jsonify({'error': err}), 400
        student.graduation_year = int(data['graduation_year'])
    if data.get('phone'):
        ok, err = validate_phone(data['phone'])
        if not ok:
            return jsonify({'error': err}), 400
        student.phone = data['phone']
    if data.get('bio'):
        student.bio = data['bio']

    # Update skills
    if 'skills' in data:
        Skill.query.filter_by(student_id=student.id).delete()
        for s in data['skills']:
            skill = Skill(student_id=student.id, skill_name=s.strip())
            db.session.add(skill)

    db.session.commit()
    return jsonify({'message': 'Profile updated', 'student': student.to_dict()}), 200


# upload resume
@student_bp.route('/api/students/upload-resume', methods=['POST'])
@role_required('student')
def upload_resume(user):
    student = StudentProfile.query.filter_by(user_id=user.id).first()
    if not student:
        return jsonify({'error': 'Student profile not found'}), 404

    if 'resume' not in request.files:
        return jsonify({'error': 'No file provided'}), 400

    file = request.files['resume']
    if file.filename == '':
        return jsonify({'error': 'No file selected'}), 400

    if not allowed_file(file.filename):
        return jsonify({'error': 'Only PDF files allowed'}), 400

    upload_dir = os.path.join(current_app.config.get('UPLOAD_FOLDER', 'uploads'), 'resumes')
    os.makedirs(upload_dir, exist_ok=True)
    filename = secure_filename(f"resume_{student.id}_{file.filename}")
    filepath = os.path.join(upload_dir, filename)
    file.save(filepath)

    # Store relative path for portability across deployments (ephemeral FS -> absolute paths break)
    try:
        rel_path = os.path.relpath(filepath, start=os.getcwd())
    except ValueError:
        rel_path = filepath
    # Fallback: store as uploads/resumes/<filename> so it works regardless of cwd
    if os.path.isabs(rel_path) and '..' in rel_path:
        rel_path = os.path.join('uploads', 'resumes', filename)
    student.resume_path = rel_path
    db.session.commit()
    return jsonify({'message': 'Resume uploaded successfully', 'resume_path': rel_path}), 200


# browse drives (cached) — paginated: ?search&branch&page&per_page
@student_bp.route('/api/student/drives', methods=['GET'])
@role_required('student')
def browse_drives(user):
    search = request.args.get('search', '').strip()
    branch = request.args.get('branch', '').strip()
    min_cgpa = request.args.get('min_cgpa', None, type=float)
    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 6, type=int)

    # cache only first page without filters (common case)
    if not search and not branch and min_cgpa is None and page == 1 and per_page == 6:
        cached = cache_get('approved_drives_paginated')
        if cached:
            return jsonify(cached), 200

    query = PlacementDrive.query.filter_by(status='approved')

    if search:
        query = query.filter(
            (PlacementDrive.drive_name.ilike(f'%{search}%')) |
            (PlacementDrive.job_title.ilike(f'%{search}%')) |
            (PlacementDrive.location.ilike(f'%{search}%'))
        )
    if branch:
        query = query.filter(PlacementDrive.eligibility_branch.ilike(f'%{branch}%'))

    query = query.order_by(PlacementDrive.application_deadline.asc())
    data = paginated_response(query, page, per_page)

    if not search and not branch and min_cgpa is None and page == 1 and per_page == 6:
        cache_set('approved_drives_paginated', data, ttl=600)

    return jsonify(data), 200


@student_bp.route('/api/student/drives/<int:id>', methods=['GET'])
@role_required('student')
def drive_detail(user, id):
    drive = PlacementDrive.query.get_or_404(id)
    student = StudentProfile.query.filter_by(user_id=user.id).first()

    result = drive.to_dict()
    # Check if already applied
    if student:
        existing = Application.query.filter_by(student_id=student.id, drive_id=id).first()
        result['already_applied'] = existing is not None
        result['application'] = existing.to_dict() if existing else None
    return jsonify(result), 200


# apply for drive
@student_bp.route('/api/student/apply/<int:drive_id>', methods=['POST'])
@role_required('student')
def apply_for_drive(user, drive_id):
    student = StudentProfile.query.filter_by(user_id=user.id).first()
    if not student:
        return jsonify({'error': 'Student profile not found'}), 404

    drive = PlacementDrive.query.get_or_404(drive_id)

    if drive.status != 'approved':
        return jsonify({'error': 'Drive is not currently accepting applications'}), 400

    if drive.application_deadline and drive.application_deadline < datetime.utcnow():
        return jsonify({'error': 'Application deadline has passed'}), 400

    # eligibility
    if drive.min_cgpa and student.cgpa < drive.min_cgpa:
        return jsonify({'error': f'Minimum CGPA requirement is {drive.min_cgpa}. Your CGPA is {student.cgpa}.'}), 400

    if drive.eligible_year and student.graduation_year and student.graduation_year != drive.eligible_year:
        return jsonify({'error': f'This drive is for {drive.eligible_year} graduation year only.'}), 400

    if drive.eligibility_branch and student.department:
        eligible_branches = [b.strip().lower() for b in drive.eligibility_branch.split(',')]
        if eligible_branches and 'all' not in eligible_branches:
            if student.department.lower() not in eligible_branches:
                return jsonify({'error': f'Your department "{student.department}" is not eligible for this drive.'}), 400

    # check if already applied
    existing = Application.query.filter_by(student_id=student.id, drive_id=drive_id).first()
    if existing:
        return jsonify({'error': 'You have already applied for this drive'}), 409

    data = request.json or {}
    application = Application(
        student_id=student.id,
        drive_id=drive_id,
        status='applied',
        cover_letter=data.get('cover_letter', ''),
    )
    db.session.add(application)

    # notify
    notification = Notification(
        user_id=drive.company.user_id,
        message=f'{student.full_name} applied for "{drive.drive_name}".',
        channel='in-app', is_sent=True,
    )
    db.session.add(notification)
    db.session.commit()

    return jsonify({'message': 'Application submitted successfully', 'application': application.to_dict()}), 201


# my applications — paginated
@student_bp.route('/api/student/applications', methods=['GET'])
@role_required('student')
def my_applications(user):
    student = StudentProfile.query.filter_by(user_id=user.id).first()
    if not student:
        return jsonify({'error': 'Student profile not found'}), 404
    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 6, type=int)
    query = Application.query.filter_by(student_id=student.id).order_by(Application.application_date.desc())
    return jsonify(paginated_response(query, page, per_page)), 200


@student_bp.route('/api/student/applications/<int:id>/withdraw', methods=['PUT'])
@role_required('student')
def withdraw_application(user, id):
    student = StudentProfile.query.filter_by(user_id=user.id).first()
    app = Application.query.get_or_404(id)

    if app.student_id != student.id:
        return jsonify({'error': 'Unauthorized'}), 403

    if app.status in ('selected', 'rejected'):
        return jsonify({'error': 'Cannot withdraw a finalized application'}), 400

    app.status = 'withdrawn'
    db.session.commit()
    return jsonify({'message': 'Application withdrawn', 'application': app.to_dict()}), 200


# placement history — paginated
@student_bp.route('/api/student/history', methods=['GET'])
@role_required('student')
def placement_history(user):
    student = StudentProfile.query.filter_by(user_id=user.id).first()
    if not student:
        return jsonify({'error': 'Student profile not found'}), 404
    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 6, type=int)
    query = PlacementHistory.query.filter_by(student_id=student.id).order_by(PlacementHistory.selection_date.desc())
    return jsonify(paginated_response(query, page, per_page)), 200


# my interviews — paginated
@student_bp.route('/api/student/interviews', methods=['GET'])
@role_required('student')
def my_interviews(user):
    student = StudentProfile.query.filter_by(user_id=user.id).first()
    if not student:
        return jsonify({'error': 'Student profile not found'}), 404
    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 6, type=int)
    from models import Interview
    apps = Application.query.filter_by(student_id=student.id).all()
    interviews = []
    for app in apps:
        for interview in app.interviews.all():
            interviews.append({
                **interview.to_dict(),
                'drive_name': app.drive.drive_name if app.drive else None,
                'company_name': app.drive.company.company_name if app.drive and app.drive.company else None,
                'job_title': app.drive.job_title if app.drive else None,
                'application_status': app.status,
            })
    interviews.sort(key=lambda x: x.get('interview_date') or '', reverse=True)
    total = len(interviews)
    start = (page - 1) * per_page
    end = start + per_page
    paged = interviews[start:end]
    return jsonify({
        'items': paged,
        'total': total,
        'pages': (total + per_page - 1) // per_page if total else 1,
        'page': page,
        'per_page': per_page,
        'has_next': end < total,
        'has_prev': start > 0
    }), 200


# export csv (async with sync fallback for single-web deploy)
@student_bp.route('/api/student/export-applications', methods=['POST'])
@role_required('student')
def export_applications(user):
    student = StudentProfile.query.filter_by(user_id=user.id).first()
    if not student:
        return jsonify({'error': 'Student profile not found'}), 404

    job = AsyncJob(
        user_id=user.id,
        job_type='export_applications_csv',
        status='pending',
    )
    db.session.add(job)
    db.session.commit()

    from tasks import export_applications_csv
    from cache import get_redis
    try:
        if get_redis() is None:
            raise RuntimeError("Redis unavailable — running sync")
        export_applications_csv.delay(user.id, student.id, job.id)
    except Exception as e:
        print(f"[!] Celery delay failed ({e}), falling back to sync CSV export")
        try:
            export_applications_csv(user.id, student.id, job.id)
        except Exception as se:
            print(f"[!] Sync CSV also failed: {se}")
    return jsonify({'message': 'Export job started', 'job_id': job.id}), 202


# download export
@student_bp.route('/api/student/download-export/<int:job_id>', methods=['GET'])
@role_required('student')
def download_export(user, job_id):
    job = AsyncJob.query.get_or_404(job_id)
    if job.user_id != user.id:
        return jsonify({'error': 'Unauthorized'}), 403
    if job.status != 'completed':
        return jsonify({'error': 'Export not ready yet', 'status': job.status}), 400
    if job.file_path and os.path.exists(job.file_path):
        return send_file(job.file_path, as_attachment=True, download_name='my_applications.csv')
    return jsonify({'error': 'Export file not found'}), 404


# ats resume check
@student_bp.route('/api/student/ats-check', methods=['POST'])
@role_required('student')
def ats_check(user):
    try:
        student = StudentProfile.query.filter_by(user_id=user.id).first()
        if not student:
            return jsonify({'error': 'Student profile not found'}), 404

        data = request.get_json(silent=True)
        drive_id = data.get('drive_id') if data else None
        if not drive_id:
            return jsonify({'error': 'drive_id is required'}), 400

        drive = PlacementDrive.query.get(drive_id)
        if not drive:
            return jsonify({'error': 'Drive not found'}), 404

        # build JD from drive info
        job_desc = f"Job Title: {drive.job_title or ''}\n"
        job_desc += f"Description: {drive.job_description or ''}\n"
        job_desc += f"Required Branch: {drive.eligibility_branch or 'All'}\n"
        job_desc += f"Min CGPA: {drive.min_cgpa or 'None'}"

        # get text from resume pdf — handle both absolute and relative paths for hosting portability
        resume_text = ""
        resume_path_to_check = None
        if student.resume_path:
            # Try stored path as-is, then relative to UPLOAD_FOLDER, then relative to BASE_DIR
            candidates = [student.resume_path]
            # If stored as relative like "uploads/resumes/file.pdf", resolve against cwd and BASE_DIR
            if not os.path.isabs(student.resume_path):
                candidates.append(os.path.join(current_app.config.get('UPLOAD_FOLDER', 'uploads'), os.path.basename(student.resume_path)))
                candidates.append(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', student.resume_path))
                candidates.append(os.path.abspath(student.resume_path))
            for cand in candidates:
                if cand and os.path.exists(cand):
                    resume_path_to_check = cand
                    break
        if resume_path_to_check:
            try:
                import PyPDF2
                with open(resume_path_to_check, 'rb') as f:
                    reader = PyPDF2.PdfReader(f)
                    for page in reader.pages:
                        resume_text += page.extract_text() or ''
            except Exception:
                resume_text = ""

        if not resume_text.strip():
            # fallback if no pdf
            resume_text = f"Name: {student.full_name}\n"
            resume_text += f"Department: {student.department or ''}\n"
            resume_text += f"CGPA: {student.cgpa or ''}\n"
            resume_text += f"Skills: {', '.join([s.skill_name for s in student.skills]) if student.skills else ''}\n"
            resume_text += f"Bio: {student.bio or ''}"

        # check cache first — avoids 20s HF sleep on repeat
        cache_key = f"ats:{student.id}:{drive_id}:{hash(resume_text[:100])}"
        cached = cache_get(cache_key)
        if cached:
            return jsonify({'result': cached, 'resume_preview': resume_text[:200] + '...', 'cached': True}), 200

        # call HF API with timeout guard
        from gradio_client import Client
        try:
            client = Client("parthjain/ResumeAnalyser")
            result = client.predict(resume_text, job_desc, api_name="/analyze_resume")
        except Exception as hf_e:
            # HF Space sleeping — return fallback analysis instead of 500 so recruiter sees result
            return jsonify({
                'result': f"ATS service temporarily unavailable (HF Space sleeping). Fallback — Resume preview matches JD branch {drive.eligibility_branch} min CGPA {drive.min_cgpa}. Raw error: {str(hf_e)[:100]}",
                'resume_preview': resume_text[:200] + '...',
                'fallback': True
            }), 200
        # cache 10 min
        cache_set(cache_key, result, ttl=600)
        return jsonify({'result': result, 'resume_preview': resume_text[:200] + '...'}), 200

    except Exception as e:
        return jsonify({'error': f'ATS check failed: {str(e)}. Please try again later.'}), 500


