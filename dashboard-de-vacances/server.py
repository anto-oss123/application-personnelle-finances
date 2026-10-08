#!/usr/bin/env python3
"""Dashboard de vacances: private travel dashboard with PostgreSQL or local SQLite storage.
Local preview: python3 server.py (127.0.0.1:8765).
Hosted mode requires CAP_FRANCE_PASSWORD_HASH, CAP_FRANCE_SESSION_SECRET,
CAP_FRANCE_ORIGIN (or RENDER_EXTERNAL_URL), DATABASE_URL and durable storage.
"""
import os, json, sqlite3, secrets, hashlib, hmac, time, threading, re, math
from datetime import date
from pathlib import Path
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from http.cookies import SimpleCookie
from urllib.parse import urlsplit, parse_qs
from urllib.request import urlopen, Request
from urllib.error import URLError, HTTPError

ROOT = Path(__file__).resolve().parent
PASSWORD_HASH = os.environ.get('CAP_FRANCE_PASSWORD_HASH', '')
# The owner enters this secret directly in the hosting dashboard; never in source.
_setup_password = os.environ.pop('CAP_FRANCE_PASSWORD', '')
if _setup_password:
    if len(_setup_password) < 12:
        raise SystemExit('The application password must contain at least 12 characters.')
    _salt = secrets.token_bytes(24)
    PASSWORD_HASH = 'pbkdf2_sha256$600000$' + _salt.hex() + '$' + hashlib.pbkdf2_hmac('sha256', _setup_password.encode(), _salt, 600000).hex()
    _setup_password = None
SECRET = os.environ.get('CAP_FRANCE_SESSION_SECRET', '')
ORIGIN = (os.environ.get('CAP_FRANCE_ORIGIN', '') or os.environ.get('RENDER_EXTERNAL_URL', '')).rstrip('/')
CLOUD = bool(PASSWORD_HASH)
if (os.environ.get('RENDER') or os.environ.get('CAP_FRANCE_REQUIRE_CLOUD') == '1') and not CLOUD:
    raise SystemExit('Private hosting requires the application password to be configured.')
DATA = Path(os.environ.get('CAP_FRANCE_DATA_DIR', str(ROOT / 'data')))
DATABASE_URL = os.environ.get('DATABASE_URL', '')
if os.environ.get('CAP_FRANCE_REQUIRE_DATABASE') == '1' and not DATABASE_URL:
    raise SystemExit('Free private hosting requires the durable database connection.')
if DATABASE_URL:
    import psycopg
    DB_ERRORS = (sqlite3.Error, psycopg.Error)
else:
    DB_ERRORS = (sqlite3.Error,)
MAX_BODY = 10 * 1024 * 1024
ATTEMPTS = {}
LOCK = threading.Lock()
RATE_CACHE = {}
RATE_LOCK = threading.Lock()


def currency_code(code):
    return isinstance(code, str) and re.fullmatch(r'[A-Z]{3}', code) is not None


def exchange_rate(code):
    if not currency_code(code):
        raise ValueError('Invalid currency')
    if code == 'CAD':
        return {'rate': 1, 'date': date.today().isoformat(), 'source': 'CAD'}
    with RATE_LOCK:
        cached = RATE_CACHE.get(code)
        if cached and time.time() - cached[0] < 6 * 3600:
            return cached[1]
        # Fixed provider host, currency code only; no personal trip data is sent.
        request = Request('https://api.frankfurter.dev/v2/rate/' + code + '/CAD', headers={'User-Agent': 'Dashboard-de-vacances/2.0', 'Accept': 'application/json'})
        with urlopen(request, timeout=10) as response:
            payload = json.loads(response.read(20000))
        if not numeric(payload.get('rate'), 1e-9, 1e6) or not good_date(payload.get('date')) or payload.get('base') != code or payload.get('quote') != 'CAD':
            raise ValueError('Invalid rate response')
        result = {'rate': payload['rate'], 'date': payload['date'], 'source': 'Frankfurter'}
        RATE_CACHE[code] = (time.time(), result)
        return result


