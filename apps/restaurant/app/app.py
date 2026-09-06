import base64
import csv
import hashlib
import hmac
import io
import json
import os
import secrets
import sqlite3
import time
from datetime import datetime, timezone, timedelta
from html import escape
from pathlib import Path

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from fastapi import FastAPI, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response

APP = FastAPI(title="Restaurant Seller Control", docs_url=None, redoc_url=None, openapi_url=None)
DB = Path(os.getenv("LICENSE_DB", "/data/licenses.db"))
KEY = Path(os.getenv("LICENSE_PRIVATE_KEY", "/run/secrets/license-private.pem"))
PASSWORD_HASH = os.getenv("SELLER_ADMIN_PASSWORD_HASH", "")
SESSION_SECRET = os.getenv("SELLER_SESSION_SECRET", "")
COOKIE_SECURE = os.getenv("COOKIE_SECURE", "0") == "1"
# RESTAURANT_SELLER_PANEL_V1
PANEL_MODE = os.getenv("PANEL_MODE", "0") == "1"
BASE_PATH = os.getenv("BASE_PATH", "").rstrip("/")
ED = ["Essential", "Lengkap", "Professional", "Multi Outlet"]
LOGIN_WINDOW = 300
LOGIN_MAX = 8
_login_attempts = {}

CSS = r'''<style>
:root{--bg:#f5f8f6;--card:#fff;--text:#152019;--muted:#6e7b72;--line:#e3eae5;--green:#179447;--green2:#e9f7ee;--red:#cf3f3f;--amber:#b7791f}
*{box-sizing:border-box}body{font-family:Inter,ui-sans-serif,system-ui,-apple-system,Segoe UI,Roboto,sans-serif;margin:0;background:var(--bg);color:var(--text)}
.wrap{max-width:1180px;margin:26px auto;padding:0 18px}.top{display:flex;justify-content:space-between;align-items:center;gap:16px;margin-bottom:14px}.brand h1{margin:0;font-size:26px}.muted{color:var(--muted)}
.card{background:var(--card);border:1px solid var(--line);border-radius:20px;padding:20px;margin-bottom:14px;box-shadow:0 8px 28px rgba(16,50,28,.04)}
.grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:14px}.grid3{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:12px}
label{font-size:12px;font-weight:800;display:block;margin:10px 0 6px}input,select,textarea{width:100%;padding:13px 14px;border:1px solid #d6e0d8;border-radius:12px;background:#fff;color:var(--text);outline:none}input:focus,select:focus,textarea:focus{border-color:#6dc68c;box-shadow:0 0 0 3px rgba(23,148,71,.10)}
button,.btn{display:inline-flex;align-items:center;justify-content:center;border:0;border-radius:12px;padding:12px 16px;font-weight:800;background:var(--green);color:#fff;text-decoration:none;cursor:pointer}.btn.secondary{background:#eef3ef;color:#203028}.btn.red{background:#fff0f0;color:var(--red);border:1px solid #f1caca}.btn.small{padding:8px 10px;font-size:12px}
.badge{display:inline-flex;padding:5px 9px;border-radius:999px;font-size:11px;font-weight:800;background:var(--green2);color:#176c37}.badge.revoked{background:#fff0f0;color:var(--red)}
.notice{padding:13px 15px;border-radius:12px;background:#eef8f1;border:1px solid #d8ecde}.token{font-family:ui-monospace,SFMono-Regular,Menlo,monospace;font-size:11px;line-height:1.55;word-break:break-all;background:#f6f8f7;border:1px solid var(--line);padding:14px;border-radius:12px}
table{width:100%;border-collapse:collapse;font-size:12px}td,th{padding:11px 9px;border-bottom:1px solid #edf1ee;text-align:left;vertical-align:top}th{color:#647168;font-size:11px;text-transform:uppercase;letter-spacing:.04em}.right{text-align:right}.row-actions{display:flex;gap:6px;flex-wrap:wrap}
.login{max-width:430px;margin:86px auto}.hero{background:linear-gradient(135deg,#ffffff 0%,#edf9f1 100%)}.stat{padding:16px;border-radius:15px;background:#f8fbf9;border:1px solid var(--line)}.stat b{display:block;font-size:24px;margin-top:4px}
@media(max-width:760px){.grid,.grid3{grid-template-columns:1fr}.top{align-items:flex-start;flex-direction:column}table{display:block;overflow-x:auto}.wrap{margin-top:14px}}
</style>'''

