"""Storage backends: same contract on disk, S3 (moto) and Azure (fake client); web/worker sharing a store."""
import io
import os

import boto3
import pytest
from moto import mock_aws

import storage as st
from conftest import login, bearer
from models import db, AsyncJob, StudentProfile


@pytest.fixture()
def local(tmp_path):
    return st.LocalStorage({c: tmp_path / c for c in st.CATEGORIES})


@pytest.fixture()
def s3():
    with mock_aws():
        client = boto3.client('s3', region_name='us-east-1')
        client.create_bucket(Bucket='ppa-test')
        yield st.S3Storage('ppa-test', prefix='prod', client=client)


class _FakeBlob:
    def __init__(self, store, name):
        self.store, self.name = store, name

    def upload_blob(self, data, overwrite=False, content_settings=None):
        self.store[self.name] = bytes(data)

    def download_blob(self):
        from azure.core.exceptions import ResourceNotFoundError
        if self.name not in self.store:
            raise ResourceNotFoundError('nope')
        data = self.store[self.name]
        return type('D', (), {'readall': lambda s: data, 'chunks': lambda s: iter([data[:3], data[3:]])})()

    def exists(self):
        return self.name in self.store

    def delete_blob(self):
        del self.store[self.name]


class _FakeContainer:
    def __init__(self):
        self.store = {}

    def get_blob_client(self, name):
        return _FakeBlob(self.store, name)

    def exists(self):
        return True


@pytest.fixture()
def azure():
    container = _FakeContainer()
    svc = type('Svc', (), {'get_container_client': lambda self, name: container})()
    return st.AzureBlobStorage('ppa', client=svc)


@pytest.fixture(params=['local', 's3', 'azure'])
def backend_store(request):
    return request.getfixturevalue(request.param)


# ------------------------------------------------------------------ contract shared by every backend
def test_put_get_exists_delete(backend_store):
    key = 'resumes/resume_1_cv.pdf'
    assert not backend_store.exists(key)
    backend_store.put_bytes(key, b'%PDF-1.4 hello', 'application/pdf')
    assert backend_store.exists(key) and backend_store.get_bytes(key) == b'%PDF-1.4 hello'
    backend_store.put_bytes(key, b'v2')                       # overwrite
    assert backend_store.get_bytes(key) == b'v2'
    backend_store.delete(key)
    assert not backend_store.exists(key)


def test_missing_key_raises_file_not_found(backend_store):
    with pytest.raises(FileNotFoundError):
        backend_store.get_bytes('reports/nope.html')


def test_send_streams_the_object(app, backend_store):
    backend_store.put_bytes('exports/a.csv', b'a,b\n1,2\n', 'text/csv')
    with app.test_request_context():
        resp = backend_store.send('exports/a.csv', 'my.csv', 'text/csv')
        body = b''.join(resp.response)
        resp.close()
        assert body == b'a,b\n1,2\n'
        assert 'my.csv' in resp.headers['Content-Disposition']


@pytest.mark.parametrize('bad', ['../etc/passwd', 'resumes/../../x.pdf', 'other/x.pdf', 'resumes/a b.pdf', 'resumes/', '', None, 'C:\\x.pdf'])
def test_keys_are_validated(backend_store, bad):
    with pytest.raises((ValueError, FileNotFoundError, TypeError)):
        backend_store.put_bytes(bad, b'x')


# ------------------------------------------------------------------ backend specifics
def test_local_resolves_legacy_paths(local, tmp_path):
    (tmp_path / 'resumes' / 'old.pdf').write_bytes(b'%PDF-old')
    assert local.get_bytes('uploads/resumes/old.pdf') == b'%PDF-old'            # relative path written by v1
    absolute = tmp_path / 'resumes' / 'old.pdf'
    assert local.get_bytes(str(absolute)) == b'%PDF-old'                        # absolute path written by v1
    assert not local.exists('uploads/resumes/missing.pdf')


def test_local_write_is_atomic_no_temp_files_left(local, tmp_path):
    local.put_bytes('reports/r.html', b'<html/>')
    assert [p.name for p in (tmp_path / 'reports').iterdir()] == ['r.html']


def test_s3_prefix_and_isolation(s3):
    s3.put_bytes('resumes/x.pdf', b'1')
    keys = [o['Key'] for o in s3.client.list_objects_v2(Bucket='ppa-test')['Contents']]
    assert keys == ['prod/resumes/x.pdf']


def test_s3_healthy(s3):
    assert s3.healthy()


def test_factory_selects_backend_from_config(app, tmp_path):
    app.config['STORAGE_BACKEND'] = 'local'
    st.use_storage(None)
    assert st.get_storage().name == 'local'
    app.config['STORAGE_BACKEND'] = 'bogus'
    st.use_storage(None)
    with pytest.raises(RuntimeError):
        st.get_storage()
    app.config['STORAGE_BACKEND'] = 'local'
    st.use_storage(None)


# ------------------------------------------------------------------ the reason this exists: web and worker on different machines
def test_worker_generated_export_is_downloadable_by_a_different_web_process(app, client, student, s3):
    """Two separate Storage objects (= two hosts) pointing at the same bucket."""
    import tasks
    web_view = st.S3Storage('ppa-test', prefix='prod', client=s3.client)
    st.use_storage(s3)                                   # "worker" host writes the CSV
    job = AsyncJob(user_id=student.id, job_type='export_applications_csv')
    db.session.add(job)
    db.session.commit()
    tasks.export_applications_csv(student.id, student.student_profile.id, job.id)
    st.use_storage(web_view)                             # "web" host, no local files at all
    token = login(client, 'stu@example.com')
    resp = client.get(f'/api/v1/student/download-export/{job.id}', headers=bearer(token))
    assert resp.status_code == 200 and b'Student ID' in resp.get_data()
    st.use_storage(None)


def test_resume_upload_and_ats_read_use_the_configured_backend(app, client, student, s3, monkeypatch):
    st.use_storage(s3)
    token = login(client, 'stu@example.com')
    resp = client.post('/api/v1/students/upload-resume', data={'resume': (io.BytesIO(b'%PDF-1.4 fake'), 'cv.pdf')},
                       headers=bearer(token), content_type='multipart/form-data')
    assert resp.status_code == 200
    key = resp.get_json()['resume_path']
    assert key == f'resumes/resume_{student.student_profile.id}_cv.pdf'
    assert s3.exists(key) and not any(f for f in os.listdir(app.config['UPLOAD_FOLDER']) if f.endswith('.pdf')) \
        if os.path.isdir(app.config['UPLOAD_FOLDER']) else s3.exists(key)
    assert StudentProfile.query.filter_by(user_id=student.id).first().resume_path == key
    st.use_storage(None)


def test_report_download_prefers_pdf_and_falls_back_to_html(app, client, admin, local):
    from models import MonthlyReport
    st.use_storage(local)
    local.put_bytes('reports/report_2026-01.html', b'<html>r</html>')
    db.session.add(MonthlyReport(month='2026-01', report_path='reports/report_2026-01.html'))
    db.session.commit()
    token = login(client, 'admin@example.com')
    r = client.get('/api/v1/admin/reports/download/1', headers=bearer(token))
    assert r.status_code == 200 and b'<html>r' in r.get_data()                   # no pdf yet -> html
    local.put_bytes('reports/report_2026-01.pdf', b'%PDF-report')
    r = client.get('/api/v1/admin/reports/download/1', headers=bearer(token))
    assert r.get_data() == b'%PDF-report'
    assert client.get('/api/v1/admin/reports/download/999', headers=bearer(token)).status_code == 404
    st.use_storage(None)
