"""Cache behaviour of the real endpoints, incl. regression tests for the old stale-cache bugs."""
import cache
from conftest import login, bearer, make_drive
from models import db


def _browse(client, token, qs=''):
    return client.get('/api/v1/student/drives' + qs, headers=bearer(token)).get_json()


def test_browse_is_cached_for_every_filter_combo(client, student, company, backend):
    make_drive(company, drive_name='Alpha')
    make_drive(company, drive_name='Beta', eligibility_branch='ECE')
    token = login(client, 'stu@example.com')

    for qs in ('', '?search=alpha', '?branch=ece', '?page=1&per_page=1', '?min_cgpa=7'):
        _browse(client, token, qs)
    misses_after_cold = cache.cache_stats()['misses']
    for qs in ('', '?search=alpha', '?branch=ece', '?page=1&per_page=1', '?min_cgpa=7'):
        _browse(client, token, qs)
    stats = cache.cache_stats()
    assert stats['hits'] >= 5 and stats['misses'] == misses_after_cold    # second round = all hits


def test_filters_return_correct_results(client, student, company):
    make_drive(company, drive_name='Alpha', min_cgpa=6.0)
    make_drive(company, drive_name='Beta', eligibility_branch='ECE', min_cgpa=9.0)
    token = login(client, 'stu@example.com')
    assert [d['drive_name'] for d in _browse(client, token, '?search=alpha')['items']] == ['Alpha']
    assert [d['drive_name'] for d in _browse(client, token, '?branch=ece')['items']] == ['Beta']
    assert [d['drive_name'] for d in _browse(client, token, '?min_cgpa=7')['items']] == ['Alpha']


def test_admin_approving_a_drive_invalidates_browse_cache(client, student, company, admin):
    """Regression: the old code deleted key 'approved_drives' but cached 'approved_drives_paginated'."""
    pending = make_drive(company, drive_name='Pending one', status='pending')
    s_token = login(client, 'stu@example.com')
    a_token = login(client, 'admin@example.com')
    assert _browse(client, s_token)['total'] == 0                  # cached "empty"
    assert client.put(f'/api/v1/admin/drives/{pending.id}/approve', json={}, headers=bearer(a_token)).status_code == 200
    assert _browse(client, s_token)['total'] == 1                  # not stale


def test_closing_a_drive_invalidates_browse_cache(client, student, company, admin):
    drive = make_drive(company)
    s_token, a_token = login(client, 'stu@example.com'), login(client, 'admin@example.com')
    assert _browse(client, s_token)['total'] == 1
    client.put(f'/api/v1/admin/drives/{drive.id}/close', headers=bearer(a_token))
    assert _browse(client, s_token)['total'] == 0


def test_company_rename_invalidates_cached_drive_cards(client, student, company):
    make_drive(company)
    s_token = login(client, 'stu@example.com')
    assert _browse(client, s_token)['items'][0]['company_name'] == 'Acme'
    c_token = login(client, 'hr@acme.com')
    client.put('/api/v1/companies/profile', json={'company_name': 'Acme Corp'}, headers=bearer(c_token))
    assert _browse(client, s_token)['items'][0]['company_name'] == 'Acme Corp'


def test_admin_stats_cached_and_invalidated_by_apply(client, student, company, admin):
    drive = make_drive(company)
    a_token, s_token = login(client, 'admin@example.com'), login(client, 'stu@example.com')
    before = client.get('/api/v1/admin/dashboard', headers=bearer(a_token)).get_json()
    assert before['total_applications'] == 0
    client.post(f'/api/v1/student/apply/{drive.id}', json={}, headers=bearer(s_token))
    after = client.get('/api/v1/admin/dashboard', headers=bearer(a_token)).get_json()
    assert after['total_applications'] == 1 and after['chart_app_status']['applied'] == 1


def test_admin_stats_shape(client, admin):
    token = login(client, 'admin@example.com')
    data = client.get('/api/v1/admin/dashboard', headers=bearer(token)).get_json()
    for key in ('total_students', 'total_companies', 'total_drives', 'pending_companies', 'selected_students',
                'blacklisted_users', 'chart_app_status', 'chart_drive_status'):
        assert key in data
    assert set(data['chart_app_status']) == {'applied', 'shortlisted', 'selected', 'rejected', 'withdrawn'}


def test_company_dashboard_counts_and_cache_busting(client, student, company):
    drive = make_drive(company, drive_name='D1')
    c_token, s_token = login(client, 'hr@acme.com'), login(client, 'stu@example.com')
    dash = client.get('/api/v1/company/dashboard', headers=bearer(c_token)).get_json()
    assert dash['total_drives'] == 1 and dash['total_applicants'] == 0
    client.post(f'/api/v1/student/apply/{drive.id}', json={}, headers=bearer(s_token))
    dash = client.get('/api/v1/company/dashboard', headers=bearer(c_token)).get_json()
    assert dash['total_applicants'] == 1 and dash['drives_summary'][0]['applicants'] == 1


def test_cache_stats_endpoint_admin_only(client, admin, student):
    assert client.get('/api/v1/admin/cache-stats', headers=bearer(login(client, 'stu@example.com'))).status_code == 403
    data = client.get('/api/v1/admin/cache-stats', headers=bearer(login(client, 'admin@example.com'))).get_json()
    assert data['backend'] in ('memory', 'redis')
    db.session.rollback()
