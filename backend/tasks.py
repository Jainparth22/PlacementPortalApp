import csv
import datetime
import html
import io
import logging
import os

from sqlalchemy.exc import DBAPIError
from redis.exceptions import RedisError

from cache import once, invalidate
from events import notify, relay_outbox, purge_published
import sessions
from celery_worker import celery
from storage import get_storage
from models import db, User, StudentProfile, PlacementDrive, Application, MonthlyReport, Notification, AsyncJob

log = logging.getLogger(__name__)

# Errors worth retrying (network / DB / disk blips). Programming errors are NOT retried.
TRANSIENT_ERRORS = (DBAPIError, RedisError, ConnectionError, TimeoutError, OSError)
MAX_RETRIES = 3


def _now():
    return datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None)  # naive UTC (matches DB columns)


def _fail_or_retry(task, exc, job=None):
    """Retry transient errors with exponential backoff; otherwise mark the job failed.

    * Running under a worker  -> raise ``Retry`` (transient) or re-raise (permanent => DLQ via on_failure).
    * Called directly (sync fallback) -> never raise; return an error dict.
    """
    db.session.rollback()
    called_directly = getattr(task.request, 'called_directly', True)
    retries = getattr(task.request, 'retries', 0) or 0
    transient = isinstance(exc, TRANSIENT_ERRORS)

    if not called_directly and transient and retries < MAX_RETRIES:
        countdown = min(60 * (2 ** retries), 600)
        log.warning('task_retry', extra={'event': 'task_retry', 'task': task.name, 'attempt': retries + 1, 'countdown': countdown, 'error': str(exc)[:200]})
        raise task.retry(exc=exc, countdown=countdown)

    if job is not None:
        try:
            job = db.session.get(AsyncJob, job.id)
            job.status = 'failed'
            db.session.commit()
        except Exception:  # noqa: BLE001
            db.session.rollback()
    log.error('task_failed', extra={'event': 'task_failed', 'task': task.name, 'error': str(exc)[:300]}, exc_info=True)
    if not called_directly:
        raise exc          # -> Celery on_failure -> dead-letter queue
    return {'status': 'error', 'message': str(exc)}


def send_email(subject, recipients, html_body):
    """Send email via Flask-Mail — optional, skipped when MAIL credentials are not configured."""
    try:
        from flask import current_app
        if not current_app.config.get('MAIL_USERNAME') or not current_app.config.get('MAIL_PASSWORD'):
            log.info('email_skipped_no_credentials', extra={'event': 'email_skipped_no_credentials'})
            return False
        from app import mail
        from flask_mail import Message
        msg = Message(subject=subject, recipients=recipients, html=html_body)
        mail.send(msg)
        log.info('email_sent', extra={'event': 'email_sent', 'subject': subject, 'recipient_count': len(recipients)})
        return True
    except Exception as e:  # noqa: BLE001
        log.warning('email_failed', extra={'event': 'email_failed', 'error': str(e)[:200]})
        return False


def send_gchat_webhook(message):
    try:
        import requests
        from flask import current_app
        webhook_url = current_app.config.get('GCHAT_WEBHOOK_URL', '') or os.environ.get('GCHAT_WEBHOOK_URL', '')
        if webhook_url:
            requests.post(webhook_url, json={"text": message}, timeout=10)
            return True
    except Exception as e:  # noqa: BLE001
        log.warning('gchat_failed', extra={'event': 'gchat_failed', 'error': str(e)[:200]})
    return False