def utcnow():
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")

def conn():
    DB.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("PRAGMA foreign_keys=ON")
    con.execute('''CREATE TABLE IF NOT EXISTS licenses(
        license_id TEXT PRIMARY KEY,
        customer TEXT NOT NULL,
        edition TEXT NOT NULL,
        device TEXT NOT NULL,
        issued_at TEXT NOT NULL,
        revoked INTEGER NOT NULL DEFAULT 0,
        revoked_at TEXT,
        note TEXT NOT NULL DEFAULT '',
        token TEXT NOT NULL
    )''')
    con.execute("CREATE INDEX IF NOT EXISTS idx_licenses_device ON licenses(device)")
    con.execute("CREATE INDEX IF NOT EXISTS idx_licenses_issued ON licenses(issued_at DESC)")
    con.commit()
    return con

def b64u(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).decode().rstrip("=")

def hash_password(password: str, salt: bytes) -> str:
    dk = hashlib.scrypt(password.encode(), salt=salt, n=2**14, r=8, p=1, dklen=32)
    return base64.urlsafe_b64encode(dk).decode()

def verify_password(password: str) -> bool:
    try:
        alg, salt_b64, digest_b64 = PASSWORD_HASH.split("$", 2)
        if alg != "scrypt-v1":
            return False
        salt = base64.urlsafe_b64decode(salt_b64.encode())
        got = hash_password(password, salt)
        return hmac.compare_digest(got, digest_b64)
    except Exception:
        return False

def sign_session(ts: int, nonce: str) -> str:
    body = f"{ts}.{nonce}"
    sig = hmac.new(SESSION_SECRET.encode(), body.encode(), hashlib.sha256).hexdigest()
    return f"{body}.{sig}"

def valid_session(value: str) -> bool:
    try:
        ts_s, nonce, sig = value.split(".", 2)
        ts = int(ts_s)
        if time.time() - ts > 8 * 3600 or ts > time.time() + 60:
            return False
        expected = hmac.new(SESSION_SECRET.encode(), f"{ts}.{nonce}".encode(), hashlib.sha256).hexdigest()
        return hmac.compare_digest(sig, expected)
    except Exception:
        return False

def panel_cookie(req: Request) -> str:
    return req.cookies.get("bc_admin", "")

def authed(req: Request) -> bool:
    if PANEL_MODE:
        # Nginx validates bc_admin through the existing admin-gate before proxying here.
        return bool(panel_cookie(req))
    return valid_session(req.cookies.get("seller_session", ""))

def csrf_for(req: Request) -> str:
    session = panel_cookie(req) if PANEL_MODE else req.cookies.get("seller_session", "")
    return hmac.new(SESSION_SECRET.encode(), ("csrf:" + session).encode(), hashlib.sha256).hexdigest()

def u(path: str = "/") -> str:
    if not path.startswith("/"):
        path = "/" + path
    if path == "/":
        return (BASE_PATH + "/") if BASE_PATH else "/"
    return (BASE_PATH + path) if BASE_PATH else path

def verify_csrf(req: Request, token: str):
    if not authed(req) or not hmac.compare_digest(csrf_for(req), token or ""):
        raise HTTPException(403, "Sesi/CSRF tidak valid")

def page(body: str, title="Seller Control") -> HTMLResponse:
    return HTMLResponse(f'''<!doctype html><html lang="id"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>{escape(title)}</title>{CSS}</head><body><div class="wrap">{body}</div></body></html>''')

def rate_limit(ip: str):
    now = time.time()
    arr = [x for x in _login_attempts.get(ip, []) if now - x < LOGIN_WINDOW]
    if len(arr) >= LOGIN_MAX:
        raise HTTPException(429, "Terlalu banyak percobaan. Coba lagi beberapa menit lagi.")
    arr.append(now)
    _login_attempts[ip] = arr