CATEGORIES = {'lodging', 'transport', 'food', 'groceries', 'activities', 'shopping', 'fees', 'other'}
if CLOUD:
    if len(SECRET) < 32 or not ORIGIN.startswith('https://'):
        raise SystemExit('Hosted mode requires a session secret >=32 characters and an HTTPS origin.')
    parts = PASSWORD_HASH.split('$')
    if len(parts) != 4 or parts[0] != 'pbkdf2_sha256' or int(parts[1]) < 600000:
        raise SystemExit('Use password_hash.py to generate a password hash.')
    if DATABASE_URL:
        # The URL lives only in the host's private configuration. Never log it.
        with psycopg.connect(DATABASE_URL, connect_timeout=15) as db:
            db.execute('CREATE TABLE IF NOT EXISTS vacation_dashboard_state (id INTEGER PRIMARY KEY CHECK(id=1), revision BIGINT NOT NULL, data TEXT)')
            db.execute('INSERT INTO vacation_dashboard_state VALUES (1, 0, NULL) ON CONFLICT (id) DO NOTHING')
    else:
        DATA.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(DATA / 'cap-france.sqlite3') as db:
            db.execute('CREATE TABLE IF NOT EXISTS state (id INTEGER PRIMARY KEY CHECK(id=1), revision INTEGER NOT NULL, data TEXT)')
            db.execute('INSERT OR IGNORE INTO state VALUES (1, 0, NULL)')
        os.chmod(DATA / 'cap-france.sqlite3', 0o600)


def read_state(known_revision=None):
    if DATABASE_URL:
        with psycopg.connect(DATABASE_URL, connect_timeout=15) as db:
            if known_revision is not None:
                rev = db.execute('SELECT revision FROM vacation_dashboard_state WHERE id=1').fetchone()[0]
                if rev == known_revision:
                    return (rev, None)
            return db.execute('SELECT revision, data FROM vacation_dashboard_state WHERE id=1').fetchone()
    with sqlite3.connect(DATA / 'cap-france.sqlite3') as db:
        if known_revision is not None:
            rev = db.execute('SELECT revision FROM state WHERE id=1').fetchone()[0]
            if rev == known_revision:
                return (rev, None)
        return db.execute('SELECT revision, data FROM state WHERE id=1').fetchone()


def write_state(revision, encoded):
    """Atomic compare-and-swap: only one simultaneous writer can succeed."""
    if DATABASE_URL:
        with psycopg.connect(DATABASE_URL, connect_timeout=15) as db:
            row = db.execute('UPDATE vacation_dashboard_state SET revision=revision+1, data=%s WHERE id=1 AND revision=%s RETURNING revision', (encoded, revision)).fetchone()
            return row[0] if row else None
    with sqlite3.connect(DATA / 'cap-france.sqlite3', timeout=10) as db:
        db.execute('BEGIN IMMEDIATE')
        current = db.execute('SELECT revision FROM state WHERE id=1').fetchone()[0]
        if revision != current:
            return None
        db.execute('UPDATE state SET revision=?, data=? WHERE id=1', (current + 1, encoded))
        return current + 1


def numeric(value, lo=0, hi=100000000):
    return type(value) in (int, float) and math.isfinite(value) and lo <= value <= hi


def string(value, length):
    return isinstance(value, str) and len(value) <= length


def good_date(value):
    if not isinstance(value, str) or not re.fullmatch(r'\d{4}-\d{2}-\d{2}', value):
        return False
    try:
        return date.fromisoformat(value).isoformat() == value
    except ValueError:
        return False


def valid(data):
    if not isinstance(data, dict) or data.get('version') not in (1, 2):
        return False
    trips = data.get('trips')
    if not isinstance(trips, list) or not 1 <= len(trips) <= 100:
        return False
    ids = set()
    for t in trips:
        if not isinstance(t, dict) or not string(t.get('id'), 100) or t['id'] in ids or not string(t.get('name'), 100):
            return False
        ids.add(t['id'])
        if not good_date(t.get('start')) or not good_date(t.get('end')) or not 0 <= (date.fromisoformat(t['end']) - date.fromisoformat(t['start'])).days < 3660:
            return False
        if not (t.get('budget') is None or numeric(t.get('budget'))) or not numeric(t.get('rate'), 1e-9, 1e6) or not currency_code(t.get('currency', 'EUR')) or ('autoRate' in t and type(t['autoRate']) is not bool):
            return False
        if 'reminderDelay' in t and (type(t['reminderDelay']) is not int or not 0 <= t['reminderDelay'] <= 365):
            return False
        if 'reminderTime' in t and (not isinstance(t['reminderTime'], str) or not re.fullmatch(r'([01]\d|2[0-3]):[0-5]\d', t['reminderTime'])):
            return False
        es = t.get('expenses')
        if not isinstance(es, list) or len(es) > 20000:
            return False
        eids = set()
        for e in es:
            if not isinstance(e, dict) or not string(e.get('id'), 100) or e['id'] in eids:
                return False
            eids.add(e['id'])
            if not string(e.get('title'), 150) or not string(e.get('note'), 2000) or not string(e.get('method'), 100) or not good_date(e.get('date')):
                return False
            reminder = e.get('reminderAt')
            if reminder is not None:
                if not isinstance(reminder, str) or not re.fullmatch(r'\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z', reminder):
                    return False
                try:
                    from datetime import datetime
                    datetime.fromisoformat(reminder.replace('Z', '+00:00'))
                except ValueError:
                    return False
            if e.get('category') not in CATEGORIES or e.get('status') not in {'paid', 'planned', 'booked'} or e.get('kind') not in {'expense', 'refund'}:
                return False
            if not numeric(e.get('rate'), 1e-9, 1e6) or not numeric(e.get('share'), 0, 100) or not currency_code(e.get('currency', 'EUR')):
                return False
            if 'eur' not in e or 'cad' not in e or (e['eur'] is None and e['cad'] is None):
                return False
            if any(e[k] is not None and not numeric(e[k], 0, 10000000) for k in ['eur', 'cad']):
                return False
    if data.get('activeTrip') not in ids:
        return False
    rules = data.get('rules')
    if not isinstance(rules, dict) or len(rules) > 10000 or any(not string(k, 150) or v not in CATEGORIES for k, v in rules.items()):
        return False
    p = data.get('planner')
    if not isinstance(p, dict) or not string(p.get('name'), 100):
        return False
    if not (p.get('start') == '' or good_date(p.get('start'))) or not (p.get('end') == '' or good_date(p.get('end'))):
        return False
    if p['start'] and p['end'] and not 0 <= (date.fromisoformat(p['end']) - date.fromisoformat(p['start'])).days < 3660:
        return False
    if p.get('scenario') not in {'economy', 'comfort', 'generous'} or not (p.get('rate') is None or numeric(p['rate'], 1e-9, 1e6)) or not (p.get('currency') == '' or currency_code(p.get('currency', 'EUR'))):
        return False
    for key in ['lodging', 'food', 'groceries', 'transport', 'activities', 'shopping', 'flight', 'other', 'target']:
        if key not in p or not (p[key] is None or numeric(p[key])):
            return False
    return (p.get('margin') is None or numeric(p['margin'], 0, 100)) and (p.get('fee') is None or numeric(p['fee'], 0, 20)) and (p.get('travelers') is None or (type(p['travelers']) is int and 1 <= p['travelers'] <= 100))


