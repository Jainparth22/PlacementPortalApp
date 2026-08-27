"""
Seed script for PPA V5 — populates the database with sample test data.

Usage:
    cd backend
    python seed.py

This will DROP all existing data and re-create the tables, then insert:
  - 1 Admin user
  - 2 Companies (approved) with 3 placement drives (approved)
  - 5 Students with profiles and skills
  - Applications, interviews, and placement history
"""

import os
import sys

# Ensure backend package is importable
sys.path.insert(0, os.path.dirname(__file__))

from datetime import datetime
from werkzeug.security import generate_password_hash
from app import create_app
from models import (
    db,
    User,
    StudentProfile,
    CompanyProfile,
    PlacementDrive,
    Application,
    DriveApproval,
    Interview,
    PlacementHistory,
    Notification,
    Skill,
)


def seed():
    app = create_app()
    with app.app_context():
        print("[*] Dropping all tables …")
        db.drop_all()
        print("[*] Re-creating tables …")
        db.create_all()

        # ── Admin ──────────────────────────────────────────────
        admin = User(
            email="jainparth7040@gmail.com",
            password_hash=generate_password_hash("admin123"),
            role="admin",
            is_active=True,
        )
        db.session.add(admin)
        db.session.flush()
        print(f"[+] Admin created: {admin.email}")

        # ── Companies ─────────────────────────────────────────
        # Company 1 – TechNova Solutions
        technova_user = User(
            email="hr@technova.com",
            password_hash=generate_password_hash("Tech@123"),
            role="company",
            is_active=True,
        )
        db.session.add(technova_user)
        db.session.flush()

        technova = CompanyProfile(
            user_id=technova_user.id,
            company_name="TechNova Solutions",
            hr_name="Priya Sharma",
            hr_email="hr@technova.com",
            hr_phone="9876543210",
            website="https://technova.com",
            industry="Information Technology",
            description=(
                "Leading IT services company specializing in cloud solutions, "
                "AI, and enterprise software development."
            ),
            approval_status="approved",
        )
        db.session.add(technova)
        db.session.flush()
        print(f"[+] Company created: {technova.company_name}")

        # Company 2 – GreenLeaf Analytics
        greenleaf_user = User(
            email="careers@greenleaf.com",
            password_hash=generate_password_hash("Green@123"),
            role="company",
            is_active=True,
        )
        db.session.add(greenleaf_user)
        db.session.flush()

        greenleaf = CompanyProfile(
            user_id=greenleaf_user.id,
            company_name="GreenLeaf Analytics",
            hr_name="Amit Desai",
            hr_email="careers@greenleaf.com",
            hr_phone="9823456789",
            website="https://greenleaf.in",
            industry="Data Analytics",
            description=(
                "Data analytics firm helping businesses make data-driven "
                "decisions using ML and BI tools."
            ),
            approval_status="approved",
        )
        db.session.add(greenleaf)
        db.session.flush()
        print(f"[+] Company created: {greenleaf.company_name}")

        # ── Placement Drives ──────────────────────────────────
        # Drive 1 – TechNova SDE
        drive_sde = PlacementDrive(
            company_id=technova.id,
            drive_name="TechNova Campus 2026",
            job_title="Software Development Engineer",
            job_description=(
                "We are looking for B.Tech graduates to join our engineering team. "
                "Work on cloud-native applications using Python, Java, and React. "
                "Strong knowledge of data structures and algorithms required."
            ),
            eligibility_branch="CSE, IT, ECE",
            min_cgpa=7.0,
            eligible_year=2026,
            application_deadline=datetime(2026, 4, 15),
            location="Bangalore",
            salary="12 LPA",
            job_type="Full-time",
            status="approved",
        )
        db.session.add(drive_sde)

        # Drive 2 – TechNova Intern
        drive_intern = PlacementDrive(
            company_id=technova.id,
            drive_name="TechNova Internship Program",
            job_title="Data Science Intern",
            job_description=(
                "6-month internship in our AI/ML division. Work on real-world "
                "NLP and computer vision projects. Experience with Python, "
                "machine learning, and deep learning preferred."
            ),
            eligibility_branch="CSE, IT",
            min_cgpa=6.5,
            eligible_year=2026,
            application_deadline=datetime(2026, 3, 30),
            location="Pune",
            salary="25000/month",
            job_type="Internship",
            status="approved",
        )
        db.session.add(drive_intern)

        # Drive 3 – GreenLeaf Analyst
        drive_analyst = PlacementDrive(
            company_id=greenleaf.id,
            drive_name="GreenLeaf Analyst Hiring 2026",
            job_title="Business Analyst",
            job_description=(
                "Analyze business data, create dashboards in Power BI, write "
                "SQL queries, and present insights to stakeholders. Strong "
                "communication and data visualization skills required."
            ),
            eligibility_branch="CSE, IT, MBA",
            min_cgpa=7.5,
            eligible_year=2026,
            application_deadline=datetime(2026, 4, 1),
            location="Indore",
            salary="8 LPA",
            job_type="Full-time",
            status="approved",
        )
        db.session.add(drive_analyst)
        db.session.flush()

        # Drive approvals by admin
        for drive in [drive_sde, drive_intern, drive_analyst]:
            db.session.add(
                DriveApproval(
                    drive_id=drive.id,
                    admin_id=admin.id,
                    action="approved",
                    remarks="Auto-approved via seed script",
                )
            )
        print("[+] 3 placement drives created & approved")

        # ── Students ──────────────────────────────────────────
        students_data = [
            {
                "email": "rahul.verma@student.com",
                "password": "Rahul@123",
                "full_name": "Rahul Verma",
                "department": "CSE",
                "cgpa": 8.5,
                "graduation_year": 2026,
                "phone": "9876501111",
                "bio": "Full-stack developer with Python and React experience. Built 3 web apps.",
                "skills": ["Python", "JavaScript", "React", "Flask", "SQL", "Git"],
            },
            {
                "email": "sneha.patel@student.com",
                "password": "Sneha@123",
                "full_name": "Sneha Patel",
                "department": "IT",
                "cgpa": 7.2,
                "graduation_year": 2026,
                "phone": "9876502222",
                "bio": "Aspiring data analyst. Proficient in SQL, Excel, and Python.",
                "skills": ["Python", "SQL", "Pandas", "Power BI", "Excel"],
            },
            {
                "email": "arjun.mehta@student.com",
                "password": "Arjun@123",
                "full_name": "Arjun Mehta",
                "department": "ECE",
                "cgpa": 6.8,
                "graduation_year": 2026,
                "phone": "9876503333",
                "bio": "Embedded systems enthusiast with IoT project experience.",
                "skills": ["C++", "Arduino", "IoT", "MATLAB", "Python"],
            },
            {
                "email": "kavya.nair@student.com",
                "password": "Kavya@123",
                "full_name": "Kavya Nair",
                "department": "CSE",
                "cgpa": 9.1,
                "graduation_year": 2026,
                "phone": "9876504444",
                "bio": "ML researcher with 2 published papers. Dean list student.",
                "skills": ["Python", "Machine Learning", "NLP", "PyTorch", "TensorFlow"],
            },
            {
                "email": "rohan.joshi@student.com",
                "password": "Rohan@123",
                "full_name": "Rohan Joshi",
                "department": "IT",
                "cgpa": 7.8,
                "graduation_year": 2026,
                "phone": "9876505555",
                "bio": "Backend developer experienced in Flask, Django, and PostgreSQL.",
                "skills": ["Python", "Flask", "Django", "PostgreSQL", "Docker", "Redis"],
            },
        ]

        student_profiles = []
        for s in students_data:
            user = User(
                email=s["email"],
                password_hash=generate_password_hash(s["password"]),
                role="student",
                is_active=True,
            )
            db.session.add(user)
            db.session.flush()

            profile = StudentProfile(
                user_id=user.id,
                full_name=s["full_name"],
                department=s["department"],
                cgpa=s["cgpa"],
                graduation_year=s["graduation_year"],
                phone=s["phone"],
                bio=s["bio"],
            )
            db.session.add(profile)
            db.session.flush()

            for skill_name in s["skills"]:
                db.session.add(Skill(student_id=profile.id, skill_name=skill_name))

            student_profiles.append(profile)
            print(f"[+] Student created: {s['full_name']} ({s['department']}, {s['cgpa']})")

        # Unpack for readability
        rahul, sneha, arjun, kavya, rohan = student_profiles

        # ── Applications ──────────────────────────────────────
        # Students apply to eligible drives
        applications_data = [
            # Rahul → SDE (HIGH), Intern (MEDIUM)
            {"student": rahul, "drive": drive_sde, "status": "shortlisted",
             "cover_letter": "I am passionate about building scalable cloud-native applications."},
            {"student": rahul, "drive": drive_intern, "status": "applied",
             "cover_letter": "Eager to explore data science and ML during an internship."},
            # Sneha → Analyst (HIGH), SDE (LOW)
            {"student": sneha, "drive": drive_analyst, "status": "shortlisted",
             "cover_letter": "Data analytics is my passion. Proficient in SQL and Power BI."},
            {"student": sneha, "drive": drive_sde, "status": "applied",
             "cover_letter": "Looking to transition into software development."},
            # Arjun → SDE (LOW – ECE eligible), Intern (MEDIUM)
            {"student": arjun, "drive": drive_sde, "status": "applied",
             "cover_letter": "Interested in software development alongside my hardware skills."},
            {"student": arjun, "drive": drive_intern, "status": "applied",
             "cover_letter": "Would like to explore ML/AI and sensor data analytics."},
            # Kavya → SDE (HIGH), Intern (HIGH), Analyst (MEDIUM)
            {"student": kavya, "drive": drive_sde, "status": "shortlisted",
             "cover_letter": "Full-stack developer and ML researcher ready to contribute."},
            {"student": kavya, "drive": drive_intern, "status": "shortlisted",
             "cover_letter": "Published NLP researcher eager for a hands-on ML internship."},
            {"student": kavya, "drive": drive_analyst, "status": "applied",
             "cover_letter": "Strong analytical skills backed by ML expertise."},
            # Rohan → SDE (HIGH), Intern (LOW)
            {"student": rohan, "drive": drive_sde, "status": "shortlisted",
             "cover_letter": "Backend developer with production experience in Flask and Docker."},
            {"student": rohan, "drive": drive_intern, "status": "applied",
             "cover_letter": "Interested in expanding my backend skills into data science."},
        ]

        app_objects = []
        for a in applications_data:
            application = Application(
                student_id=a["student"].id,
                drive_id=a["drive"].id,
                status=a["status"],
                cover_letter=a["cover_letter"],
            )
            db.session.add(application)
            app_objects.append(application)
        db.session.flush()
        print(f"[+] {len(applications_data)} applications created")

        # ── Interviews (for shortlisted candidates) ───────────
        shortlisted = [a for a in app_objects if a.status == "shortlisted"]
        for app_obj in shortlisted:
            interview = Interview(
                application_id=app_obj.id,
                interview_date=datetime(2026, 3, 20, 10, 0),
                mode="Online",
                venue="Google Meet",
                result="pending",
            )
            db.session.add(interview)
        db.session.flush()
        print(f"[+] {len(shortlisted)} interviews scheduled")

        # ── Notifications ─────────────────────────────────────
        # Welcome notifications for every user
        for user_obj in User.query.all():
            db.session.add(
                Notification(
                    user_id=user_obj.id,
                    message=f"Welcome to the Placement Portal, {user_obj.email}!",
                    channel="in-app",
                    is_sent=True,
                )
            )

        # Shortlist notifications for shortlisted students
        for app_obj in shortlisted:
            student_user_id = app_obj.student.user_id
            db.session.add(
                Notification(
                    user_id=student_user_id,
                    message=(
                        f"Congratulations! You have been shortlisted for "
                        f"'{app_obj.drive.drive_name}' by {app_obj.drive.company.company_name}."
                    ),
                    channel="in-app",
                    is_sent=True,
                )
            )
        print("[+] Notifications created")

        # ── Extra Pagination Demo Data (6 more companies → total 8, so paginated lists show 2 pages) ──
        extra_companies = [
            ("Astra Dynamics", "hr@astra.com", "Astra@123", "Aerospace", "Astra Dynamics builds drones & avionics."),
            ("BlueWave FinTech", "careers@bluewave.com", "Blue@123", "FinTech", "Payments gateway & lending platform."),
            ("Crest Labs", "hr@crestlabs.com", "Crest@123", "Healthcare", "Bioinformatics & diagnostic kits."),
            ("Delta Retail", "hr@deltaretail.com", "Delta@123", "E-commerce", "Omni-channel retail chain."),
            ("Echo Energy", "careers@echoenergy.com", "Echo@123", "Energy", "Solar micro-grids startup."),
            ("Falcon Motors", "hr@falcon.com", "Falcon@123", "Automobile", "EV two-wheelers."),
        ]
        extra_drives = []
        for cname, email, pwd, industry, desc in extra_companies:
            u = User(email=email, password_hash=generate_password_hash(pwd), role="company", is_active=True)
            db.session.add(u); db.session.flush()
            cp = CompanyProfile(user_id=u.id, company_name=cname, hr_name="HR "+cname.split()[0], hr_email=email, hr_phone="9876000000", website=f"https://{email.split('@')[1]}", industry=industry, description=desc, approval_status="approved")
            db.session.add(cp); db.session.flush()
            d = PlacementDrive(company_id=cp.id, drive_name=f"{cname} Hiring 2026", job_title=f"Trainee {industry}", job_description=f"Opportunity at {cname} for 2026 batch. {desc}", eligibility_branch="CSE, IT", min_cgpa=6.0, eligible_year=2026, application_deadline=datetime(2026, 4, 20), location="Remote", salary="6 LPA", job_type="Full-time", status="approved")
            db.session.add(d); db.session.flush()
            extra_drives.append(d)
            db.session.add(DriveApproval(drive_id=d.id, admin_id=admin.id, action="approved", remarks="Auto-approved extra pagination demo"))
        print(f"[+] {len(extra_companies)} extra companies + drives for pagination demo (now 8 total)")

        # ── Commit everything ─────────────────────────────────
        db.session.commit()
        print("\n✅  Database seeded successfully!")
        print(f"    Admin  : jainparth7040@gmail.com / admin123")
        print(f"    Company: hr@technova.com / Tech@123")
        print(f"    Company: careers@greenleaf.com / Green@123  (+6 extra pagination demo)")
        print(f"    Student: rahul.verma@student.com / Rahul@123")
        print(f"    Student: sneha.patel@student.com / Sneha@123")
        print(f"    Student: arjun.mehta@student.com / Arjun@123")
        print(f"    Student: kavya.nair@student.com / Kavya@123")
        print(f"    Student: rohan.joshi@student.com / Rohan@123")


if __name__ == "__main__":
    seed()