def issue_token(customer: str, edition: str, device: str, note: str = ""):
    customer = customer.strip()
    device = "".join(ch for ch in device.strip().upper() if ch.isalnum())
    note = note.strip()
    if not customer or len(customer) > 100:
        raise ValueError("Nama customer tidak valid")
    if edition not in ED:
        raise ValueError("Paket tidak valid")
    if len(device) != 16:
        raise ValueError("ID perangkat harus 16 karakter")
    if not KEY.is_file():
        raise RuntimeError("Private key lisensi tidak ditemukan")
    lid = "LIC-" + secrets.token_hex(6).upper()
    at = utcnow()
    payload = {
        "v": 1, "license_id": lid, "customer": customer, "edition": edition,
        "device": device, "perpetual": True, "issued_at": at, "note": note
    }
    raw = json.dumps(payload, separators=(",", ":"), sort_keys=True, ensure_ascii=False).encode()
    priv = serialization.load_pem_private_key(KEY.read_bytes(), password=None)
    sig = priv.sign(raw, ec.ECDSA(hashes.SHA256()))
    token = "RAI1." + b64u(raw) + "." + b64u(sig)
    with conn() as con:
        con.execute('INSERT INTO licenses(license_id,customer,edition,device,issued_at,note,token) VALUES(?,?,?,?,?,?,?)',
                    (lid, customer, edition, device, at, note, token))
        con.commit()
    return lid, token

# BUSINESS_TRIAL_3D_V1
BUSINESS_TRIAL_SCOPE = "BUSINESS_SUITE_3"
BUSINESS_TRIAL_PRODUCTS = ["vehicle_wash", "workshop", "retail"]
BUSINESS_TRIAL_HOURS = 72

def issue_business_trial_token(customer: str, device: str, note: str = ""):
    customer = customer.strip()
    device = "".join(ch for ch in device.strip().upper() if ch.isalnum())
    note = note.strip()
    if not customer or len(customer) > 100:
        raise ValueError("Nama customer tidak valid")
    if len(device) != 16:
        raise ValueError("ID perangkat harus 16 karakter")
    if not KEY.is_file():
        raise RuntimeError("Private key lisensi tidak ditemukan")
    lid = "TRL-" + secrets.token_hex(6).upper()
    now = datetime.now(timezone.utc).replace(microsecond=0)
    exp = now + timedelta(hours=BUSINESS_TRIAL_HOURS)
    at = now.isoformat().replace("+00:00", "Z")
    expires_at = exp.isoformat().replace("+00:00", "Z")
    payload = {
        "v": 1,
        "license_id": lid,
        "customer": customer,
        "edition": "Essential",
        "device": device,
        "perpetual": True,
        "issued_at": at,
        "note": note,
        "trial": True,
        "trial_days": 3,
        "scope": BUSINESS_TRIAL_SCOPE,
        "products": BUSINESS_TRIAL_PRODUCTS,
        "expires_at": expires_at,
    }
    raw = json.dumps(payload, separators=(",", ":"), sort_keys=True, ensure_ascii=False).encode()
    priv = serialization.load_pem_private_key(KEY.read_bytes(), password=None)
    sig = priv.sign(raw, ec.ECDSA(hashes.SHA256()))
    token = "RAI1." + b64u(raw) + "." + b64u(sig)
    db_note = ("TRIAL 3 HARI BUSINESS SUITE; expires=" + expires_at + ("; " + note if note else ""))[:200]
    with conn() as con:
        con.execute(
            'INSERT INTO licenses(license_id,customer,edition,device,issued_at,note,token) VALUES(?,?,?,?,?,?,?)',
            (lid, customer, "TRIAL 3 HARI", device, at, db_note, token),
        )
        con.commit()
    return lid, token, expires_at

# UNIVERSAL_LICENSE_ENGINE_V1
UNIVERSAL_PRODUCTS = {
    "restaurant": "Restaurant",
    "vehicle_wash": "Vehicle Wash",
    "workshop": "Workshop",
    "retail": "Retail",
}
UNIVERSAL_LICENSE_TYPES = {
    "trial": "Trial 3 Hari",
    "full": "Full",
    "upgrade": "Upgrade",
}
UNIVERSAL_TRIAL_HOURS = 72

