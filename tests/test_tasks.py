from datetime import datetime, timedelta

import pytest

import async_dispatch
import dead_letter
import tasks
from conftest import make_drive, make_user
from models import db, AsyncJob, MonthlyReport, Notification, Application


def test_reminders_are_idempotent(app, student, company):
    make_drive(company, deadline=datetime.utcnow() + timedelta(days=1))
    first = tasks.send_daily_reminders()
    second = tasks.send_daily_reminders()          # next day's run / retried delivery
    assert first['reminders_sent'] == 1 and second['reminders_sent'] == 0
    assert Notification.query.filter_by(user_id=student.id).count() == 1


def test_reminders_skip_students_who_already_applied(app, student, company):
    drive = make_drive(company, deadline=datetime.utcnow() + timedelta(days=1))
    db.session.add(Application(student_id=student.student_profile.id, drive_id=drive.id))
    db.session.commit()
    assert tasks.send_daily_reminders()['reminders_sent'] == 0


def test_monthly_report_upserts_single_row(app, admin, company, monkeypatch):
    sent = []
    monkeypatch.setattr(tasks, 'send_email', lambda *a, **k: sent.append(1) or True)
    for _ in range(2):
        job = AsyncJob(user_id=admin.id, job_type='generate_monthly_report')
        db.session.add(job)
        db.session.commit()
        assert tasks.generate_monthly_report(job.id)['status'] == 'success'
    assert MonthlyReport.query.count() == 1
    assert len(sent) == 1                          # admin e-mailed once per month per day, not per click


def test_completed_job_is_a_noop(app, admin):
    job = AsyncJob(user_id=admin.id, job_type='generate_monthly_report', status='completed', file_path='/x.html')
    db.session.add(job)
    db.session.commit()
    assert tasks.generate_monthly_report(job.id).get('idempotent') is True
    assert MonthlyReport.query.count() == 0


def test_export_is_idempotent_and_deterministic(app, student):
    job = AsyncJob(user_id=student.id, job_type='export_applications_csv')
    db.session.add(job)
    db.session.commit()
    sp = student.student_profile.id
    r1 = tasks.export_applications_csv(student.id, sp, job.id)
    r2 = tasks.export_applications_csv(student.id, sp, job.id)
    assert r1['file_path'].endswith(f'job{job.id}.csv') and r2.get('idempotent') is True
    assert Notification.query.filter_by(user_id=student.id).count() == 1


def test_failure_in_sync_mode_marks_job_failed_without_raising(app, student, monkeypatch):
    job = AsyncJob(user_id=student.id, job_type='export_applications_csv')
    db.session.add(job)
    db.session.commit()
    monkeypatch.setattr(tasks.Application, 'query', type('Q', (), {'filter_by': staticmethod(lambda **k: (_ for _ in ()).throw(RuntimeError('boom')))}))
    result = tasks.export_applications_csv(student.id, 1, job.id)
    assert result['status'] == 'error'
    db.session.expire_all()      # the task ran in its own app context / session
    assert db.session.get(AsyncJob, job.id).status == 'failed'


def test_transient_errors_retry_with_backoff_permanent_errors_do_not(app, monkeypatch):
    class FakeRequest:
        called_directly = False
        retries = 1

    class FakeTask:
        name = 'tasks.fake'
        request = FakeRequest()

        def retry(self, exc, countdown):
            self.countdown = countdown
            return RuntimeError('retry-signal')

    t = FakeTask()
    with pytest.raises(RuntimeError, match='retry-signal'):
        tasks._fail_or_retry(t, ConnectionError('net blip'))
    assert t.countdown == 120                       # 60 * 2**retries (exponential)

    with pytest.raises(ValueError):                 # programming error: no retry, goes to DLQ via on_failure
        tasks._fail_or_retry(t, ValueError('bug'))

    FakeRequest.retries = tasks.MAX_RETRIES
    with pytest.raises(ConnectionError):            # retries exhausted
        tasks._fail_or_retry(t, ConnectionError('still down'))


