from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import re
import secrets
import sqlite3
import time
import urllib.error
import urllib.request
from decimal import Decimal, InvalidOperation
from datetime import datetime, timezone
from pathlib import Path

from fastapi import BackgroundTasks, FastAPI, HTTPException, Request, Response
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, Field

BASE = Path(__file__).resolve().parent
DATA = Path(os.environ.get("STORE_DATA", "/var/lib/botconnector-store"))
DB = DATA / "store.db"
PRODUCTS = json.loads((BASE / "products.json").read_text(encoding="utf-8"))
PUBLIC_BASE = os.environ.get("PUBLIC_BASE", "https://botconnector.id").rstrip("/")
PAYMENT_MODE = os.environ.get("PAYMENT_MODE", "manual").lower()
MIDTRANS_ENV = os.environ.get("MIDTRANS_ENV", "sandbox").lower()
MIDTRANS_SERVER_KEY = os.environ.get("MIDTRANS_SERVER_KEY", "")
SELLER_URL = os.environ.get("SELLER_URL", "http://127.0.0.1:18192").rstrip("/")
SELLER_SECRET = os.environ.get("SELLER_SECRET", "")
ADMIN_SECRET = os.environ.get("STORE_ADMIN_SECRET", "")
COOKIE_SECRET = os.environ.get("STORE_COOKIE_SECRET", ADMIN_SECRET or "change-me")
TRIAL_AUTO = os.environ.get("TRIAL_AUTO_ISSUE", "1") == "1"
STORE_ENABLED = os.environ.get("STORE_ENABLED", "1") == "1"
MANUAL_PAYMENT_TEXT = os.environ.get(
    "MANUAL_PAYMENT_TEXT",
    "Pesanan menunggu pemeriksaan pembayaran oleh admin BotConnector.",
).strip()

DATA.mkdir(parents=True, exist_ok=True)
APP = FastAPI(title="BotConnector Store", docs_url=None, redoc_url=None, openapi_url=None)
APP.mount("/store/static", StaticFiles(directory=str(BASE / "static")), name="static")
TPL = Jinja2Templates(directory=str(BASE / "templates"))
EDITION_ORDER = ["Essential", "Lengkap", "Professional", "Multi Outlet"]
DEVICE_RE = re.compile(r"^[A-Z0-9]{16}$")
EMAIL_RE = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")
RATE: dict[str, list[float]] = {}


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def money(n: int) -> str:
    return "Rp" + f"{int(n):,}".replace(",", ".")


def license_type_label(value: str) -> str:
    return {"trial": "Uji Coba", "full": "Lisensi Penuh", "upgrade": "Peningkatan"}.get(value, value)


def payment_status_label(value: str) -> str:
    return {
        "pending": "Menunggu Pembayaran",
        "paid": "Lunas",
        "failed": "Gagal",
        "cancelled": "Dibatalkan",
        "expired": "Kedaluwarsa",
        "refunded": "Dikembalikan",
    }.get(value, value)


def fulfillment_status_label(value: str) -> str:
    return {"pending": "Menunggu", "issuing": "Diproses", "issued": "Kode Siap"}.get(value, value)


TPL.env.globals.update(
    money=money, edition_order=EDITION_ORDER, license_type_label=license_type_label,
    payment_status_label=payment_status_label, fulfillment_status_label=fulfillment_status_label,
)


def conn() -> sqlite3.Connection:
    c = sqlite3.connect(DB, timeout=10)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA journal_mode=WAL")
    c.execute("PRAGMA foreign_keys=ON")
    c.execute("PRAGMA busy_timeout=10000")
    return c