def issue_universal_token(customer: str, product: str, license_type: str, edition: str, device: str, note: str = ""):
    customer = customer.strip()
    product = product.strip().lower()
    license_type = license_type.strip().lower()
    edition = edition.strip()
    device = "".join(ch for ch in device.strip().upper() if ch.isalnum())
    note = note.strip()
    if not customer or len(customer) > 100:
        raise ValueError("Nama customer tidak valid")
    if product not in UNIVERSAL_PRODUCTS:
        raise ValueError("Produk tidak valid")
    if license_type not in UNIVERSAL_LICENSE_TYPES:
        raise ValueError("Jenis lisensi tidak valid")
    if edition not in ED:
        raise ValueError("Paket tidak valid")
    if len(device) != 16:
        raise ValueError("ID perangkat harus 16 karakter")
    if not KEY.is_file():
        raise RuntimeError("Private key lisensi tidak ditemukan")

    prefix = {"restaurant":"RST", "vehicle_wash":"VWH", "workshop":"WSH", "retail":"RTL"}[product]
    kind = {"trial":"TRL", "full":"FUL", "upgrade":"UPG"}[license_type]
    lid = f"{prefix}-{kind}-" + secrets.token_hex(5).upper()
    now = datetime.now(timezone.utc).replace(microsecond=0)
    at = now.isoformat().replace("+00:00", "Z")
    payload = {
        "v": 2,
        "license_id": lid,
        "customer": customer,
        "product": product,
        "license_type": license_type,
        "edition": edition,
        "device": device,
        # Native verifier keeps backward-compatible perpetual=true; JS Universal Engine
        # enforces trial expiry and upgrade semantics after cryptographic verification.
        "perpetual": True,
        "issued_at": at,
        "note": note,
    }
    expires_at = ""
    if license_type == "trial":
        exp = now + timedelta(hours=UNIVERSAL_TRIAL_HOURS)
        expires_at = exp.isoformat().replace("+00:00", "Z")
        payload.update({"trial_days": 3, "expires_at": expires_at})

    raw = json.dumps(payload, separators=(",", ":"), sort_keys=True, ensure_ascii=False).encode()
    priv = serialization.load_pem_private_key(KEY.read_bytes(), password=None)
    sig = priv.sign(raw, ec.ECDSA(hashes.SHA256()))
    token = "RAI1." + b64u(raw) + "." + b64u(sig)

    label = f"{UNIVERSAL_PRODUCTS[product]} | {UNIVERSAL_LICENSE_TYPES[license_type]} | {edition}"
    db_note = note
    if expires_at:
        db_note = (f"expires={expires_at}" + (f"; {note}" if note else ""))[:200]
    with conn() as con:
        con.execute(
            'INSERT INTO licenses(license_id,customer,edition,device,issued_at,note,token) VALUES(?,?,?,?,?,?,?)',
            (lid, customer, label, device, at, db_note, token),
        )
        con.commit()
    return lid, token, expires_at