@celery.task(bind=True, name='tasks.send_daily_reminders', max_retries=MAX_RETRIES)
def send_daily_reminders(self):
    """Remind students about drives closing within 3 days.

    Idempotent: a student gets one reminder per drive (we look for the identical notification
    first), so the daily job - or a re-delivered/retried task - never duplicates messages.
    """
    try:
        now = _now()
        upcoming_deadline = now + datetime.timedelta(days=3)

        drives = PlacementDrive.query.filter(
            PlacementDrive.status == 'approved',
            PlacementDrive.application_deadline >= now,
            PlacementDrive.application_deadline <= upcoming_deadline
        ).all()
        if not drives:
            return {'status': 'success', 'reminders_sent': 0}

        students = StudentProfile.query.join(User).filter(
            User.is_active == True,  # noqa: E712
            User.is_blacklisted == False  # noqa: E712
        ).all()

        count = 0
        for student in students:
            reminder_drives = []
            for drive in drives:
                if Application.query.filter_by(student_id=student.id, drive_id=drive.id).first():
                    continue
                message = (f"Reminder: Application deadline for '{drive.drive_name}' at {drive.company.company_name} "
                           f"is on {drive.application_deadline.strftime('%Y-%m-%d')}. Apply before it's too late!")
                if Notification.query.filter_by(user_id=student.user_id, message=message).first():
                    continue   # already reminded
                notify(student.user_id, message, channel='email')
                reminder_drives.append(drive)
                count += 1

            if reminder_drives and student.user and student.user.email:
                drives_html = ''.join(
                    f"<li><strong>{html.escape(d.drive_name)}</strong> at {html.escape(d.company.company_name)} — "
                    f"Deadline: {d.application_deadline.strftime('%Y-%m-%d')}</li>"
                    for d in reminder_drives
                )
                email_body = f"""
                <html><body>
                <h2>Placement Portal - Upcoming Deadlines</h2>
                <p>Hi {html.escape(student.full_name)},</p>
                <p>The following placement drives have upcoming deadlines (within 3 days):</p>
                <ul>{drives_html}</ul>
                <p>Log in to the Placement Portal to apply before it's too late!</p>
                <p>Best regards,<br>Placement Portal Team</p>
                </body></html>
                """
                send_email("Placement Portal - Upcoming Application Deadlines", [student.user.email], email_body)
                drives_text = ', '.join(f"{d.drive_name} (deadline: {d.application_deadline.strftime('%Y-%m-%d')})" for d in reminder_drives)
                send_gchat_webhook(f"Reminder for {student.full_name}: Upcoming deadlines - {drives_text}")

        db.session.commit()
        relay_outbox()
        log.info('reminders_done', extra={'event': 'reminders_done', 'count': count})
        return {'status': 'success', 'reminders_sent': count}
    except Exception as e:  # noqa: BLE001
        return _fail_or_retry(self, e)


def _build_report_html(month_str, total_drives, total_applications, total_selected, now):
    return f"""
        <html>
        <head><title>Monthly Placement Report - {month_str}</title>
        <style>
            body {{ font-family: Arial, sans-serif; padding: 20px; }}
            h1 {{ color: #2c3e50; }}
            table {{ border-collapse: collapse; width: 100%; margin-top: 20px; }}
            th, td {{ border: 1px solid #ddd; padding: 12px; text-align: left; }}
            th {{ background-color: #3498db; color: white; }}
            .stat {{ font-size: 24px; font-weight: bold; color: #2c3e50; }}
        </style>
        </head>
        <body>
            <h1>Monthly Placement Report - {month_str}</h1>
            <table>
                <tr><th>Metric</th><th>Count</th></tr>
                <tr><td>Total Placement Drives</td><td class="stat">{total_drives}</td></tr>
                <tr><td>Total Applications</td><td class="stat">{total_applications}</td></tr>
                <tr><td>Students Selected</td><td class="stat">{total_selected}</td></tr>
            </table>
            <p><em>Report generated on {now.strftime('%Y-%m-%d %H:%M')}</em></p>
        </body>
        </html>
        """