def init_db() -> None:
    with conn() as c:
        c.executescript(
            """
            CREATE TABLE IF NOT EXISTS orders(
              order_id TEXT PRIMARY KEY,
              access_hash TEXT NOT NULL,
              created_at TEXT NOT NULL,
              updated_at TEXT NOT NULL,
              product TEXT NOT NULL,
              edition TEXT NOT NULL,
              license_type TEXT NOT NULL,
              current_edition TEXT,
              customer TEXT NOT NULL,
              email TEXT NOT NULL,
              phone TEXT NOT NULL,
              device TEXT NOT NULL,
              amount INTEGER NOT NULL,
              payment_mode TEXT NOT NULL,
              payment_status TEXT NOT NULL,
              fulfillment_status TEXT NOT NULL,
              midtrans_redirect TEXT,
              midtrans_token TEXT,
              payment_ref TEXT,
              license_id TEXT,
              license_token TEXT,
              note TEXT,
              ip TEXT,
              paid_at TEXT,
              issued_at TEXT
            );
            CREATE INDEX IF NOT EXISTS idx_orders_created ON orders(created_at DESC);
            CREATE INDEX IF NOT EXISTS idx_orders_device ON orders(product,device);
            CREATE INDEX IF NOT EXISTS idx_orders_payment ON orders(payment_status,fulfillment_status);
            CREATE TABLE IF NOT EXISTS price_overrides(
              product TEXT NOT NULL,
              edition TEXT NOT NULL,
              price INTEGER NOT NULL,
              updated_at TEXT NOT NULL,
              PRIMARY KEY(product,edition)
            );
            CREATE TABLE IF NOT EXISTS events(
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              order_id TEXT,
              created_at TEXT NOT NULL,
              type TEXT NOT NULL,
              payload TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_events_order ON events(order_id,id DESC);
            """
        )
        cols = {r[1] for r in c.execute("PRAGMA table_info(orders)").fetchall()}
        for name in ("paid_at", "issued_at"):
            if name not in cols:
                c.execute(f"ALTER TABLE orders ADD COLUMN {name} TEXT")


init_db()


def event(order_id: str, typ: str, payload: dict) -> None:
    safe = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))[:12000]
    with conn() as c:
        c.execute(
            "INSERT INTO events(order_id,created_at,type,payload) VALUES(?,?,?,?)",
            (order_id, now_iso(), typ, safe),
        )


def client_ip(req: Request) -> str:
    # Uvicorn trusts only the local reverse proxy; X-Forwarded-For is therefore safe here.
    return req.headers.get("x-forwarded-for", "").split(",")[0].strip() or (
        req.client.host if req.client else "unknown"
    )


def allow(key: str, limit: int, window: int) -> bool:
    now = time.time()
    bucket = RATE.setdefault(key, [])
    bucket[:] = [t for t in bucket if now - t < window]
    if len(bucket) >= limit:
        return False
    bucket.append(now)
    return True


def product_view(slug: str) -> dict:
    p0 = PRODUCTS.get(slug)
    if not p0:
        raise HTTPException(404, "Produk tidak ditemukan")
    p = json.loads(json.dumps(p0))
    with conn() as c:
        rows = c.execute("SELECT edition,price FROM price_overrides WHERE product=?", (slug,)).fetchall()
    for row in rows:
        if row["edition"] in p["editions"]:
            p["editions"][row["edition"]]["price"] = int(row["price"])
    p["sellable_editions"] = [
        e for e in EDITION_ORDER if e in p["editions"] and p["editions"][e].get("sellable", True)
    ]
    if not p["sellable_editions"]:
        raise RuntimeError(f"Tidak ada paket aktif untuk {slug}")
    p["starting_price"] = min(p["editions"][e]["price"] for e in p["sellable_editions"])
    return p