# STORE_LICENSE_API_V1
@APP.post("/api/store/issue")
async def store_license_issue(request: Request):
    expected = __import__("os").environ.get("STORE_API_SECRET", "")
    supplied = request.headers.get("X-Store-Secret", "")
    if not expected or not secrets.compare_digest(supplied, expected):
        raise HTTPException(403, "Forbidden")
    try:
        body = await request.json()
        lid, token, expires_at = issue_universal_token(
            str(body.get("customer", "")),
            str(body.get("product", "")),
            str(body.get("license_type", "")),
            str(body.get("edition", "")),
            str(body.get("device", "")),
            str(body.get("note", "")),
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(400, str(e))
    return {"ok": True, "license_id": lid, "token": token, "expires_at": expires_at}

# STORE_LICENSE_API_V2
@APP.post("/api/store/status")
async def store_license_status(request: Request):
    expected = __import__("os").environ.get("STORE_API_SECRET", "")
    supplied = request.headers.get("X-Store-Secret", "")
    if not expected or not secrets.compare_digest(supplied, expected):
        raise HTTPException(403, "Forbidden")
    body = await request.json()
    product = str(body.get("product", "")).strip().lower()
    device = "".join(ch for ch in str(body.get("device", "")).strip().upper() if ch.isalnum())
    if product not in UNIVERSAL_PRODUCTS:
        raise HTTPException(400, "Produk tidak valid")
    if len(device) != 16:
        raise HTTPException(400, "ID perangkat harus 16 karakter")
    product_label = UNIVERSAL_PRODUCTS[product]
    levels = {"Essential":0,"Lengkap":1,"Professional":2,"Multi Outlet":3}
    has_trial = False
    current = None
    current_level = -1
    last_issued_at = None
    with conn() as con:
        rows = con.execute(
            "SELECT edition,issued_at FROM licenses WHERE device=? ORDER BY issued_at DESC",
            (device,),
        ).fetchall()
    for row in rows:
        label = str(row[0] or "")
        parts = [x.strip() for x in label.split("|")]
        if len(parts) < 3 or parts[0] != product_label:
            continue
        kind, edition = parts[1], parts[2]
        if last_issued_at is None:
            last_issued_at = str(row[1] or "")
        if kind == UNIVERSAL_LICENSE_TYPES.get("trial"):
            has_trial = True
            continue
        if kind in {UNIVERSAL_LICENSE_TYPES.get("full"), UNIVERSAL_LICENSE_TYPES.get("upgrade")} and edition in levels:
            if levels[edition] > current_level:
                current, current_level = edition, levels[edition]
    return {
        "ok": True,
        "product": product,
        "device": device,
        "has_trial": has_trial,
        "has_paid": current is not None,
        "current_edition": current,
        "last_issued_at": last_issued_at,
    }

@APP.get("/health")
def health():
    with conn() as con:
        con.execute("SELECT 1").fetchone()
    key_ok = KEY.is_file() and KEY.stat().st_size > 100
    return {"ok": key_ok, "service": "restaurant-seller-control", "db": True, "key": key_ok}

@APP.get("/", response_class=HTMLResponse)
def home(request: Request):
    if not authed(request):
        if PANEL_MODE:
            raise HTTPException(403, "Khusus admin")
        return page(f'''<div class="login card hero"><h2>Seller Control</h2><p class="muted">Masuk untuk membuat kode aktivasi aplikasi Restaurant All in One.</p><form method="post" action="{u('/login')}"><label>Password Admin</label><input type="password" name="password" autocomplete="current-password" required><br><br><button>MASUK</button></form></div>''')
    csrf = csrf_for(request)
    with conn() as con:
        rows = con.execute("SELECT * FROM licenses ORDER BY issued_at DESC LIMIT 300").fetchall()
        total = con.execute("SELECT COUNT(*) c FROM licenses").fetchone()[0]
        active = con.execute("SELECT COUNT(*) c FROM licenses WHERE revoked=0").fetchone()[0]
    tr = "".join(f'''<tr><td><b>{escape(r['license_id'])}</b><br><span class="muted">{escape(r['issued_at'])}</span></td><td>{escape(r['customer'])}</td><td>{escape(r['edition'])}</td><td><code>{escape(r['device'])}</code></td><td><span class="badge {'revoked' if r['revoked'] else ''}">{'Dicabut' if r['revoked'] else 'Aktif'}</span></td><td><div class="row-actions"><form method="post" action="{u('/show-token')}"><input type="hidden" name="csrf" value="{csrf}"><input type="hidden" name="license_id" value="{escape(r['license_id'])}"><button class="btn small secondary">Lihat kode</button></form>{'' if r['revoked'] else f'<form method="post" action="{u('/revoke')}" onsubmit="return confirm(\'Cabut lisensi ini dari daftar Seller Control?\')"><input type="hidden" name="csrf" value="{csrf}"><input type="hidden" name="license_id" value="{escape(r["license_id"])}"><button class="btn small red">Cabut</button></form>'}</div></td></tr>''' for r in rows)
    opts = "".join(f'<option>{escape(x)}</option>' for x in ED)
    return page(f'''<div class="top"><div class="brand"><h1>Application License Control</h1><div class="muted">Restaurant • Vehicle Wash • Workshop • Retail</div></div>{('<a class="btn secondary" href="/panel/">Kembali ke Panel</a>' if PANEL_MODE else f'<form method="post" action="{u('/logout')}"><input type="hidden" name="csrf" value="{csrf}"><button class="btn secondary">Keluar</button></form>')}</div>
<div class="card hero"><div class="grid3"><div class="stat">Total lisensi<b>{total}</b></div><div class="stat">Lisensi aktif<b>{active}</b></div><div class="stat">Paket tersedia<b>{len(ED)}</b></div></div></div>
<div class="card hero"><h2>Universal License Engine</h2><p class="muted">Pilih aplikasi dan jenis lisensi. <b>Trial → Full → Upgrade cukup memakai kode baru pada APK yang sama.</b></p><form method="post" action="{u('/issue-universal')}"><input type="hidden" name="csrf" value="{csrf}"><div class="grid"><div><label>Produk</label><select name="product"><option value="restaurant">Restaurant</option><option value="vehicle_wash">Vehicle Wash</option><option value="workshop">Workshop</option><option value="retail">Retail</option></select></div><div><label>Jenis Lisensi</label><select name="license_type"><option value="trial">Trial 3 Hari</option><option value="full">Full</option><option value="upgrade">Upgrade</option></select></div><div><label>Paket / Edition</label><select name="edition">{opts}</select></div><div><label>ID Perangkat</label><input name="device" maxlength="19" required placeholder="16 karakter dari aplikasi" autocapitalize="characters"></div><div style="grid-column:1/-1"><label>Nama Customer / Usaha</label><input name="customer" maxlength="100" required placeholder="Nama usaha / pemilik"></div><div style="grid-column:1/-1"><label>Catatan</label><input name="note" maxlength="200" placeholder="Opsional"></div></div><br><button>BUAT KODE LISENSI</button></form><div class="notice" style="margin-top:14px"><b>Penting:</b> ID perangkat berbeda untuk setiap aplikasi. Ambil ID dari aplikasi yang akan diaktifkan. Trial berlaku 72 jam sejak kode diterbitkan. Full bersifat permanen. Upgrade membuka paket yang sama atau lebih tinggi tanpa instal APK baru.</div></div>
<div class="card"><div class="top"><div><h2 style="margin:0">Riwayat Lisensi</h2><div class="muted">300 lisensi terbaru</div></div><a class="btn secondary" href="{u('/export.csv')}">Export CSV</a></div><table><thead><tr><th>Lisensi</th><th>Customer</th><th>Paket</th><th>Perangkat</th><th>Status</th><th>Aksi</th></tr></thead><tbody>{tr or '<tr><td colspan="6" class="muted">Belum ada lisensi.</td></tr>'}</tbody></table></div>''')

@APP.post("/login")
def login(request: Request, password: str = Form(...)):
    ip = request.client.host if request.client else "unknown"
    rate_limit(ip)
    if not PASSWORD_HASH or not SESSION_SECRET or not verify_password(password):
        raise HTTPException(403, "Password salah")
    _login_attempts.pop(ip, None)
    token = sign_session(int(time.time()), secrets.token_urlsafe(18))
    r = RedirectResponse(u("/"), 303)
    r.set_cookie("seller_session", token, httponly=True, samesite="strict", secure=COOKIE_SECURE, max_age=8*3600)
    return r

@APP.post("/logout")
def logout(request: Request, csrf: str = Form(...)):
    verify_csrf(request, csrf)
    r = RedirectResponse(u("/"), 303)
    r.delete_cookie("seller_session")
    return r

@APP.post("/issue", response_class=HTMLResponse)
def issue(request: Request, csrf: str = Form(...), customer: str = Form(...), edition: str = Form(...), device: str = Form(...), note: str = Form("")):
    verify_csrf(request, csrf)
    try:
        lid, token = issue_token(customer, edition, device, note)
    except Exception as e:
        raise HTTPException(400, str(e))
    return page(f'''<div class="card hero"><h2>Kode aktivasi berhasil dibuat</h2><p><b>{escape(lid)}</b> · {escape(customer)} · {escape(edition)}</p><div class="notice">Kirim kode ini hanya ke customer yang sesuai dengan ID perangkat tersebut.</div><br><div id="token" class="token">{escape(token)}</div><br><button onclick="navigator.clipboard.writeText(document.getElementById('token').innerText);this.innerText='TERSALIN ✓'">SALIN KODE</button> <a class="btn secondary" href="{u('/')}">KEMBALI</a></div>''', "Kode Aktivasi")

@APP.post("/issue-universal", response_class=HTMLResponse)
def issue_universal(request: Request, csrf: str = Form(...), customer: str = Form(...), product: str = Form(...), license_type: str = Form(...), edition: str = Form(...), device: str = Form(...), note: str = Form("")):
    verify_csrf(request, csrf)
    try:
        lid, token, expires_at = issue_universal_token(customer, product, license_type, edition, device, note)
    except Exception as e:
        raise HTTPException(400, str(e))
    product_label = UNIVERSAL_PRODUCTS[product]
    type_label = UNIVERSAL_LICENSE_TYPES[license_type]
    expiry = f'<br><b>Berakhir:</b> {escape(expires_at)}' if expires_at else ''
    return page(f"""<div class="card hero"><h2>Kode lisensi berhasil dibuat</h2><p><b>{escape(lid)}</b></p><div class="notice"><b>Produk:</b> {escape(product_label)}<br><b>Jenis:</b> {escape(type_label)}<br><b>Paket:</b> {escape(edition)}<br><b>Customer:</b> {escape(customer)}<br><b>ID Perangkat:</b> {escape("".join(ch for ch in device.upper() if ch.isalnum()))}{expiry}</div><br><div id="token" class="token">{escape(token)}</div><br><button onclick="navigator.clipboard.writeText(document.getElementById('token').innerText);this.innerText='TERSALIN ✓'">SALIN KODE</button> <a class="btn secondary" href="{u('/')}">KEMBALI</a></div>""", "Kode Lisensi")

@APP.post("/issue-trial", response_class=HTMLResponse)
def issue_trial(request: Request, csrf: str = Form(...), customer: str = Form(...), device: str = Form(...), note: str = Form("")):
    verify_csrf(request, csrf)
    try:
        lid, token, expires_at = issue_business_trial_token(customer, device, note)
    except Exception as e:
        raise HTTPException(400, str(e))
    return page(f'''<div class="card hero"><h2>Kode Trial 3 Hari berhasil dibuat</h2><p><b>{escape(lid)}</b> · {escape(customer)}</p><div class="notice"><b>Berlaku untuk:</b> Vehicle Wash, Workshop, dan Retail<br><b>Berakhir:</b> {escape(expires_at)} · 72 jam dari penerbitan</div><br><div id="token" class="token">{escape(token)}</div><br><button onclick="navigator.clipboard.writeText(document.getElementById('token').innerText);this.innerText='TERSALIN ✓'">SALIN KODE</button> <a class="btn secondary" href="{u('/')}">KEMBALI</a></div>''', "Trial 3 Hari")

@APP.post("/show-token", response_class=HTMLResponse)
def show_token(request: Request, csrf: str = Form(...), license_id: str = Form(...)):
    verify_csrf(request, csrf)
    with conn() as con:
        r = con.execute("SELECT * FROM licenses WHERE license_id=?", (license_id,)).fetchone()
    if not r:
        raise HTTPException(404)
    return page(f'''<div class="card"><h2>{escape(r['license_id'])}</h2><p>{escape(r['customer'])} · {escape(r['edition'])} · <code>{escape(r['device'])}</code></p><div id="token" class="token">{escape(r['token'])}</div><br><button onclick="navigator.clipboard.writeText(document.getElementById('token').innerText);this.innerText='TERSALIN ✓'">SALIN KODE</button> <a class="btn secondary" href="{u('/')}">KEMBALI</a></div>''')

@APP.post("/revoke")
def revoke(request: Request, csrf: str = Form(...), license_id: str = Form(...)):
    verify_csrf(request, csrf)
    with conn() as con:
        con.execute("UPDATE licenses SET revoked=1, revoked_at=? WHERE license_id=?", (utcnow(), license_id))
        con.commit()
    return RedirectResponse(u("/"), 303)

@APP.get("/export.csv")
def export_csv(request: Request):
    if not authed(request):
        raise HTTPException(403)
    with conn() as con:
        rows = con.execute("SELECT license_id,customer,edition,device,issued_at,revoked,revoked_at,note FROM licenses ORDER BY issued_at DESC").fetchall()
    out = io.StringIO()
    w = csv.writer(out)
    w.writerow(["license_id","customer","edition","device","issued_at","status","revoked_at","note"])
    for r in rows:
        w.writerow([r["license_id"], r["customer"], r["edition"], r["device"], r["issued_at"], "REVOKED" if r["revoked"] else "ACTIVE", r["revoked_at"] or "", r["note"]])
    return Response(out.getvalue(), media_type="text/csv", headers={"Content-Disposition":"attachment; filename=restaurant-licenses.csv"})
