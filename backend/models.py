from flask_sqlalchemy import SQLAlchemy
from datetime import datetime

db = SQLAlchemy()


class User(db.Model):
    __tablename__ = 'users'
    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(256), nullable=False)
    role = db.Column(db.String(20), nullable=False)  # admin, company, student
    is_active = db.Column(db.Boolean, default=True)
    is_blacklisted = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    last_login = db.Column(db.DateTime)

    student_profile = db.relationship('StudentProfile', backref='user', uselist=False, cascade='all, delete-orphan')
    company_profile = db.relationship('CompanyProfile', backref='user', uselist=False, cascade='all, delete-orphan')
    notifications = db.relationship('Notification', backref='user', lazy='dynamic', cascade='all, delete-orphan')
    async_jobs = db.relationship('AsyncJob', backref='user', lazy='dynamic', cascade='all, delete-orphan')

    def to_dict(self):
        return {
            'id': self.id,
            'email': self.email,
            'role': self.role,
            'is_active': self.is_active,
            'is_blacklisted': self.is_blacklisted,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'last_login': self.last_login.isoformat() if self.last_login else None,
        }


class StudentProfile(db.Model):
    __tablename__ = 'student_profiles'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False, unique=True)
    full_name = db.Column(db.String(100), nullable=False)
    department = db.Column(db.String(50))
    cgpa = db.Column(db.Float, default=0.0)
    graduation_year = db.Column(db.Integer)
    resume_path = db.Column(db.String(256))
    phone = db.Column(db.String(15))
    bio = db.Column(db.Text)

    applications = db.relationship('Application', backref='student', lazy='dynamic', cascade='all, delete-orphan')
    placement_history = db.relationship('PlacementHistory', backref='student', lazy='dynamic', cascade='all, delete-orphan')
    skills = db.relationship('Skill', backref='student', lazy='dynamic', cascade='all, delete-orphan')

    def to_dict(self):
        return {
            'id': self.id,
            'user_id': self.user_id,
            'full_name': self.full_name,
            'department': self.department,
            'cgpa': self.cgpa,
            'graduation_year': self.graduation_year,
            'resume_path': self.resume_path,
            'phone': self.phone,
            'bio': self.bio,
            'email': self.user.email if self.user else None,
            'is_active': self.user.is_active if self.user else None,
            'is_blacklisted': self.user.is_blacklisted if self.user else None,
            'skills': [s.skill_name for s in self.skills.all()] if self.skills else [],
        }


class CompanyProfile(db.Model):
    __tablename__ = 'company_profiles'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False, unique=True)
    company_name = db.Column(db.String(150), nullable=False)
    hr_name = db.Column(db.String(100))
    hr_email = db.Column(db.String(120))
    hr_phone = db.Column(db.String(15))
    website = db.Column(db.String(256))
    description = db.Column(db.Text)
    industry = db.Column(db.String(100))
    company_size = db.Column(db.String(50))
    approval_status = db.Column(db.String(20), default='pending')  # pending, approved, rejected

    placement_drives = db.relationship('PlacementDrive', backref='company', lazy='dynamic', cascade='all, delete-orphan')

    def to_dict(self):
        return {
            'id': self.id,
            'user_id': self.user_id,
            'company_name': self.company_name,
            'hr_name': self.hr_name,
            'hr_email': self.hr_email,
            'hr_phone': self.hr_phone,
            'website': self.website,
            'description': self.description,
            'industry': self.industry,
            'company_size': self.company_size,
            'approval_status': self.approval_status,
            'email': self.user.email if self.user else None,
            'is_active': self.user.is_active if self.user else None,
            'is_blacklisted': self.user.is_blacklisted if self.user else None,
        }


class PlacementDrive(db.Model):
    __tablename__ = 'placement_drives'
    id = db.Column(db.Integer, primary_key=True)
    company_id = db.Column(db.Integer, db.ForeignKey('company_profiles.id'), nullable=False)
    drive_name = db.Column(db.String(200), nullable=False)
    job_title = db.Column(db.String(150), nullable=False)
    job_description = db.Column(db.Text)
    eligibility_branch = db.Column(db.String(200))  # comma separated
    min_cgpa = db.Column(db.Float, default=0.0)
    eligible_year = db.Column(db.Integer)
    application_deadline = db.Column(db.DateTime)
    location = db.Column(db.String(100))
    salary = db.Column(db.String(100))
    job_type = db.Column(db.String(50))  # Full-time / Internship
    status = db.Column(db.String(20), default='pending')  # pending, approved, rejected, closed
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    applications = db.relationship('Application', backref='drive', lazy='dynamic', cascade='all, delete-orphan')
    approvals = db.relationship('DriveApproval', backref='drive', lazy='dynamic', cascade='all, delete-orphan')

    def to_dict(self):
        return {
            'id': self.id,
            'company_id': self.company_id,
            'company_name': self.company.company_name if self.company else None,
            'drive_name': self.drive_name,
            'job_title': self.job_title,
            'job_description': self.job_description,
            'eligibility_branch': self.eligibility_branch,
            'min_cgpa': self.min_cgpa,
            'eligible_year': self.eligible_year,
            'application_deadline': self.application_deadline.isoformat() if self.application_deadline else None,
            'location': self.location,
            'salary': self.salary,
            'job_type': self.job_type,
            'status': self.status,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'application_count': self.applications.count() if self.applications else 0,
        }