def seller_request(path: str, body: dict, timeout: int = 8) -> dict:
    if not SELLER_SECRET:
        raise RuntimeError("SELLER_SECRET belum dikonfigurasi")
    req = urllib.request.Request(
        SELLER_URL + path,
        data=json.dumps(body, separators=(",", ":")).encode(),
        method="POST",
        headers={"Content-Type": "application/json", "X-Store-Secret": SELLER_SECRET},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        detail = e.read().decode(errors="replace")[:500]
        raise RuntimeError(f"Seller Control HTTP {e.code}: {detail}") from e
    except Exception as e:
        raise RuntimeError(f"Seller Control tidak tersedia: {e}") from e


def seller_status(product: str, device: str) -> dict:
    return seller_request("/api/store/status", {"product": product, "device": device}, timeout=6)


def seller_issue(product: str, license_type: str, edition: str, customer: str, device: str, note: str) -> dict:
    return seller_request(
        "/api/store/issue",
        {
            "product": product,
            "license_type": license_type,
            "edition": edition,
            "customer": customer,
            "device": device,
            "note": note,
        },
        timeout=10,
    )


def validate_order_against_seller(p: dict, license_type: str, edition: str, device: str) -> tuple[int, str | None]:
    if edition not in p["sellable_editions"]:
        raise HTTPException(400, "Paket belum tersedia untuk pembelian")
    try:
        status = seller_status(p["license_product"], device)
    except Exception:
        raise HTTPException(503, "Layanan aktivasi sedang tidak tersedia. Coba lagi sebentar.")

    current = status.get("current_edition") or None
    has_trial = bool(status.get("has_trial"))
    has_paid = bool(status.get("has_paid")) or bool(current)

    if license_type == "trial":
        if has_trial or has_paid:
            raise HTTPException(409, "Uji coba untuk perangkat ini sudah pernah digunakan atau sudah memiliki lisensi")
        return 0, None

    if license_type == "full":
        if has_paid:
            raise HTTPException(409, "Perangkat ini sudah memiliki lisensi. Gunakan pilihan peningkatan paket.")
        return int(p["editions"][edition]["price"]), None

    if license_type != "upgrade":
        raise HTTPException(400, "Jenis lisensi tidak valid")
    if not has_paid or not current or current not in p["editions"]:
        raise HTTPException(409, "Paket lisensi aktif pada perangkat ini tidak dapat dikenali untuk peningkatan")
    if EDITION_ORDER.index(current) >= EDITION_ORDER.index(edition):
        raise HTTPException(409, "Paket tujuan harus lebih tinggi dari paket yang aktif")
    if edition not in p["sellable_editions"]:
        raise HTTPException(400, "Paket tujuan belum tersedia")
    amount = max(0, int(p["editions"][edition]["price"]) - int(p["editions"][current]["price"]))
    return amount, current


def claim_fulfillment(order_id: str) -> tuple[sqlite3.Row | None, bool]:
    with conn() as c:
        c.execute("BEGIN IMMEDIATE")
        row = c.execute("SELECT * FROM orders WHERE order_id=?", (order_id,)).fetchone()
        if not row:
            return None, False
        if row["fulfillment_status"] == "issued":
            return row, False
        if row["fulfillment_status"] == "issuing":
            return row, False
        if row["payment_status"] != "paid" and row["license_type"] != "trial":
            raise RuntimeError("Pembayaran belum lunas")
        c.execute(
            "UPDATE orders SET fulfillment_status='issuing',updated_at=? WHERE order_id=?",
            (now_iso(), order_id),
        )
        return c.execute("SELECT * FROM orders WHERE order_id=?", (order_id,)).fetchone(), True


def fulfill(order_id: str) -> dict:
    row, claimed = claim_fulfillment(order_id)
    if not row:
        raise RuntimeError("Pesanan tidak ditemukan")
    if not claimed:
        return dict(row)

    p = product_view(row["product"])
    try:
        status = seller_status(p["license_product"], row["device"])
        current = status.get("current_edition") or None
        has_paid = bool(status.get("has_paid")) or bool(current)
        if row["license_type"] == "trial":
            if status.get("has_trial") or has_paid:
                raise RuntimeError("Perangkat sudah memiliki riwayat lisensi/uji coba")
        elif row["license_type"] == "full":
            if has_paid:
                raise RuntimeError("Perangkat sudah memiliki lisensi")
        elif row["license_type"] == "upgrade":
            if not current or current != row["current_edition"]:
                raise RuntimeError("Paket aktif berubah sejak pesanan dibuat; perlu pemeriksaan admin")
            if EDITION_ORDER.index(current) >= EDITION_ORDER.index(row["edition"]):
                raise RuntimeError("Paket tujuan tidak lebih tinggi dari lisensi aktif")

        result = seller_issue(
            p["license_product"],
            row["license_type"],
            row["edition"],
            row["customer"],
            row["device"],
            f"STORE {order_id}",
        )
        token = result.get("token") or result.get("license_token")
        if not token:
            raise RuntimeError("Seller Control tidak mengembalikan kode aktivasi")
        with conn() as c:
            c.execute(
                """UPDATE orders SET fulfillment_status='issued',license_id=?,license_token=?,issued_at=?,updated_at=?
                   WHERE order_id=?""",
                (str(result.get("license_id", "")), token, now_iso(), now_iso(), order_id),
            )
        event(order_id, "license_issued", {"license_id": result.get("license_id")})
    except Exception as e:
        with conn() as c:
            c.execute(
                "UPDATE orders SET fulfillment_status='pending',updated_at=? WHERE order_id=? AND fulfillment_status='issuing'",
                (now_iso(), order_id),
            )
        event(order_id, "fulfillment_error", {"error": str(e)[:800]})
        raise

    with conn() as c:
        final = c.execute("SELECT * FROM orders WHERE order_id=?", (order_id,)).fetchone()
    return dict(final)


def safe_fulfill(order_id: str) -> None:
    try:
        fulfill(order_id)
    except Exception:
        pass


def midtrans_create(order: dict) -> dict:
    if not MIDTRANS_SERVER_KEY:
        raise RuntimeError("MIDTRANS_SERVER_KEY belum dikonfigurasi")
    host = "https://app.midtrans.com" if MIDTRANS_ENV == "production" else "https://app.sandbox.midtrans.com"
    auth = base64.b64encode((MIDTRANS_SERVER_KEY + ":").encode()).decode()
    p = product_view(order["product"])
    plan_label = p["editions"][order["edition"]]["label"]
    payload = {
        "transaction_details": {"order_id": order["order_id"], "gross_amount": int(order["amount"])},
        "customer_details": {
            "first_name": order["customer"][:50],
            "email": order["email"],
            "phone": order["phone"],
        },
        "item_details": [
            {
                "id": f"{order['product']}-{order['edition']}",
                "price": int(order["amount"]),
                "quantity": 1,
                "name": f"{p['display_name']} - {plan_label}"[:50],
            }
        ],
        "callbacks": {"finish": f"{PUBLIC_BASE}/store/order/{order['order_id']}"},
    }
    req = urllib.request.Request(
        host + "/snap/v1/transactions",
        data=json.dumps(payload, separators=(",", ":")).encode(),
        method="POST",
        headers={
            "Authorization": "Basic " + auth,
            "Accept": "application/json",
            "Content-Type": "application/json",
            "X-Override-Notification": f"{PUBLIC_BASE}/store/api/payment/midtrans",
        },
    )
    with urllib.request.urlopen(req, timeout=15) as r:
        return json.loads(r.read().decode())


def access_cookie_ok(request: Request, row: sqlite3.Row) -> bool:
    token = request.cookies.get("bc_store_order", "")
    if not token:
        return False
    return hmac.compare_digest(hashlib.sha256(token.encode()).hexdigest(), row["access_hash"])


def admin_cookie_value() -> str:
    ts = str(int(time.time()))
    sig = hmac.new(COOKIE_SECRET.encode(), ts.encode(), hashlib.sha256).hexdigest()
    return ts + "." + sig


def require_admin(req: Request) -> None:
    val = req.cookies.get("bc_store_admin", "")
    try:
        ts, sig = val.split(".", 1)
        good = hmac.new(COOKIE_SECRET.encode(), ts.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(sig, good) or int(time.time()) - int(ts) > 43200:
            raise ValueError
    except Exception:
        raise HTTPException(401, "Admin login diperlukan")


def require_same_origin(req: Request) -> None:
    origin = req.headers.get("origin", "")
    if origin and origin.rstrip("/") != PUBLIC_BASE:
        raise HTTPException(403, "Origin tidak diizinkan")


class OrderIn(BaseModel):
    product: str
    edition: str
    license_type: str = Field(pattern="^(trial|full|upgrade)$")
    customer: str = Field(min_length=2, max_length=100)
    email: str = Field(min_length=5, max_length=160)
    phone: str = Field(min_length=8, max_length=30)
    device: str = Field(min_length=16, max_length=16)


class AdminLogin(BaseModel):
    secret: str


class AdminAction(BaseModel):
    action: str


class PriceIn(BaseModel):
    product: str
    edition: str
    price: int


@APP.middleware("http")
async def security_headers(request: Request, call_next):
    if not STORE_ENABLED and request.url.path != "/health":
        return JSONResponse({"detail": "Store sedang dalam pemeliharaan"}, status_code=503)
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=(), payment=()"
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; img-src 'self' data:; style-src 'self'; script-src 'self'; "
        "connect-src 'self'; frame-ancestors 'none'; base-uri 'self'; form-action 'self'"
    )
    if request.url.path.startswith(("/store/order/", "/store/admin/", "/store/api/")) or request.url.path == "/health":
        response.headers["Cache-Control"] = "no-store"
    return response


@APP.get("/health")
def health():
    return {
        "ok": True,
        "service": "botconnector-store",
        "release": "v6",
        "products": len(PRODUCTS),
        "payment_mode": PAYMENT_MODE,
    }


@APP.get("/store", include_in_schema=False)
def store_no_slash():
    return RedirectResponse("/store/", status_code=308)


@APP.get("/store/", response_class=HTMLResponse)
def home(request: Request):
    return TPL.TemplateResponse(
        request=request,
        name="home.html",
        context={
            "products": [product_view(k) for k in PRODUCTS],
            "title": "BotConnector Store",
            "canonical": f"{PUBLIC_BASE}/store/",
        },
    )


@APP.get("/store/panduan/", response_class=HTMLResponse)
def guide_page(request: Request):
    return TPL.TemplateResponse(
        request=request,
        name="guide.html",
        context={"title": "Panduan — BotConnector Store", "canonical": f"{PUBLIC_BASE}/store/panduan/"},
    )


@APP.get("/store/status/", response_class=HTMLResponse)
def status_page(request: Request):
    seller_ok = False
    try:
        req = urllib.request.Request(SELLER_URL + "/health", method="GET")
        with urllib.request.urlopen(req, timeout=2) as r:
            seller_ok = 200 <= r.status < 300
    except Exception:
        seller_ok = False
    return TPL.TemplateResponse(
        request=request,
        name="status.html",
        context={
            "title": "Status — BotConnector Store",
            "canonical": f"{PUBLIC_BASE}/store/status/",
            "seller_ok": seller_ok,
            "payment_mode": PAYMENT_MODE,
        },
    )


@APP.get("/store/admin/", response_class=HTMLResponse)
def admin_page(request: Request):
    return TPL.TemplateResponse(
        request=request,
        name="admin.html",
        context={"title": "Store Admin — BotConnector", "canonical": f"{PUBLIC_BASE}/store/admin/", "noindex": True},
    )


@APP.get("/store/{slug}/", response_class=HTMLResponse)
def product_page(request: Request, slug: str):
    if slug in {"admin", "api", "download", "order", "static", "panduan", "status"}:
        raise HTTPException(404, "Halaman tidak ditemukan")
    p = product_view(slug)
    return TPL.TemplateResponse(
        request=request,
        name="product.html",
        context={
            "p": p,
            "title": f"{p['display_name']} — BotConnector Store",
            "canonical": f"{PUBLIC_BASE}/store/{slug}/",
        },
    )


@APP.get("/store/download/{slug}.apk")
def download_apk(slug: str):
    p = product_view(slug)
    path = BASE / "static" / "downloads" / p["apk"]
    if not path.is_file():
        raise HTTPException(404, "APK tidak ditemukan")
    return FileResponse(
        path,
        filename=p["apk"],
        media_type="application/vnd.android.package-archive",
        headers={"Cache-Control": "public, max-age=3600"},
    )


@APP.get("/store/order/{order_id}", response_class=HTMLResponse)
def order_page(request: Request, order_id: str, background_tasks: BackgroundTasks):
    with conn() as c:
        row = c.execute("SELECT * FROM orders WHERE order_id=?", (order_id,)).fetchone()
    if not row or not access_cookie_ok(request, row):
        raise HTTPException(404, "Pesanan tidak ditemukan")
    if row["payment_status"] == "paid" and row["fulfillment_status"] == "pending":
        background_tasks.add_task(safe_fulfill, order_id)
    p = product_view(row["product"])
    return TPL.TemplateResponse(
        request=request,
        name="order.html",
        context={
            "order": dict(row),
            "product": p,
            "title": f"Pesanan {order_id} — BotConnector Store",
            "canonical": f"{PUBLIC_BASE}/store/order/{order_id}",
            "noindex": True,
            "manual_payment_text": MANUAL_PAYMENT_TEXT,
        },
    )


@APP.get("/store/order/{order_id}/status")
def order_status(request: Request, order_id: str, background_tasks: BackgroundTasks):
    with conn() as c:
        row = c.execute("SELECT * FROM orders WHERE order_id=?", (order_id,)).fetchone()
    if not row or not access_cookie_ok(request, row):
        raise HTTPException(404, "Pesanan tidak ditemukan")
    if row["payment_status"] == "paid" and row["fulfillment_status"] == "pending":
        background_tasks.add_task(safe_fulfill, order_id)
    return {
        "order_id": order_id,
        "payment_status": row["payment_status"],
        "fulfillment_status": row["fulfillment_status"],
        "amount": row["amount"],
        "amount_text": money(row["amount"]),
        "license_token": row["license_token"] if row["fulfillment_status"] == "issued" else None,
        "payment_url": row["midtrans_redirect"] if row["payment_status"] == "pending" else None,
    }


@APP.post("/store/api/order")
def create_order(inp: OrderIn, request: Request):
    require_same_origin(request)
    ip = client_ip(request)
    if not allow("order:" + ip, 12, 3600):
        raise HTTPException(429, "Terlalu banyak permintaan. Coba lagi nanti.")

    p = product_view(inp.product)
    device = inp.device.strip().upper()
    if not DEVICE_RE.fullmatch(device):
        raise HTTPException(400, "ID perangkat harus 16 karakter A-Z/0-9")
    email = inp.email.strip().lower()
    if not EMAIL_RE.fullmatch(email):
        raise HTTPException(400, "Email tidak valid")

    edition = p["trial_edition"] if inp.license_type == "trial" else inp.edition
    amount, current_edition = validate_order_against_seller(p, inp.license_type, edition, device)

    if inp.license_type != "trial" and PAYMENT_MODE not in {"manual", "midtrans"}:
        raise HTTPException(503, "Pembayaran belum diaktifkan")
    if inp.license_type != "trial" and PAYMENT_MODE == "midtrans" and not MIDTRANS_SERVER_KEY:
        raise HTTPException(503, "Pembayaran belum siap")

    order_id = "BC-" + datetime.now().strftime("%y%m%d") + "-" + secrets.token_hex(4).upper()
    token = secrets.token_urlsafe(32)
    access_hash = hashlib.sha256(token.encode()).hexdigest()
    is_trial = inp.license_type == "trial"
    mode = "free" if is_trial else PAYMENT_MODE
    now = now_iso()

    # Cegah beberapa transaksi aktif untuk perangkat dan produk yang sama.
    # Pesanan gagal/dibatalkan/kedaluwarsa tidak menghalangi transaksi baru.
    with conn() as c:
        active = c.execute(
            """SELECT order_id,payment_status,fulfillment_status FROM orders
               WHERE product=? AND device=?
                 AND payment_status IN ('pending','paid')
                 AND fulfillment_status!='issued'
               ORDER BY created_at DESC LIMIT 1""",
            (inp.product, device),
        ).fetchone()
    if active:
        raise HTTPException(
            409,
            f"Masih ada pesanan aktif untuk perangkat ini ({active['order_id']}). Selesaikan atau batalkan pesanan tersebut terlebih dahulu.",
        )

    with conn() as c:
        c.execute(
            """INSERT INTO orders(
               order_id,access_hash,created_at,updated_at,product,edition,license_type,current_edition,
               customer,email,phone,device,amount,payment_mode,payment_status,fulfillment_status,note,ip,paid_at
               ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                order_id,
                access_hash,
                now,
                now,
                inp.product,
                edition,
                inp.license_type,
                current_edition,
                inp.customer.strip(),
                email,
                inp.phone.strip(),
                device,
                amount,
                mode,
                "paid" if is_trial else "pending",
                "pending",
                "",
                ip,
                now if is_trial else None,
            ),
        )
    event(
        order_id,
        "order_created",
        {
            "product": inp.product,
            "edition": edition,
            "license_type": inp.license_type,
            "current_edition": current_edition,
            "amount": amount,
        },
    )

    payment_url = None
    if is_trial and TRIAL_AUTO:
        try:
            fulfill(order_id)
        except Exception as e:
            raise HTTPException(502, "Kode uji coba belum dapat diterbitkan. Pesanan tersimpan; coba muat status lagi.") from e
    elif PAYMENT_MODE == "midtrans":
        try:
            md = midtrans_create(
                {
                    "order_id": order_id,
                    "amount": amount,
                    "customer": inp.customer.strip(),
                    "email": email,
                    "phone": inp.phone.strip(),
                    "product": inp.product,
                    "edition": edition,
                }
            )
            payment_url = md.get("redirect_url")
            if not payment_url:
                raise RuntimeError("Midtrans tidak mengembalikan redirect_url")
            with conn() as c:
                c.execute(
                    "UPDATE orders SET midtrans_redirect=?,midtrans_token=?,updated_at=? WHERE order_id=?",
                    (payment_url, md.get("token"), now_iso(), order_id),
                )
        except Exception as e:
            event(order_id, "payment_create_error", {"error": str(e)[:800]})
            with conn() as c:
                c.execute("UPDATE orders SET payment_status='failed',updated_at=? WHERE order_id=?", (now_iso(), order_id))
            raise HTTPException(502, "Pembayaran belum dapat dibuat. Silakan coba lagi.")

    response = JSONResponse(
        {
            "ok": True,
            "order_id": order_id,
            "status_url": f"/store/order/{order_id}",
            "payment_url": payment_url,
            "amount": amount,
            "amount_text": money(amount),
            "payment_mode": mode,
            "current_edition": current_edition,
        }
    )
    response.set_cookie(
        "bc_store_order",
        token,
        httponly=True,
        secure=True,
        samesite="lax",
        max_age=60 * 60 * 24 * 30,
        path=f"/store/order/{order_id}",
    )
    return response


@APP.post("/store/api/payment/midtrans")
async def midtrans_notification(request: Request, background_tasks: BackgroundTasks):
    if not MIDTRANS_SERVER_KEY:
        raise HTTPException(503, "Midtrans belum aktif")
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(400, "JSON tidak valid")

    order_id = str(body.get("order_id", ""))
    status_code = str(body.get("status_code", ""))
    gross_amount = str(body.get("gross_amount", ""))
    signature = str(body.get("signature_key", ""))
    expected = hashlib.sha512((order_id + status_code + gross_amount + MIDTRANS_SERVER_KEY).encode()).hexdigest()
    if not signature or not hmac.compare_digest(expected, signature):
        raise HTTPException(403, "Signature tidak valid")

    with conn() as c:
        row = c.execute("SELECT * FROM orders WHERE order_id=?", (order_id,)).fetchone()
    if not row or row["payment_mode"] != "midtrans":
        raise HTTPException(404, "Pesanan tidak dikenal")

    try:
        notified_amount = Decimal(gross_amount)
    except InvalidOperation:
        raise HTTPException(400, "Nominal tidak valid")
    if notified_amount != Decimal(int(row["amount"])):
        event(order_id, "midtrans_amount_mismatch", {"gross_amount": gross_amount, "expected": row["amount"]})
        raise HTTPException(409, "Nominal pembayaran tidak sesuai")

    tx = str(body.get("transaction_status", "")).lower()
    fraud = str(body.get("fraud_status", "")).lower()
    paid = status_code == "200" and tx in {"settlement", "capture"} and fraud in {"", "accept"}
    terminal = {"deny": "failed", "cancel": "cancelled", "expire": "expired", "failure": "failed"}

    with conn() as c:
        current = c.execute("SELECT payment_status FROM orders WHERE order_id=?", (order_id,)).fetchone()[0]
        if paid and current != "paid":
            c.execute(
                "UPDATE orders SET payment_status='paid',payment_ref=?,paid_at=?,updated_at=? WHERE order_id=?",
                (str(body.get("transaction_id", "")), now_iso(), now_iso(), order_id),
            )
        elif tx in terminal and current != "paid":
            c.execute(
                "UPDATE orders SET payment_status=?,payment_ref=?,updated_at=? WHERE order_id=?",
                (terminal[tx], str(body.get("transaction_id", "")), now_iso(), order_id),
            )
        elif tx in {"refund", "partial_refund"}:
            c.execute(
                "UPDATE orders SET payment_status='refunded',payment_ref=?,updated_at=? WHERE order_id=?",
                (str(body.get("transaction_id", "")), now_iso(), order_id),
            )

    event(
        order_id,
        "midtrans_notification",
        {"transaction_status": tx, "status_code": status_code, "fraud_status": fraud},
    )
    if paid:
        background_tasks.add_task(safe_fulfill, order_id)
    return {"ok": True}


@APP.post("/store/api/admin/login")
def admin_login(inp: AdminLogin, response: Response, request: Request):
    require_same_origin(request)
    if not allow("admin-login:" + client_ip(request), 10, 3600):
        raise HTTPException(429, "Terlalu banyak percobaan login")
    if not ADMIN_SECRET or not hmac.compare_digest(inp.secret, ADMIN_SECRET):
        raise HTTPException(401, "Secret salah")
    response.set_cookie(
        "bc_store_admin",
        admin_cookie_value(),
        httponly=True,
        secure=True,
        samesite="strict",
        max_age=43200,
        path="/store/",
    )
    return {"ok": True}


@APP.post("/store/api/admin/logout")
def admin_logout(response: Response, request: Request):
    require_same_origin(request)
    response.delete_cookie("bc_store_admin", path="/store/")
    return {"ok": True}


@APP.get("/store/api/admin/orders")
def admin_orders(request: Request):
    require_admin(request)
    with conn() as c:
        rows = c.execute("SELECT * FROM orders ORDER BY created_at DESC LIMIT 300").fetchall()
    return [
        {k: v for k, v in dict(r).items() if k not in {"access_hash", "license_token", "midtrans_token"}}
        for r in rows
    ]


@APP.post("/store/api/admin/order/{order_id}")
def admin_action(order_id: str, inp: AdminAction, request: Request):
    require_same_origin(request)
    require_admin(request)
    with conn() as c:
        row = c.execute("SELECT * FROM orders WHERE order_id=?", (order_id,)).fetchone()
        if not row:
            raise HTTPException(404, "Pesanan tidak ditemukan")
        if inp.action == "mark_paid":
            if row["payment_mode"] != "manual":
                raise HTTPException(409, "Pembayaran Midtrans tidak boleh ditandai lunas secara manual")
            c.execute(
                "UPDATE orders SET payment_status='paid',paid_at=?,updated_at=? WHERE order_id=?",
                (now_iso(), now_iso(), order_id),
            )
        elif inp.action == "cancel":
            if row["payment_status"] == "paid":
                raise HTTPException(409, "Pesanan yang sudah lunas tidak dapat dibatalkan dari Store")
            c.execute("UPDATE orders SET payment_status='cancelled',updated_at=? WHERE order_id=?", (now_iso(), order_id))
        elif inp.action != "fulfill":
            raise HTTPException(400, "Aksi tidak dikenal")

    if inp.action in {"mark_paid", "fulfill"}:
        try:
            fulfill(order_id)
        except Exception as e:
            raise HTTPException(502, "Penerbitan lisensi gagal: " + str(e)[:300])
    event(order_id, "admin_action", {"action": inp.action})
    return {"ok": True}


@APP.get("/store/api/admin/prices")
def admin_prices(request: Request):
    require_admin(request)
    return {
        slug: {
            e: p["editions"][e]
            for e in p["sellable_editions"]
        }
        for slug in PRODUCTS
        for p in [product_view(slug)]
    }


@APP.post("/store/api/admin/price")
def admin_price(inp: PriceIn, request: Request):
    require_same_origin(request)
    require_admin(request)
    if inp.product not in PRODUCTS or inp.edition not in PRODUCTS[inp.product]["editions"] or inp.price < 1000:
        raise HTTPException(400, "Harga tidak valid")
    if not PRODUCTS[inp.product]["editions"][inp.edition].get("sellable", True):
        raise HTTPException(400, "Paket belum dijual di Store")
    with conn() as c:
        c.execute(
            """INSERT INTO price_overrides(product,edition,price,updated_at) VALUES(?,?,?,?)
               ON CONFLICT(product,edition) DO UPDATE SET price=excluded.price,updated_at=excluded.updated_at""",
            (inp.product, inp.edition, inp.price, now_iso()),
        )
    return {"ok": True, "price_text": money(inp.price)}