@celery.task(bind=True, name='tasks.generate_monthly_report', max_retries=MAX_RETRIES)
def generate_monthly_report(self, job_id=None):
    """Generate the monthly report (PDF + HTML) and notify/email the admin.

    Idempotent: re-running for the same month updates the existing ``MonthlyReport`` row, a job that is
    already completed is a no-op, and the admin e-mail / chat summary goes out at most once per day per month.
    """
    job = None
    try:
        if job_id:
            job = db.session.get(AsyncJob, job_id)
            if job and job.status == 'completed':
                return {'status': 'success', 'report_path': job.file_path, 'idempotent': True}
            if job:
                job.status = 'running'
                db.session.commit()

        now = _now()
        month_str = now.strftime('%Y-%m')
        first_day = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        last_day = first_day.replace(year=now.year + 1, month=1) if now.month == 12 else first_day.replace(month=now.month + 1)

        total_drives = PlacementDrive.query.filter(PlacementDrive.created_at >= first_day, PlacementDrive.created_at < last_day).count()
        total_applications = Application.query.filter(Application.application_date >= first_day, Application.application_date < last_day).count()
        total_selected = Application.query.filter(
            Application.application_date >= first_day, Application.application_date < last_day, Application.status == 'selected'
        ).count()

        report_html = _build_report_html(month_str, total_drives, total_applications, total_selected, now)

        storage = get_storage()
        report_key = f'reports/report_{month_str}.html'
        storage.put_bytes(report_key, report_html.encode('utf-8'), 'text/html')
        report_path = report_key

        try:
            from xhtml2pdf import pisa
            pdf_buffer = io.BytesIO()
            result = pisa.CreatePDF(report_html, dest=pdf_buffer)
            if result.err:
                raise RuntimeError(f'xhtml2pdf reported {result.err} error(s)')
            storage.put_bytes(f'reports/report_{month_str}.pdf', pdf_buffer.getvalue(), 'application/pdf')
        except Exception as pdf_err:  # noqa: BLE001
            log.warning('pdf_generation_failed', extra={'event': 'pdf_generation_failed', 'error': str(pdf_err)[:200]})

        report = MonthlyReport.query.filter_by(month=month_str).first()
        if report is None:
            report = MonthlyReport(month=month_str)
            db.session.add(report)
        report.total_drives = total_drives
        report.total_applications = total_applications
        report.total_selected = total_selected
        report.report_path = report_path
        report.created_at = now

        admin = User.query.filter_by(role='admin').first()
        if admin:
            notify(admin.id,
                   f"Monthly placement report for {month_str} is ready. Drives: {total_drives}, Applications: {total_applications}, Selected: {total_selected}",
                   channel='email')
            # Side effects that must not repeat on retry / double click: once per month per day.
            if once(f"report-mail:{month_str}:{now.strftime('%Y-%m-%d')}", ttl=86400):
                send_email(f"Placement Portal - Monthly Report {month_str}", [admin.email], report_html)
                send_gchat_webhook(f"Monthly Report {month_str}: {total_drives} drives, {total_applications} applications, {total_selected} selected")

        db.session.commit()

        if job:
            job.status = 'completed'
            job.file_path = report_path
            job.completed_at = now
            db.session.commit()

        invalidate('stats')
        relay_outbox()
        log.info('report_generated', extra={'event': 'report_generated', 'month': month_str, 'job_id': job_id})
        return {'status': 'success', 'report_path': report_path}
    except Exception as e:  # noqa: BLE001
        return _fail_or_retry(self, e, job)


@celery.task(bind=True, name='tasks.export_applications_csv', max_retries=MAX_RETRIES)
def export_applications_csv(self, user_id, student_id, job_id):
    """Export a student's applications to CSV. Idempotent per job (completed job => no-op)."""
    job = None
    try:
        job = db.session.get(AsyncJob, job_id)
        if job and job.status == 'completed':
            return {'status': 'success', 'file_path': job.file_path, 'idempotent': True}
        if job:
            job.status = 'running'
            db.session.commit()

        applications = Application.query.filter_by(student_id=student_id).all()

        # deterministic key per job => a retry overwrites the same object instead of leaving duplicates
        file_path = f'exports/applications_{student_id}_job{job_id}.csv'
        buffer = io.StringIO(newline='')
        writer = csv.writer(buffer)
        writer.writerow(['Student ID', 'Company Name', 'Drive Title', 'Application Status', 'Application Date', 'Remarks'])
        for app in applications:
            writer.writerow([
                student_id,
                app.drive.company.company_name if app.drive and app.drive.company else 'N/A',
                app.drive.drive_name if app.drive else 'N/A',
                app.status,
                app.application_date.strftime('%Y-%m-%d') if app.application_date else 'N/A',
                app.remarks or '',
            ])
        get_storage().put_bytes(file_path, buffer.getvalue().encode('utf-8'), 'text/csv')

        if job:
            job.status = 'completed'
            job.file_path = file_path
            job.completed_at = _now()
        notify(user_id, 'Your application export is ready for download.')
        db.session.commit()
        relay_outbox()          # push the live event right away (beat also relays every 30s)
        return {'status': 'success', 'file_path': file_path}
    except Exception as e:  # noqa: BLE001
        return _fail_or_retry(self, e, job)


@celery.task(bind=True, name='tasks.relay_outbox', max_retries=0, ignore_result=True)
def relay_outbox_task(self):
    """Safety net: publish outbox events that the request-time fast path missed (crash, Redis outage)."""
    try:
        n = relay_outbox(limit=500)
        if n:
            log.info('outbox_relayed', extra={'event': 'outbox_relayed', 'count': n})
        return {'published': n}
    except Exception as e:  # noqa: BLE001
        db.session.rollback()
        log.warning('outbox_relay_failed', extra={'event': 'outbox_relay_failed', 'error': str(e)[:200]})
        return {'status': 'error', 'message': str(e)}


@celery.task(bind=True, name='tasks.housekeeping', max_retries=0, ignore_result=True)
def housekeeping(self):
    """Daily: delete expired refresh tokens and long-published outbox rows."""
    try:
        return {'refresh_tokens': sessions.purge_expired(), 'outbox': purge_published()}
    except Exception as e:  # noqa: BLE001
        db.session.rollback()
        return {'status': 'error', 'message': str(e)}
