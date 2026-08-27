import csv
import os
import datetime
from celery_worker import celery
from models import db, User, StudentProfile, PlacementDrive, Application, MonthlyReport, Notification, AsyncJob


def send_email(subject, recipients, html_body):
    """Send email via Flask-Mail — optional, fails silently in dev without MAIL creds"""
    # Skip if no mail creds configured (Railway without MAIL_PASSWORD)
    try:
        from flask import current_app
        if not current_app.config.get('MAIL_USERNAME') or not current_app.config.get('MAIL_PASSWORD'):
            print("[*] Email skipped — MAIL creds not configured (set MAIL_USERNAME/PASSWORD to enable)")
            return False
        from app import mail
        from flask_mail import Message
        msg = Message(subject=subject, recipients=recipients, html=html_body)
        mail.send(msg)
        print(f"[+] Email sent: {subject} -> {recipients}")
        return True
    except Exception as e:
        print(f"[!] Email sending failed (non-fatal): {e}")
        return False


def send_gchat_webhook(message):
    # send to google chat space
    try:
        import requests
        from flask import current_app
        webhook_url = current_app.config.get('GCHAT_WEBHOOK_URL', '') or os.environ.get('GCHAT_WEBHOOK_URL', '')
        if webhook_url:
            requests.post(webhook_url, json={"text": message}, timeout=10)
            return True
    except Exception as e:
        print(f"Google Chat webhook failed: {e}")
    return False


@celery.task(name='tasks.send_daily_reminders')
def send_daily_reminders():
    """Send daily reminders for upcoming deadlines"""
    try:
        now = datetime.datetime.utcnow()
        upcoming_deadline = now + datetime.timedelta(days=3)

        drives = PlacementDrive.query.filter(
            PlacementDrive.status == 'approved',
            PlacementDrive.application_deadline >= now,
            PlacementDrive.application_deadline <= upcoming_deadline
        ).all()

        students = StudentProfile.query.join(User).filter(
            User.is_active == True,
            User.is_blacklisted == False
        ).all()

        count = 0
        for student in students:
            reminder_drives = []
            for drive in drives:
                existing_app = Application.query.filter_by(
                    student_id=student.id, drive_id=drive.id
                ).first()
                if not existing_app:
                    # In-app notification
                    notification = Notification(
                        user_id=student.user_id,
                        message=f"Reminder: Application deadline for '{drive.drive_name}' at {drive.company.company_name} is on {drive.application_deadline.strftime('%Y-%m-%d')}. Apply before it's too late!",
                        channel='email',
                        is_sent=True,
                    )
                    db.session.add(notification)
                    reminder_drives.append(drive)
                    count += 1

            # Send a single email per student with all upcoming drives
            if reminder_drives and student.user and student.user.email:
                drives_html = ''.join([
                    f"<li><strong>{d.drive_name}</strong> at {d.company.company_name} — Deadline: {d.application_deadline.strftime('%Y-%m-%d')}</li>"
                    for d in reminder_drives
                ])
                email_body = f"""
                <html><body>
                <h2>Placement Portal - Upcoming Deadlines</h2>
                <p>Hi {student.full_name},</p>
                <p>The following placement drives have upcoming deadlines (within 3 days):</p>
                <ul>{drives_html}</ul>
                <p>Log in to the Placement Portal to apply before it's too late!</p>
                <p>Best regards,<br>Placement Portal Team</p>
                </body></html>
                """
                send_email(
                    subject="Placement Portal - Upcoming Application Deadlines",
                    recipients=[student.user.email],
                    html_body=email_body
                )
                # webhook notification
                drives_text = ', '.join([f"{d.drive_name} (deadline: {d.application_deadline.strftime('%Y-%m-%d')})" for d in reminder_drives])
                send_gchat_webhook(f"Reminder for {student.full_name}: Upcoming deadlines - {drives_text}")

        db.session.commit()
        return {'status': 'success', 'reminders_sent': count}
    except Exception as e:
        db.session.rollback()
        return {'status': 'error', 'message': str(e)}


