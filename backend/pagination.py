"""Reusable pagination helper — consistent across all list endpoints."""

def paginate_query(query, page=1, per_page=6):
    """Paginate a SQLAlchemy query and return dict with items + meta.
    - page/per_page from request args, sanitized
    - returns {items, total, pages, page, per_page, has_next, has_prev}
    - supports both array and paginated response for backward compatibility
    """
    try:
        page = int(page)
    except (TypeError, ValueError):
        page = 1
    try:
        per_page = int(per_page)
    except (TypeError, ValueError):
        per_page = 6
    page = max(1, page)
    per_page = min(50, max(1, per_page))

    pagination = query.paginate(page=page, per_page=per_page, error_out=False)
    return {
        'items': [item.to_dict() for item in pagination.items],
        'total': pagination.total,
        'pages': pagination.pages,
        'page': pagination.page,
        'per_page': pagination.per_page,
        'has_next': pagination.has_next,
        'has_prev': pagination.has_prev,
    }


def paginated_response(query, page, per_page):
    """Wrapper that returns Flask jsonify-ready dict with pagination meta.
    Frontend can use r.items || r (fallback) for backward compat.
    """
    data = paginate_query(query, page, per_page)
    return data
