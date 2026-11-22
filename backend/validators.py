import re

# basic input validators

def validate_email(email):
    """check if email looks valid"""
    if not email or not isinstance(email, str):
        return False
    pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
    return bool(re.match(pattern, email.strip()))

def validate_password(password):
    if not password or len(password) < 6:
        return False, 'Password must be at least 6 characters'
    if len(password) > 128:
        return False, 'Password too long'
    return True, None

def validate_phone(phone):
    if not phone:
        return True, None  # phone is optional
    phone = phone.strip()
    # allow digits, spaces, +, -, ()
    cleaned = re.sub(r'[\s\-\(\)\+]', '', phone)
    if not cleaned.isdigit():
        return False, 'Phone number should contain only digits'
    if len(cleaned) < 7 or len(cleaned) > 15:
        return False, 'Phone number should be 7-15 digits'
    return True, None

def validate_cgpa(cgpa):
    try:
        val = float(cgpa)
        if val < 0 or val > 10:
            return False, 'CGPA must be between 0 and 10'
        return True, None
    except (ValueError, TypeError):
        return False, 'CGPA must be a number'

def validate_year(year):
    if not year:
        return True, None
    try:
        y = int(year)
        if y < 2000 or y > 2035:
            return False, 'Graduation year must be between 2000 and 2035'
        return True, None
    except (ValueError, TypeError):
        return False, 'Graduation year must be a valid number'

def validate_url(url):
    if not url:
        return True, None  # optional
    url = url.strip()
    pattern = r'^https?://[a-zA-Z0-9]([a-zA-Z0-9\-]*\.)+[a-zA-Z]{2,}'
    if not re.match(pattern, url):
        return False, 'Please enter a valid URL starting with http:// or https://'
    return True, None

def validate_name(name, field='Name'):
    if not name or not name.strip():
        return False, f'{field} is required'
    if len(name.strip()) < 2:
        return False, f'{field} must be at least 2 characters'
    if len(name.strip()) > 150:
        return False, f'{field} is too long'
    return True, None


# --------------------------------------------------------------------------- sanitisation
_TAG_RE = re.compile(r'<[^>]*>')
_CTRL_RE = re.compile(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]')


def clean_text(value, max_len=None):
    """Strip HTML tags and control characters from user-supplied free text (stored-XSS defence).

    The Vue frontend already escapes output, but the same strings also end up in HTML e-mails and
    PDF reports, so we sanitise on the way in rather than trusting every consumer.
    Non-strings are returned unchanged.
    """
    if not isinstance(value, str):
        return value
    value = _CTRL_RE.sub('', value)
    previous = None
    while previous != value:       # handles nested tricks like "<<b>script>"
        previous = value
        value = _TAG_RE.sub('', value)
    value = value.replace('<', '').replace('>', '').strip()
    return value[:max_len] if max_len else value


def clean_list(values, max_len=100, max_items=50):
    if not isinstance(values, list):
        return []
    out = []
    for v in values[:max_items]:
        v = clean_text(v, max_len) if isinstance(v, str) else ''
        if v:
            out.append(v)
    return out


def is_pdf(file_storage):
    """Check the real file signature (magic bytes), not just the extension. Rewinds the stream."""
    head = file_storage.stream.read(5)
    file_storage.stream.seek(0)
    return head == b'%PDF-'