def signature(token):
    return hmac.new(SECRET.encode(), token.encode(), hashlib.sha256).hexdigest()


class Handler(BaseHTTPRequestHandler):
    server_version = 'CapFrance'

    def log_message(self, fmt, *args):
        # No request bodies, passwords, cookies, query strings or financial data.
        pass

    def response(self, code, body, kind='application/json; charset=utf-8', cookie=None):
        encoded = body.encode() if isinstance(body, str) else body
        self.send_response(code)
        self.send_header('Content-Type', kind)
        self.send_header('Content-Length', str(len(encoded)))
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('X-Frame-Options', 'DENY')
        self.send_header('Referrer-Policy', 'no-referrer')
        self.send_header('Permissions-Policy', 'camera=(), microphone=(), geolocation=()')
        self.send_header('Content-Security-Policy', "default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'")
        if CLOUD:
            self.send_header('Strict-Transport-Security', 'max-age=31536000')
        if cookie:
            self.send_header('Set-Cookie', cookie)
        self.end_headers()
        self.wfile.write(encoded)

    def json_response(self, code, obj, cookie=None):
        self.response(code, json.dumps(obj, ensure_ascii=False, allow_nan=False), cookie=cookie)

    def authenticated(self):
        if not CLOUD:
            return False
        try:
            cookies = SimpleCookie(self.headers.get('Cookie', ''))
            token = cookies['cap_session'].value
            expiry, nonce, sig = token.split('.')
            signed = expiry + '.' + nonce
            return int(expiry) > time.time() and hmac.compare_digest(sig, signature(signed))
        except (KeyError, ValueError, AttributeError):
            return False

    def write_allowed(self):
        # Custom header + JSON blocks cross-site simple requests; exact Origin blocks CORS requests.
        origin = self.headers.get('Origin')
        expected = ORIGIN if CLOUD else 'http://' + self.headers.get('Host', '')
        return self.headers.get('X-Cap-France') == '1' and (origin is None or origin == expected)

    def read_json(self):
        if self.headers.get('Content-Type', '').split(';')[0] != 'application/json':
            raise ValueError('JSON required')
        length = int(self.headers.get('Content-Length', '0'))
        if length < 1 or length > MAX_BODY:
            raise ValueError('Invalid size')
        return json.loads(self.rfile.read(length), parse_constant=lambda x: (_ for _ in ()).throw(ValueError('Non-finite number')))

    def do_GET(self):
        path = urlsplit(self.path).path
        if path == '/api/config':
            return self.json_response(200, {'mode': 'cloud' if CLOUD else 'local'})
        if path == '/health':
            return self.json_response(200, {'ok': True})
        if path == '/api/rate':
            if CLOUD and not self.authenticated():
                return self.json_response(401, {'error': 'authentication_required'})
            code = parse_qs(urlsplit(self.path).query).get('currency', [''])[0]
            if not currency_code(code):
                return self.json_response(400, {'error': 'invalid_currency'})
            try:
                return self.json_response(200, exchange_rate(code))
            except (URLError, HTTPError, ValueError, OSError):
                return self.json_response(503, {'error': 'rate_unavailable'})
        if path == '/api/state':
            if not self.authenticated():
                return self.json_response(401, {'error': 'authentication_required'})
            query = parse_qs(urlsplit(self.path).query)
            known = query.get('revision', [''])[0]
            known_revision = int(known) if re.fullmatch(r'[0-9]{1,15}', known) else None
            try:
                row = read_state(known_revision)
            except DB_ERRORS:
                return self.json_response(503, {'error': 'storage_unavailable'})
            if known_revision is not None and known_revision == row[0]:
                return self.response(204, b'')
            return self.json_response(200, {'revision': row[0], 'data': json.loads(row[1]) if row[1] else None})
        assets = {'/favicon.svg': ('favicon.svg', 'image/svg+xml'), '/icon-192.png': ('icon-192.png', 'image/png'), '/icon-512.png': ('icon-512.png', 'image/png'), '/apple-touch-icon.png': ('apple-touch-icon.png', 'image/png'), '/manifest.webmanifest': ('manifest.webmanifest', 'application/manifest+json')}
        if path in assets:
            filename, mime = assets[path]
            return self.response(200, (ROOT / filename).read_bytes(), mime)
        if path in ('/', '/index.html'):
            return self.response(200, (ROOT / 'index.html').read_bytes(), 'text/html; charset=utf-8')
        return self.json_response(404, {'error': 'not_found'})

    def do_POST(self):
        path = urlsplit(self.path).path
        if not CLOUD or not self.write_allowed():
            return self.json_response(403, {'error': 'forbidden'})
        if path == '/api/logout':
            return self.json_response(200, {'ok': True}, 'cap_session=; Path=/; HttpOnly; Secure; SameSite=Strict; Max-Age=0')
        if path != '/api/login':
            return self.json_response(404, {'error': 'not_found'})
        # Small personal app: global limiter avoids reliance on untrusted proxy headers.
        with LOCK:
            now = time.time()
            attempts = [t for t in ATTEMPTS.get('login', []) if now - t < 300]
            if len(attempts) >= 10:
                return self.json_response(429, {'error': 'try_later'})
            attempts.append(now)
            ATTEMPTS['login'] = attempts
        try:
            payload = self.read_json()
            password = payload.get('password')
            if not isinstance(password, str) or len(password) > 1024:
                raise ValueError('Invalid password')
            algo, iterations, salt, expected = PASSWORD_HASH.split('$')
            actual = hashlib.pbkdf2_hmac('sha256', password.encode(), bytes.fromhex(salt), int(iterations)).hex()
            password = None
            if not hmac.compare_digest(actual, expected):
                return self.json_response(401, {'error': 'incorrect_password'})
            signed = str(int(time.time()) + 7 * 86400) + '.' + secrets.token_hex(24)
            cookie = 'cap_session=' + signed + '.' + signature(signed) + '; Path=/; HttpOnly; Secure; SameSite=Strict; Max-Age=604800'
            return self.json_response(200, {'ok': True}, cookie)
        except (ValueError, TypeError, AttributeError, json.JSONDecodeError):
            return self.json_response(400, {'error': 'invalid_request'})

    def do_PUT(self):
        if urlsplit(self.path).path != '/api/state':
            return self.json_response(404, {'error': 'not_found'})
        if not self.write_allowed():
            return self.json_response(403, {'error': 'forbidden'})
        if not self.authenticated():
            return self.json_response(401, {'error': 'authentication_required'})
        try:
            p = self.read_json()
            if not isinstance(p, dict) or type(p.get('revision')) is not int or p['revision'] < 0 or not valid(p.get('data')):
                raise ValueError('Invalid state')
            encoded = json.dumps(p['data'], ensure_ascii=False, allow_nan=False)
            revision = write_state(p['revision'], encoded)
            if revision is None:
                return self.json_response(409, {'error': 'revision_conflict'})
            return self.json_response(200, {'revision': revision})
        except (ValueError, TypeError, KeyError, AttributeError, json.JSONDecodeError):
            return self.json_response(400, {'error': 'invalid_data'})
        except DB_ERRORS:
            return self.json_response(503, {'error': 'storage_unavailable'})


if __name__ == '__main__':
    host = os.environ.get('HOST', '0.0.0.0' if CLOUD else '127.0.0.1')
    port = int(os.environ.get('PORT', '8765'))
    print('Dashboard de vacances ready (' + ('private hosted mode' if CLOUD else 'local preview') + ')', flush=True)
    ThreadingHTTPServer((host, port), Handler).serve_forever()