@celery.task(name='tasks.generate_monthly_report')
def generate_monthly_report(job_id=None):
    """Generate monthly report and email it to admin"""
    job = None
    try:
        if job_id:
            job = AsyncJob.query.get(job_id)
            if job:
                job.status = 'running'
                db.session.commit()

        now = datetime.datetime.utcnow()
        month_str = now.strftime('%Y-%m')
        first_day = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        if now.month == 12:
            last_day = first_day.replace(year=now.year + 1, month=1)
        else:
            last_day = first_day.replace(month=now.month + 1)

        total_drives = PlacementDrive.query.filter(
            PlacementDrive.created_at >= first_day,
            PlacementDrive.created_at < last_day
        ).count()

        total_applications = Application.query.filter(
            Application.application_date >= first_day,
            Application.application_date < last_day
        ).count()

        total_selected = Application.query.filter(
            Application.application_date >= first_day,
            Application.application_date < last_day,
            Application.status == 'selected'
        ).count()

        report_html = f"""
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

        # save HTML report — volume-aware (Railway: REPORTS_FOLDER=/data/reports)
        try:
            from flask import current_app
            reports_dir = current_app.config.get('REPORTS_FOLDER', os.path.join(os.path.dirname(__file__), 'reports'))
        except Exception:
            reports_dir = os.environ.get('REPORTS_FOLDER', os.path.join(os.path.dirname(__file__), 'reports'))
        os.makedirs(reports_dir, exist_ok=True)
        report_path = os.path.join(reports_dir, f'report_{month_str}.html')
        with open(report_path, 'w') as f:
            f.write(report_html)

        # also generate PDF
        pdf_path = os.path.join(reports_dir, f'report_{month_str}.pdf')
        try:
            from xhtml2pdf import pisa
            with open(pdf_path, 'wb') as pdf_file:
                pisa.CreatePDF(report_html, dest=pdf_file)
        except Exception as pdf_err:
            print(f"PDF generation failed: {pdf_err}")
            pdf_path = None

        report = MonthlyReport(
            month=month_str,
            total_drives=total_drives,
            total_applications=total_applications,
            total_selected=total_selected,
            report_path=report_path,
        )
        db.session.add(report)

        # notify admin + send email
        admin = User.query.filter_by(role='admin').first()
        if admin:
            notification = Notification(
                user_id=admin.id,
                message=f"Monthly placement report for {month_str} is ready. Drives: {total_drives}, Applications: {total_applications}, Selected: {total_selected}",
                channel='email',
                is_sent=True,
            )
            db.session.add(notification)

            # Email the report to admin
            send_email(
                subject=f"Placement Portal - Monthly Report {month_str}",
                recipients=[admin.email],
                html_body=report_html
            )
            # gchat summary
            send_gchat_webhook(f"Monthly Report {month_str}: {total_drives} drives, {total_applications} applications, {total_selected} selected")

        db.session.commit()

        # Update job status for frontend polling
        if job:
            job.status = 'completed'
            job.file_path = report_path
            job.completed_at = datetime.datetime.utcnow()
            db.session.commit()

        return {'status': 'success', 'report_path': report_path}
    except Exception as e:
        db.session.rollback()
        if job:
            try:
                job.status = 'failed'
                db.session.commit()
            except Exception:
                pass
        return {'status': 'error', 'message': str(e)}


@celery.task(name='tasks.export_applications_csv')
def export_applications_csv(user_id, student_id, job_id):
    """Export student applications to CSV"""
    job = None
    try:
        job = AsyncJob.query.get(job_id)
        if job:
            job.status = 'running'
            db.session.commit()

        applications = Application.query.filter_by(student_id=student_id).all()

        # volume-aware exports (Railway: EXPORTS_FOLDER=/data/exports)
        try:
            from flask import current_app
            exports_dir = current_app.config.get('EXPORTS_FOLDER', os.path.join(os.path.dirname(__file__), 'exports'))
        except Exception:
            exports_dir = os.environ.get('EXPORTS_FOLDER', os.path.join(os.path.dirname(__file__), 'exports'))
        os.makedirs(exports_dir, exist_ok=True)
        file_path = os.path.join(exports_dir, f'applications_{student_id}_{datetime.datetime.utcnow().strftime("%Y%m%d_%H%M%S")}.csv')

        with open(file_path, 'w', newline='', encoding='utf-8') as csvfile:
            writer = csv.writer(csvfile)
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

        if job:
            job.status = 'completed'
            job.file_path = file_path
            job.completed_at = datetime.datetime.utcnow()
            db.session.commit()

        # Notify user
        notification = Notification(
            user_id=user_id,
            message='Your application export is ready for download.',
            channel='in-app',
            is_sent=True,
        )
        db.session.add(notification)
        db.session.commit()

        return {'status': 'success', 'file_path': file_path}
    except Exception as e:
        if job:
            job.status = 'failed'
            db.session.commit()
        return {'status': 'error', 'message': str(e)}
