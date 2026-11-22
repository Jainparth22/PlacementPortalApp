from models import db, Notification
from pagination import paginate_query
from conftest import login, bearer


def _seed(user, n):
    for i in range(n):
        db.session.add(Notification(user_id=user.id, message=f'm{i}'))
    db.session.commit()


def test_pagination_math(app, student):
    _seed(student, 13)
    q = Notification.query.order_by(Notification.id)
    p1 = paginate_query(q, 1, 6)
    p3 = paginate_query(q, 3, 6)
    assert p1['total'] == 13 and p1['pages'] == 3 and len(p1['items']) == 6 and p1['has_next'] and not p1['has_prev']
    assert len(p3['items']) == 1 and not p3['has_next'] and p3['has_prev']


def test_page_out_of_range_is_empty_not_error(app, student):
    _seed(student, 3)
    p = paginate_query(Notification.query, 999, 6)
    assert p['items'] == [] and p['total'] == 3


def test_bad_inputs_are_sanitised(app, student):
    _seed(student, 3)
    assert paginate_query(Notification.query, 'abc', 'xyz')['per_page'] == 6
    assert paginate_query(Notification.query, -5, 6)['page'] == 1
    assert paginate_query(Notification.query, 1, 9999)['per_page'] == 50
    assert paginate_query(Notification.query, 1, 0)['per_page'] == 1


def test_endpoint_returns_pagination_envelope(client, student):
    _seed(student, 15)
    token = login(client, 'stu@example.com')
    data = client.get('/api/v1/notifications?page=2&per_page=10', headers=bearer(token)).get_json()
    assert data['page'] == 2 and data['pages'] == 2 and len(data['items']) == 5