# ---------------------------------------------------------------------------- dead letter queue
def test_dead_letter_push_list_replay(app, fake_redis, monkeypatch):
    dead_letter.push_dead_letter('tasks.export_applications_csv', 'abc-123', [1, 2, 3], {}, RuntimeError('disk full'))
    items = dead_letter.list_dead_letters()
    assert items[0]['task_id'] == 'abc-123' and 'disk full' in items[0]['error']

    sent = []
    import celery_worker
    monkeypatch.setattr(celery_worker.celery, 'send_task', lambda name, args, kwargs: sent.append((name, args)))
    assert dead_letter.replay_dead_letter('abc-123') is True
    assert sent == [('tasks.export_applications_csv', [1, 2, 3])]
    assert dead_letter.list_dead_letters() == []
    assert dead_letter.replay_dead_letter('abc-123') is False


def test_dead_letter_is_bounded_and_falls_back_to_memory(app):
    dead_letter._memory.clear()
    dead_letter.push_dead_letter('t', 'id1', [], {}, ValueError('x'))     # no redis => memory
    assert dead_letter.list_dead_letters()[0]['task_id'] == 'id1'
    dead_letter._memory.clear()


def test_dead_letter_admin_endpoints(client, admin, fake_redis):
    from conftest import login, bearer
    dead_letter.push_dead_letter('tasks.x', 'zzz', [], {}, RuntimeError('nope'))
    token = login(client, 'admin@example.com')
    items = client.get('/api/v1/admin/dead-letters', headers=bearer(token)).get_json()['items']
    assert items[0]['task_id'] == 'zzz'
    assert client.post('/api/v1/admin/dead-letters/missing/replay', headers=bearer(token)).status_code == 404


# ---------------------------------------------------------------------------- dispatch
class _FakeTask:
    name = 'tasks.fake'

    def __init__(self):
        self.queued, self.ran = [], []

    def apply_async(self, args=(), kwargs=None):
        self.queued.append(args)

    def __call__(self, *a, **k):
        self.ran.append(a)


def test_dispatch_queues_when_worker_alive(app, monkeypatch):
    app.config['FORCE_SYNC_TASKS'] = False
    monkeypatch.setattr(async_dispatch, 'worker_count', lambda use_cache=True: 2)
    t = _FakeTask()
    assert async_dispatch.dispatch(t, 7) == 'queued' and t.queued == [(7,)] and not t.ran


def test_dispatch_runs_inline_when_no_worker(app, monkeypatch):
    app.config['FORCE_SYNC_TASKS'] = False
    monkeypatch.setattr(async_dispatch, 'worker_count', lambda use_cache=True: 0)
    t = _FakeTask()
    assert async_dispatch.dispatch(t, 7) == 'sync' and t.ran == [(7,)] and not t.queued


def test_dispatch_falls_back_when_publish_fails(app, monkeypatch):
    app.config['FORCE_SYNC_TASKS'] = False
    monkeypatch.setattr(async_dispatch, 'worker_count', lambda use_cache=True: 1)
    t = _FakeTask()

    def broken(args=(), kwargs=None):
        raise ConnectionError('broker died')

    t.apply_async = broken
    assert async_dispatch.dispatch(t, 9) == 'sync' and t.ran == [(9,)]


def test_dispatch_never_raises_if_inline_task_fails(app):
    class Bad(_FakeTask):
        def __call__(self, *a, **k):
            raise RuntimeError('boom')

    assert async_dispatch.dispatch(Bad(), 1) == 'sync'


def test_worker_count_is_cached(app, fake_redis, monkeypatch):
    import celery_worker
    calls = []

    class Insp:
        def ping(self):
            calls.append(1)
            return {'w1@host': {'ok': 'pong'}}

    monkeypatch.setattr(celery_worker.celery.control, 'inspect', lambda timeout=1: Insp())
    assert async_dispatch.worker_count() == 1
    assert async_dispatch.worker_count() == 1
    assert len(calls) == 1


def test_make_user_helper_sanity(app):
    assert make_user('student', 'x@y.com').student_profile.full_name == 'Test Student'