class Application(db.Model):
    __tablename__ = 'applications'
    id = db.Column(db.Integer, primary_key=True)
    student_id = db.Column(db.Integer, db.ForeignKey('student_profiles.id'), nullable=False)
    drive_id = db.Column(db.Integer, db.ForeignKey('placement_drives.id'), nullable=False)
    application_date = db.Column(db.DateTime, default=datetime.utcnow)
    status = db.Column(db.String(20), default='applied')  # applied, shortlisted, selected, rejected, withdrawn
    interview_type = db.Column(db.String(50))
    remarks = db.Column(db.Text)
    cover_letter = db.Column(db.Text)

    interviews = db.relationship('Interview', backref='application', lazy='dynamic', cascade='all, delete-orphan')

    __table_args__ = (db.UniqueConstraint('student_id', 'drive_id', name='unique_student_drive'),)

    def to_dict(self):
        return {
            'id': self.id,
            'student_id': self.student_id,
            'drive_id': self.drive_id,
            'student_name': self.student.full_name if self.student else None,
            'student_email': self.student.user.email if self.student and self.student.user else None,
            'student_cgpa': self.student.cgpa if self.student else None,
            'student_department': self.student.department if self.student else None,
            'drive_name': self.drive.drive_name if self.drive else None,
            'company_name': self.drive.company.company_name if self.drive and self.drive.company else None,
            'job_title': self.drive.job_title if self.drive else None,
            'application_date': self.application_date.isoformat() if self.application_date else None,
            'status': self.status,
            'interview_type': self.interview_type,
            'remarks': self.remarks,
            'cover_letter': self.cover_letter,
        }


class DriveApproval(db.Model):
    __tablename__ = 'drive_approvals'
    id = db.Column(db.Integer, primary_key=True)
    drive_id = db.Column(db.Integer, db.ForeignKey('placement_drives.id'), nullable=False)
    admin_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    action = db.Column(db.String(20), nullable=False)  # approved, rejected
    remarks = db.Column(db.Text)
    action_date = db.Column(db.DateTime, default=datetime.utcnow)

    def to_dict(self):
        return {
            'id': self.id,
            'drive_id': self.drive_id,
            'admin_id': self.admin_id,
            'action': self.action,
            'remarks': self.remarks,
            'action_date': self.action_date.isoformat() if self.action_date else None,
        }


class Interview(db.Model):
    __tablename__ = 'interviews'
    id = db.Column(db.Integer, primary_key=True)
    application_id = db.Column(db.Integer, db.ForeignKey('applications.id'), nullable=False)
    interview_date = db.Column(db.DateTime)
    mode = db.Column(db.String(50))  # Online / Offline
    venue = db.Column(db.String(200))
    result = db.Column(db.String(20))  # pending, passed, failed

    def to_dict(self):
        return {
            'id': self.id,
            'application_id': self.application_id,
            'interview_date': self.interview_date.isoformat() if self.interview_date else None,
            'mode': self.mode,
            'venue': self.venue,
            'result': self.result,
        }


class PlacementHistory(db.Model):
    __tablename__ = 'placement_history'
    id = db.Column(db.Integer, primary_key=True)
    student_id = db.Column(db.Integer, db.ForeignKey('student_profiles.id'), nullable=False)
    company_name = db.Column(db.String(150))
    job_title = db.Column(db.String(150))
    selection_date = db.Column(db.DateTime)
    salary = db.Column(db.String(100))
    status = db.Column(db.String(20))  # selected, joined, declined

    def to_dict(self):
        return {
            'id': self.id,
            'student_id': self.student_id,
            'company_name': self.company_name,
            'job_title': self.job_title,
            'selection_date': self.selection_date.isoformat() if self.selection_date else None,
            'salary': self.salary,
            'status': self.status,
        }


class MonthlyReport(db.Model):
    __tablename__ = 'monthly_reports'
    id = db.Column(db.Integer, primary_key=True)
    month = db.Column(db.String(20), nullable=False)
    total_drives = db.Column(db.Integer, default=0)
    total_applications = db.Column(db.Integer, default=0)
    total_selected = db.Column(db.Integer, default=0)
    report_path = db.Column(db.String(256))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def to_dict(self):
        return {
            'id': self.id,
            'month': self.month,
            'total_drives': self.total_drives,
            'total_applications': self.total_applications,
            'total_selected': self.total_selected,
            'report_path': self.report_path,
            'created_at': self.created_at.isoformat() if self.created_at else None,
        }


class Notification(db.Model):
    __tablename__ = 'notifications'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    message = db.Column(db.Text, nullable=False)
    channel = db.Column(db.String(20), default='in-app')  # in-app, email, webhook
    is_sent = db.Column(db.Boolean, default=False)
    is_read = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def to_dict(self):
        return {
            'id': self.id,
            'user_id': self.user_id,
            'message': self.message,
            'channel': self.channel,
            'is_sent': self.is_sent,
            'is_read': self.is_read,
            'created_at': self.created_at.isoformat() if self.created_at else None,
        }


class AsyncJob(db.Model):
    __tablename__ = 'async_jobs'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    job_type = db.Column(db.String(50), nullable=False)
    status = db.Column(db.String(20), default='pending')  # pending, running, completed, failed
    file_path = db.Column(db.String(256))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    completed_at = db.Column(db.DateTime)

    def to_dict(self):
        return {
            'id': self.id,
            'user_id': self.user_id,
            'job_type': self.job_type,
            'status': self.status,
            'file_path': self.file_path,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'completed_at': self.completed_at.isoformat() if self.completed_at else None,
        }


class Skill(db.Model):
    __tablename__ = 'skills'
    id = db.Column(db.Integer, primary_key=True)
    student_id = db.Column(db.Integer, db.ForeignKey('student_profiles.id'), nullable=False)
    skill_name = db.Column(db.String(100), nullable=False)

    def to_dict(self):
        return {
            'id': self.id,
            'student_id': self.student_id,
            'skill_name': self.skill_name,
        }
