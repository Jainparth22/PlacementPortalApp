import io
from datetime import datetime, timedelta

from conftest import login, bearer, make_drive, make_user
from models import db, StudentProfile


def _apply(client, token, drive_id):
    return client.post(f'/api/v1/student/apply/{drive_id}', json={}, headers=bearer(token))


def test_register_student_with_skills(client):
    resp = client.post('/api/v1/students/register', json={
        'email': 'new@example.com', 'password': 'secret1', 'full_name': 'New <b>Student</b>',
        'department': 'CSE', 'cgpa': 8.2, 'graduation_year': 2026, 'skills': ['Python', '<script>x</script>SQL', ''],
    })
    assert resp.status_code == 201, resp.get_json()
    student = resp.get_json()['student']
    assert student['full_name'] == 'New Student'                      # tags stripped
    assert sorted(student['skills']) == ['Python', 'xSQL']            # sanitised, blanks dropped


def test_apply_eligibility_cgpa(client, student, company):
    drive = make_drive(company, min_cgpa=9.5)
    token = login(client, 'stu@example.com')
    resp = _apply(client, token, drive.id)
    assert resp.status_code == 400 and 'CGPA' in resp.get_json()['error']


def test_apply_branch_and_year(client, student, company):
    d1 = make_drive(company, eligibility_branch='ECE,EEE')
    d2 = make_drive(company, eligible_year=2030)
    token = login(client, 'stu@example.com')
    assert _apply(client, token, d1.id).status_code == 400
    assert _apply(client, token, d2.id).status_code == 400


def test_apply_then_duplicate_is_409(client, student, company):
    drive = make_drive(company)
    token = login(client, 'stu@example.com')
    assert _apply(client, token, drive.id).status_code == 201
    assert _apply(client, token, drive.id).status_code == 409


def test_apply_after_deadline_and_unapproved(client, student, company):
    expired = make_drive(company, deadline=datetime.utcnow() - timedelta(days=1))
    pending = make_drive(company, status='pending')
    token = login(client, 'stu@example.com')
    assert _apply(client, token, expired.id).status_code == 400
    assert _apply(client, token, pending.id).status_code == 400


def test_resume_upload_rejects_non_pdf_extension(client, student):
    token = login(client, 'stu@example.com')
    data = {'resume': (io.BytesIO(b'PK\x03\x04 docx'), 'cv.docx')}
    resp = client.post('/api/v1/students/upload-resume', data=data, headers=bearer(token), content_type='multipart/form-data')
    assert resp.status_code == 400


def test_resume_upload_rejects_renamed_executable(client, student):
    """An .exe renamed to resume.pdf must be rejected by the magic-byte check."""
    token = login(client, 'stu@example.com')
    data = {'resume': (io.BytesIO(b'MZ\x90\x00 this is not a pdf'), 'resume.pdf')}
    resp = client.post('/api/v1/students/upload-resume', data=data, headers=bearer(token), content_type='multipart/form-data')
    assert resp.status_code == 400
    assert 'not a valid PDF' in resp.get_json()['error']


def test_resume_upload_accepts_real_pdf(client, student):
    token = login(client, 'stu@example.com')
    data = {'resume': (io.BytesIO(b'%PDF-1.4\n1 0 obj\n<<>>\nendobj\n%%EOF'), 'resume.pdf')}
    resp = client.post('/api/v1/students/upload-resume', data=data, headers=bearer(token), content_type='multipart/form-data')
    assert resp.status_code == 200, resp.get_json()
    assert StudentProfile.query.filter_by(user_id=student.id).first().resume_path


def test_oversized_upload_is_413_json(client, student, app):
    token = login(client, 'stu@example.com')
    big = b'%PDF-' + b'0' * (5 * 1024 * 1024 + 10)
    resp = client.post('/api/v1/students/upload-resume', data={'resume': (io.BytesIO(big), 'big.pdf')},
                       headers=bearer(token), content_type='multipart/form-data')
    assert resp.status_code == 413 and 'error' in resp.get_json()


def test_export_runs_inline_without_workers_and_is_rate_limited(client, student, app):
    app.config['HEAVY_ENDPOINT_RATE_LIMIT'] = 2
    token = login(client, 'stu@example.com')
    first = client.post('/api/v1/student/export-applications', headers=bearer(token))
    assert first.status_code == 202 and first.get_json()['mode'] == 'sync'
    job = client.get(f"/api/v1/jobs/{first.get_json()['job_id']}", headers=bearer(token)).get_json()
    assert job['status'] == 'completed' and job['file_path']
    client.post('/api/v1/student/export-applications', headers=bearer(token))
    third = client.post('/api/v1/student/export-applications', headers=bearer(token))
    assert third.status_code == 429 and 'Retry-After' in third.headers


def test_other_students_cannot_read_my_job(client, student):
    token = login(client, 'stu@example.com')
    job_id = client.post('/api/v1/student/export-applications', headers=bearer(token)).get_json()['job_id']
    make_user('student', 'intruder@example.com')
    other = login(client, 'intruder@example.com')
    assert client.get(f'/api/v1/jobs/{job_id}', headers=bearer(other)).status_code == 403


def test_ats_cache_key_is_stable_and_fallback_not_cached(client, student, company, monkeypatch):
    """The old key used builtin hash() (random per process => never a cross-worker hit)."""
    import sys
    import types
    drive = make_drive(company)
    token = login(client, 'stu@example.com')

    class Boom:
        def __init__(self, *a, **k):
            raise RuntimeError('space is sleeping')

    monkeypatch.setitem(sys.modules, 'gradio_client', types.SimpleNamespace(Client=Boom))
    resp = client.post('/api/v1/student/ats-check', json={'drive_id': drive.id}, headers=bearer(token))
    assert resp.status_code == 200 and resp.get_json()['fallback'] is True
    assert resp.get_json()['retry_after_minutes'] == 10

    calls = []

    class Fine:
        def __init__(self, *a, **k):
            pass

        def predict(self, *a, **k):
            calls.append(1)
            return 'ATS 90%'

    monkeypatch.setitem(sys.modules, 'gradio_client', types.SimpleNamespace(Client=Fine))
    r1 = client.post('/api/v1/student/ats-check', json={'drive_id': drive.id}, headers=bearer(token)).get_json()
    r2 = client.post('/api/v1/student/ats-check', json={'drive_id': drive.id}, headers=bearer(token)).get_json()
    assert r1['result'] == 'ATS 90%' and not r1.get('cached')
    assert r2['cached'] is True and len(calls) == 1


def test_profile_update_sanitises(client, student):
    token = login(client, 'stu@example.com')
    resp = client.put('/api/v1/students/profile', json={'bio': 'hi <img src=x onerror=alert(1)>', 'skills': ['Go', '<i>Rust</i>']}, headers=bearer(token))
    assert resp.status_code == 200
    s = resp.get_json()['student']
    assert '<' not in s['bio'] and sorted(s['skills']) == ['Go', 'Rust']
    db.session.expire_all()
