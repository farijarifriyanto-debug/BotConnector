import asyncio
import hashlib
import ipaddress
import json
import os
import re
import secrets
import socket
import sqlite3
import threading
import time
from datetime import datetime, timezone
from typing import Any, Dict, Literal, Optional
from urllib.parse import urlparse

import httpx
from cryptography.fernet import Fernet, InvalidToken
from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, field_validator

APP_VERSION = "connector-core-v1-google-sheets-candidate"
DB_PATH = os.environ.get("BC_CONNECTOR_DB", "/var/lib/botconnector-connector-core/core.sqlite3")
MASTER_KEY_PATH = os.environ.get("BC_CONNECTOR_MASTER_KEY", "/etc/botconnector-connector-core/master.key")
PUBLIC_BASE_URL = os.environ.get("BC_PUBLIC_BASE_URL", "https://botconnector.id").rstrip("/")
MAX_BODY = int(os.environ.get("BC_MAX_BODY_BYTES", "262144"))
PORT = int(os.environ.get("BC_PORT", "18196"))
MAX_WEBHOOK_PER_MINUTE = int(os.environ.get("BC_WEBHOOK_RATE_PER_MINUTE", "60"))
HTTP_TIMEOUT = float(os.environ.get("BC_HTTP_TIMEOUT_SECONDS", "8"))

GOOGLE_SHEETS_BRIDGE_URL = os.environ.get(
    "BC_GOOGLE_SHEETS_BRIDGE_URL",
    "",
).rstrip("/")

GOOGLE_SHEETS_BRIDGE_SECRET = os.environ.get(
    "BC_GOOGLE_SHEETS_BRIDGE_SECRET",
    "",
)
HTTP_METHODS = {"POST", "PUT", "PATCH"}

app = FastAPI(
    title="BotConnector Connector Core",
    version="1.0.0",
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
)

_db_lock = threading.Lock()
_rate_lock = threading.Lock()
_rate: Dict[str, list[float]] = {}
_stop = threading.Event()
_worker_thread: Optional[threading.Thread] = None

def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()

def db() -> sqlite3.Connection:
    con = sqlite3.connect(DB_PATH, timeout=15, check_same_thread=False)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys=ON")
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("PRAGMA synchronous=NORMAL")
    return con

def init_db() -> None:
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    with db() as con:
        con.executescript("""
        CREATE TABLE IF NOT EXISTS workflows(
            id TEXT PRIMARY KEY,
            user_id TEXT NOT NULL,
            name TEXT NOT NULL,
            action_type TEXT NOT NULL,
            hook_token TEXT NOT NULL UNIQUE,
            encrypted_config BLOB NOT NULL,
            active INTEGER NOT NULL DEFAULT 1,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );

        CREATE INDEX IF NOT EXISTS idx_workflows_user
            ON workflows(user_id, created_at DESC);

        CREATE TABLE IF NOT EXISTS runs(
            id TEXT PRIMARY KEY,
            workflow_id TEXT NOT NULL,
            status TEXT NOT NULL,
            attempts INTEGER NOT NULL DEFAULT 0,
            http_status INTEGER,
            error TEXT,
            idempotency_key TEXT,
            created_at TEXT NOT NULL,
            finished_at TEXT,
            FOREIGN KEY(workflow_id) REFERENCES workflows(id) ON DELETE CASCADE
        );

        CREATE INDEX IF NOT EXISTS idx_runs_workflow
            ON runs(workflow_id, created_at DESC);

        CREATE UNIQUE INDEX IF NOT EXISTS uq_runs_idempotency
            ON runs(workflow_id, idempotency_key)
            WHERE idempotency_key IS NOT NULL;

        CREATE TABLE IF NOT EXISTS jobs(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            run_id TEXT NOT NULL UNIQUE,
            workflow_id TEXT NOT NULL,
            payload_json TEXT NOT NULL,
            attempts INTEGER NOT NULL DEFAULT 0,
            next_attempt_at REAL NOT NULL,
            FOREIGN KEY(run_id) REFERENCES runs(id) ON DELETE CASCADE,
            FOREIGN KEY(workflow_id) REFERENCES workflows(id) ON DELETE CASCADE
        );

        CREATE INDEX IF NOT EXISTS idx_jobs_due
            ON jobs(next_attempt_at, id);
        """)
        con.commit()

def load_fernet() -> Fernet:
    try:
        key = open(MASTER_KEY_PATH, "rb").read().strip()
        return Fernet(key)
    except Exception as exc:
        raise RuntimeError(f"master key unavailable: {exc}") from exc

FERNET: Optional[Fernet] = None

def encrypt_config(data: Dict[str, Any]) -> bytes:
    raw = json.dumps(data, ensure_ascii=False, separators=(",", ":")).encode()
    return FERNET.encrypt(raw)  # type: ignore[union-attr]

def decrypt_config(blob: bytes) -> Dict[str, Any]:
    try:
        raw = FERNET.decrypt(blob)  # type: ignore[union-attr]
        return json.loads(raw.decode())
    except (InvalidToken, json.JSONDecodeError) as exc:
        raise RuntimeError("credential decrypt failed") from exc

def require_user(x_botconnector_user_id: Optional[str]) -> str:
    uid = (x_botconnector_user_id or "").strip()
    if not uid:
        raise HTTPException(status_code=401, detail="Login BotConnector diperlukan")
    if len(uid) > 200:
        raise HTTPException(status_code=400, detail="Invalid user header")
    return uid

def public_workflow(row: sqlite3.Row) -> Dict[str, Any]:
    cfg = decrypt_config(row["encrypted_config"])
    display = {}
    if row["action_type"] == "telegram":
        display = {
            "chat_id": str(cfg.get("chat_id", "")),
            "template": cfg.get("message_template", ""),
        }
    elif row["action_type"] == "http":
        parsed = urlparse(str(cfg.get("url", "")))
        display = {
            "host": parsed.hostname or "",
            "method": cfg.get("method", "POST"),
        }
    return {
        "id": row["id"],
        "name": row["name"],
        "action_type": row["action_type"],
        "active": bool(row["active"]),
        "webhook_url": f"{PUBLIC_BASE_URL}/hook/{row['hook_token']}",
        "display": display,
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }

def lookup_public_ips(hostname: str) -> list[ipaddress._BaseAddress]:
    try:
        infos = socket.getaddrinfo(hostname, None, type=socket.SOCK_STREAM)
    except socket.gaierror as exc:
        raise ValueError("Hostname tujuan tidak dapat di-resolve") from exc
    ips = []
    for info in infos:
        ip = ipaddress.ip_address(info[4][0])
        if ip not in ips:
            ips.append(ip)
    if not ips:
        raise ValueError("Tidak ada IP untuk hostname tujuan")
    for ip in ips:
        if not ip.is_global:
            raise ValueError("Tujuan HTTP harus berada di jaringan publik")
    return ips

def validate_http_url(url: str) -> str:
    url = url.strip()
    if len(url) > 2000:
        raise ValueError("URL terlalu panjang")
    p = urlparse(url)
    if p.scheme != "https":
        raise ValueError("V1 hanya mengizinkan HTTPS untuk action HTTP")
    if not p.hostname:
        raise ValueError("Hostname tujuan wajib")
    if p.username or p.password:
        raise ValueError("Credential tidak boleh diletakkan di URL")
    if p.port not in (None, 443):
        raise ValueError("V1 hanya mengizinkan HTTPS port 443")
    lookup_public_ips(p.hostname)
    return url

SAFE_HEADER_NAME = re.compile(r"^[A-Za-z0-9!#$%&'*+\-.^_`|~]+$")

def validate_headers(headers: Dict[str, str]) -> Dict[str, str]:
    if len(headers) > 12:
        raise ValueError("Maksimal 12 header")
    blocked = {"host", "content-length", "transfer-encoding", "connection", "proxy-authorization"}
    clean = {}
    for k, v in headers.items():
        k = str(k).strip()
        v = str(v)
        if not SAFE_HEADER_NAME.match(k):
            raise ValueError(f"Nama header tidak valid: {k}")
        if k.lower() in blocked:
            raise ValueError(f"Header tidak diizinkan: {k}")
        if "\r" in v or "\n" in v or len(v) > 2000:
            raise ValueError(f"Nilai header tidak valid: {k}")
        clean[k] = v
    return clean

class TelegramConfig(BaseModel):
    bot_token: str = Field(min_length=20, max_length=300)
    chat_id: str = Field(min_length=1, max_length=100)
    message_template: str = Field(
        default="BotConnector menerima event:\n{{event}}",
        min_length=1,
        max_length=4096
    )

    @field_validator("bot_token")
    @classmethod
    def token_no_space(cls, v: str) -> str:
        v = v.strip()
        if any(c.isspace() for c in v):
            raise ValueError("Token Telegram tidak valid")
        return v

class HttpConfig(BaseModel):
    url: str
    method: Literal["POST", "PUT", "PATCH"] = "POST"
    headers: Dict[str, str] = Field(default_factory=dict)

    @field_validator("url")
    @classmethod
    def url_valid(cls, v: str) -> str:
        return validate_http_url(v)

    @field_validator("headers")
    @classmethod
    def headers_valid(cls, v: Dict[str, str]) -> Dict[str, str]:
        return validate_headers(v)

class GoogleSheetsConfig(BaseModel):
    spreadsheet_id: str = Field(
        min_length=20,
        max_length=200,
    )

    range: str = Field(
        min_length=1,
        max_length=200,
    )

    columns: list[str] = Field(
        min_length=1,
        max_length=50,
    )

    value_input_option: Literal[
        "RAW",
        "USER_ENTERED",
    ] = "USER_ENTERED"

    @field_validator("spreadsheet_id")
    @classmethod
    def validate_spreadsheet_id(cls, value: str) -> str:
        value = value.strip()

        if not re.fullmatch(
            r"[A-Za-z0-9_-]{20,200}",
            value,
        ):
            raise ValueError(
                "Spreadsheet ID tidak valid"
            )

        return value

    @field_validator("range")
    @classmethod
    def validate_range(cls, value: str) -> str:
        value = value.strip()

        if not value:
            raise ValueError(
                "Range Google Sheets wajib"
            )

        if any(
            ch in value
            for ch in ("\\r", "\\n", "\\x00")
        ):
            raise ValueError(
                "Range Google Sheets tidak valid"
            )

        return value

    @field_validator("columns")
    @classmethod
    def validate_columns(
        cls,
        value: list[str],
    ) -> list[str]:
        cleaned: list[str] = []

        for item in value:
            key = item.strip()

            if not re.fullmatch(
                r"[A-Za-z_][A-Za-z0-9_.-]{0,99}",
                key,
            ):
                raise ValueError(
                    "Nama kolom Google Sheets tidak valid"
                )

            cleaned.append(key)

        if len(set(cleaned)) != len(cleaned):
            raise ValueError(
                "Kolom Google Sheets tidak boleh duplikat"
            )

        return cleaned


class WorkflowCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    action_type: Literal["telegram", "http", "google_sheets"]
    telegram: Optional[TelegramConfig] = None
    http: Optional[HttpConfig] = None
    google_sheets: Optional[GoogleSheetsConfig] = None

    @field_validator("name")
    @classmethod
    def name_clean(cls, v: str) -> str:
        return " ".join(v.strip().split())

class ToggleRequest(BaseModel):
    active: bool

class TestRequest(BaseModel):
    payload: Any = Field(default_factory=lambda: {"nama": "Andi", "status": "uji", "total": 125000})

class TelegramDiscover(BaseModel):
    bot_token: str = Field(min_length=20, max_length=300)

def dotted_get(payload: Any, path: str) -> Any:
    if path in ("event", "payload"):
        return payload
    if path.startswith("event."):
        path = path[6:]
    current = payload
    for part in path.split("."):
        if isinstance(current, dict) and part in current:
            current = current[part]
        elif isinstance(current, list) and part.isdigit() and int(part) < len(current):
            current = current[int(part)]
        else:
            return ""
    return current

TPL_RE = re.compile(r"\{\{\s*([A-Za-z0-9_.-]+)\s*\}\}")

def render_template(template: str, payload: Any) -> str:
    def repl(m: re.Match) -> str:
        val = dotted_get(payload, m.group(1))
        if isinstance(val, (dict, list)):
            return json.dumps(val, ensure_ascii=False, separators=(",", ":"))
        return str(val)
    text = TPL_RE.sub(repl, template)
    if len(text) > 4096:
        text = text[:4090] + "…"
    return text

def allow_rate(token: str) -> bool:
    now = time.time()
    cutoff = now - 60
    with _rate_lock:
        arr = [x for x in _rate.get(token, []) if x >= cutoff]
        if len(arr) >= MAX_WEBHOOK_PER_MINUTE:
            _rate[token] = arr
            return False
        arr.append(now)
        _rate[token] = arr
        return True

async def telegram_api(token: str, method: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    url = f"https://api.telegram.org/bot{token}/{method}"
    try:
        async with httpx.AsyncClient(timeout=HTTP_TIMEOUT, follow_redirects=False, trust_env=False) as client:
            resp = await client.post(url, json=payload)
    except httpx.HTTPError as exc:
        # Never persist/log the request URL because it contains the bot token.
        raise RuntimeError("Telegram network error") from exc
    try:
        data = resp.json()
    except Exception:
        data = {"ok": False, "description": "Respons Telegram tidak valid"}
    if resp.status_code != 200 or not data.get("ok"):
        desc = str(data.get("description","gagal"))[:400]
        raise RuntimeError(f"Telegram {resp.status_code}: {desc}")
    return data

async def execute_telegram(cfg: Dict[str, Any], payload: Any) -> tuple[int, str]:
    text = render_template(cfg["message_template"], payload)
    await telegram_api(cfg["bot_token"], "sendMessage", {
        "chat_id": cfg["chat_id"],
        "text": text,
        "disable_web_page_preview": True,
    })
    return 200, "sent"

async def execute_http(cfg: Dict[str, Any], payload: Any) -> tuple[int, str]:
    url = validate_http_url(cfg["url"])
    headers = validate_headers(dict(cfg.get("headers") or {}))
    headers.setdefault("Content-Type", "application/json")
    headers.setdefault("User-Agent", "BotConnector/1.0")
    async with httpx.AsyncClient(timeout=HTTP_TIMEOUT, follow_redirects=False, trust_env=False) as client:
        resp = await client.request(cfg["method"], url, headers=headers, json=payload)
    if 200 <= resp.status_code < 300:
        return resp.status_code, "delivered"
    raise RuntimeError(f"HTTP tujuan mengembalikan {resp.status_code}")


def validate_google_sheets_bridge() -> None:
    if not GOOGLE_SHEETS_BRIDGE_URL:
        raise RuntimeError(
            "Google Sheets bridge URL unavailable"
        )

    if len(GOOGLE_SHEETS_BRIDGE_SECRET) < 32:
        raise RuntimeError(
            "Google Sheets bridge secret unavailable"
        )

    parsed = urlparse(
        GOOGLE_SHEETS_BRIDGE_URL
    )

    if (
        parsed.scheme != "http"
        or parsed.hostname != "127.0.0.1"
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
    ):
        raise RuntimeError(
            "Google Sheets bridge must use loopback HTTP"
        )


def google_sheet_cell(value: Any) -> Any:
    if value is None:
        return ""

    if isinstance(
        value,
        (str, int, float, bool),
    ):
        return value

    return json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
    )


async def execute_google_sheets(
    cfg: Dict[str, Any],
    payload: Any,
    user_id: str,
    run_id: str,
) -> tuple[int, str]:

    validate_google_sheets_bridge()

    if not isinstance(payload, dict):
        raise RuntimeError(
            "Google Sheets payload harus object"
        )

    columns = list(
        cfg.get("columns") or []
    )

    if not columns:
        raise RuntimeError(
            "Google Sheets columns kosong"
        )

    values = [
        google_sheet_cell(
            payload.get(column)
        )
        for column in columns
    ]

    body = {
        "operation": "append_row",
        "spreadsheet_id":
            cfg["spreadsheet_id"],
        "range":
            cfg["range"],
        "value_input_option":
            cfg.get(
                "value_input_option",
                "USER_ENTERED",
            ),
        "columns":
            columns,
        "values":
            values,
    }

    headers = {
        "Content-Type":
            "application/json",

        "User-Agent":
            "BotConnector-Connector-Core/1.0",

        "X-BC-Bridge-Secret":
            GOOGLE_SHEETS_BRIDGE_SECRET,

        # Ownership comes from the workflow row,
        # never from webhook payload.
        "X-BotConnector-User-ID":
            user_id,

        # Allows bridge-side idempotency.
        "X-BotConnector-Run-ID":
            run_id,
    }

    url = (
        GOOGLE_SHEETS_BRIDGE_URL
        + "/internal/google-sheets/append"
    )

    try:
        async with httpx.AsyncClient(
            timeout=HTTP_TIMEOUT,
            follow_redirects=False,
            trust_env=False,
        ) as client:
            response = await client.post(
                url,
                headers=headers,
                json=body,
            )

    except httpx.HTTPError as exc:
        raise RuntimeError(
            "Google Sheets bridge network error"
        ) from exc

    if 200 <= response.status_code < 300:
        return response.status_code, "appended"

    # Do not persist response body because it may contain
    # provider-specific details in a future bridge.
    raise RuntimeError(
        "Google Sheets bridge returned "
        + str(response.status_code)
    )


async def process_job(job: sqlite3.Row) -> None:
    with db() as con:
        wf = con.execute("SELECT * FROM workflows WHERE id=?", (job["workflow_id"],)).fetchone()
    if not wf:
        raise RuntimeError("Workflow tidak ditemukan")
    if not wf["active"]:
        raise RuntimeError("Workflow nonaktif")
    cfg = decrypt_config(wf["encrypted_config"])
    payload = json.loads(job["payload_json"])
    if wf["action_type"] == "telegram":
        code, _ = await execute_telegram(cfg, payload)
    elif wf["action_type"] == "http":
        code, _ = await execute_http(cfg, payload)
    elif wf["action_type"] == "google_sheets":
        code, _ = await execute_google_sheets(
            cfg,
            payload,
            str(wf["user_id"]),
            str(job["run_id"]),
        )
    else:
        raise RuntimeError("Action tidak dikenal")
    with db() as con:
        con.execute(
            "UPDATE runs SET status='success', attempts=?, http_status=?, error=NULL, finished_at=? WHERE id=?",
            (job["attempts"] + 1, code, utcnow(), job["run_id"])
        )
        con.execute("DELETE FROM jobs WHERE id=?", (job["id"],))
        con.commit()

async def worker_once() -> bool:
    now = time.time()
    with _db_lock:
        con = db()
        try:
            con.execute("BEGIN IMMEDIATE")
            job = con.execute(
                "SELECT * FROM jobs WHERE next_attempt_at<=? ORDER BY id LIMIT 1", (now,)
            ).fetchone()
            if not job:
                con.commit()
                return False
            # Reserve briefly so another loop cannot take the same job.
            con.execute("UPDATE jobs SET next_attempt_at=? WHERE id=?", (now + 30, job["id"]))
            con.commit()
        finally:
            con.close()

    try:
        await process_job(job)
    except Exception as exc:
        attempts = int(job["attempts"]) + 1
        err = str(exc)[:1000]
        with db() as con:
            if attempts >= 3:
                con.execute(
                    "UPDATE runs SET status='failed', attempts=?, error=?, finished_at=? WHERE id=?",
                    (attempts, err, utcnow(), job["run_id"])
                )
                con.execute("DELETE FROM jobs WHERE id=?", (job["id"],))
            else:
                delay = (2, 10, 30)[attempts - 1]
                con.execute(
                    "UPDATE jobs SET attempts=?, next_attempt_at=? WHERE id=?",
                    (attempts, time.time() + delay, job["id"])
                )
                con.execute(
                    "UPDATE runs SET status='retrying', attempts=?, error=? WHERE id=?",
                    (attempts, err, job["run_id"])
                )
            con.commit()
    return True

def worker_loop() -> None:
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    while not _stop.is_set():
        try:
            worked = loop.run_until_complete(worker_once())
            if not worked:
                _stop.wait(0.5)
        except Exception:
            _stop.wait(1.0)
    loop.close()

def enqueue(workflow_id: str, payload: Any, idempotency_key: Optional[str]) -> Dict[str, Any]:
    run_id = "run_" + secrets.token_urlsafe(12)
    payload_json = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    now = utcnow()
    with db() as con:
        if idempotency_key:
            existing = con.execute(
                "SELECT id,status FROM runs WHERE workflow_id=? AND idempotency_key=?",
                (workflow_id, idempotency_key)
            ).fetchone()
            if existing:
                return {"run_id": existing["id"], "status": existing["status"], "duplicate": True}
        try:
            con.execute(
                "INSERT INTO runs(id,workflow_id,status,idempotency_key,created_at) VALUES(?,?,?,?,?)",
                (run_id, workflow_id, "queued", idempotency_key, now)
            )
            con.execute(
                "INSERT INTO jobs(run_id,workflow_id,payload_json,next_attempt_at) VALUES(?,?,?,?)",
                (run_id, workflow_id, payload_json, time.time())
            )
            con.commit()
        except sqlite3.IntegrityError:
            if idempotency_key:
                existing = con.execute(
                    "SELECT id,status FROM runs WHERE workflow_id=? AND idempotency_key=?",
                    (workflow_id, idempotency_key)
                ).fetchone()
                if existing:
                    return {"run_id": existing["id"], "status": existing["status"], "duplicate": True}
            raise
    return {"run_id": run_id, "status": "queued", "duplicate": False}

@app.middleware("http")
async def product_header(request: Request, call_next):
    response = await call_next(request)
    response.headers["X-BotConnector-Connector-Core"] = APP_VERSION
    response.headers["X-Content-Type-Options"] = "nosniff"
    return response

@app.on_event("startup")
def startup() -> None:
    global FERNET, _worker_thread
    FERNET = load_fernet()
    validate_google_sheets_bridge()
    init_db()
    # Old payload jobs are required for retry, but a job never stores provider credentials.
    _stop.clear()
    _worker_thread = threading.Thread(target=worker_loop, name="connector-worker", daemon=True)
    _worker_thread.start()

@app.on_event("shutdown")
def shutdown() -> None:
    _stop.set()
    if _worker_thread:
        _worker_thread.join(timeout=3)

@app.get("/health")
def health():
    try:
        with db() as con:
            con.execute("SELECT 1").fetchone()
        return {"ok": True, "version": APP_VERSION, "queue": "sqlite"}
    except Exception as exc:
        return JSONResponse(status_code=503, content={"ok": False, "error": str(exc)})

@app.get("/api/workflows")
def list_workflows(x_botconnector_user_id: Optional[str] = Header(default=None)):
    uid = require_user(x_botconnector_user_id)
    with db() as con:
        rows = con.execute(
            "SELECT * FROM workflows WHERE user_id=? ORDER BY created_at DESC", (uid,)
        ).fetchall()
    return {"items": [public_workflow(r) for r in rows]}

@app.post("/api/workflows")
def create_workflow(body: WorkflowCreate, x_botconnector_user_id: Optional[str] = Header(default=None)):
    uid = require_user(x_botconnector_user_id)
    if body.action_type == "telegram":
        if not body.telegram:
            raise HTTPException(
                400,
                "Konfigurasi Telegram wajib",
            )
        cfg = body.telegram.model_dump()

    elif body.action_type == "http":
        if not body.http:
            raise HTTPException(
                400,
                "Konfigurasi HTTP wajib",
            )
        cfg = body.http.model_dump()

    elif body.action_type == "google_sheets":
        if not body.google_sheets:
            raise HTTPException(
                400,
                "Konfigurasi Google Sheets wajib",
            )
        cfg = body.google_sheets.model_dump()

    else:
        raise HTTPException(
            400,
            "Action tidak dikenal",
        )
    wf_id = "wf_" + secrets.token_urlsafe(10)
    hook_token = secrets.token_urlsafe(24)
    now = utcnow()
    with db() as con:
        con.execute(
            """INSERT INTO workflows
               (id,user_id,name,action_type,hook_token,encrypted_config,active,created_at,updated_at)
               VALUES(?,?,?,?,?,?,1,?,?)""",
            (wf_id, uid, body.name, body.action_type, hook_token, encrypt_config(cfg), now, now)
        )
        con.commit()
        row = con.execute("SELECT * FROM workflows WHERE id=?", (wf_id,)).fetchone()
    return public_workflow(row)

def owned_workflow(con: sqlite3.Connection, uid: str, wf_id: str) -> sqlite3.Row:
    row = con.execute(
        "SELECT * FROM workflows WHERE id=? AND user_id=?", (wf_id, uid)
    ).fetchone()
    if not row:
        raise HTTPException(404, "Workflow tidak ditemukan")
    return row

@app.post("/api/workflows/{wf_id}/toggle")
def toggle_workflow(wf_id: str, body: ToggleRequest, x_botconnector_user_id: Optional[str] = Header(default=None)):
    uid = require_user(x_botconnector_user_id)
    with db() as con:
        owned_workflow(con, uid, wf_id)
        con.execute(
            "UPDATE workflows SET active=?, updated_at=? WHERE id=?",
            (1 if body.active else 0, utcnow(), wf_id)
        )
        con.commit()
        row = con.execute("SELECT * FROM workflows WHERE id=?", (wf_id,)).fetchone()
    return public_workflow(row)

@app.delete("/api/workflows/{wf_id}")
def delete_workflow(wf_id: str, x_botconnector_user_id: Optional[str] = Header(default=None)):
    uid = require_user(x_botconnector_user_id)
    with db() as con:
        owned_workflow(con, uid, wf_id)
        con.execute("DELETE FROM workflows WHERE id=?", (wf_id,))
        con.commit()
    return {"ok": True}

@app.get("/api/workflows/{wf_id}/runs")
def list_runs(wf_id: str, x_botconnector_user_id: Optional[str] = Header(default=None)):
    uid = require_user(x_botconnector_user_id)
    with db() as con:
        owned_workflow(con, uid, wf_id)
        rows = con.execute(
            """SELECT id,status,attempts,http_status,error,idempotency_key,created_at,finished_at
               FROM runs WHERE workflow_id=? ORDER BY created_at DESC LIMIT 50""",
            (wf_id,)
        ).fetchall()
    return {"items": [dict(r) for r in rows]}

@app.post("/api/workflows/{wf_id}/test")
def test_workflow(wf_id: str, body: TestRequest, x_botconnector_user_id: Optional[str] = Header(default=None)):
    uid = require_user(x_botconnector_user_id)
    with db() as con:
        wf = owned_workflow(con, uid, wf_id)
        if not wf["active"]:
            raise HTTPException(409, "Aktifkan workflow sebelum test")
    return enqueue(wf_id, body.payload, "test-" + secrets.token_urlsafe(8))

@app.post("/api/telegram/discover")
async def discover_telegram(body: TelegramDiscover, x_botconnector_user_id: Optional[str] = Header(default=None)):
    require_user(x_botconnector_user_id)
    token = body.bot_token.strip()
    try:
        data = await telegram_api(token, "getUpdates", {"limit": 20, "timeout": 0})
    except Exception as exc:
        raise HTTPException(400, str(exc))
    chats: Dict[str, Dict[str, Any]] = {}
    for update in data.get("result", []):
        msg = update.get("message") or update.get("channel_post") or update.get("edited_message")
        if not isinstance(msg, dict):
            continue
        chat = msg.get("chat")
        if not isinstance(chat, dict) or "id" not in chat:
            continue
        cid = str(chat["id"])
        chats[cid] = {
            "id": cid,
            "type": chat.get("type"),
            "title": chat.get("title") or " ".join(
                x for x in [chat.get("first_name"), chat.get("last_name")] if x
            ) or chat.get("username") or cid,
            "username": chat.get("username"),
        }
    return {"items": list(chats.values())}

@app.post("/hook/{hook_token}")
async def receive_hook(hook_token: str, request: Request):
    if not allow_rate(hook_token):
        raise HTTPException(429, "Rate limit webhook tercapai")
    length = request.headers.get("content-length")
    if length and length.isdigit() and int(length) > MAX_BODY:
        raise HTTPException(413, "Payload terlalu besar")
    raw = await request.body()
    if len(raw) > MAX_BODY:
        raise HTTPException(413, "Payload terlalu besar")
    with db() as con:
        wf = con.execute(
            "SELECT * FROM workflows WHERE hook_token=?", (hook_token,)
        ).fetchone()
    if not wf or not wf["active"]:
        raise HTTPException(404, "Webhook tidak ditemukan")
    ctype = request.headers.get("content-type", "")
    try:
        if "application/json" in ctype:
            payload = json.loads(raw.decode("utf-8") or "{}")
        else:
            try:
                payload = json.loads(raw.decode("utf-8"))
            except Exception:
                payload = {"text": raw.decode("utf-8", errors="replace")}
    except Exception:
        raise HTTPException(400, "JSON tidak valid")

    idem = (
        request.headers.get("idempotency-key")
        or request.headers.get("x-idempotency-key")
        or request.headers.get("x-botconnector-event-id")
    )
    if idem:
        idem = idem.strip()[:200]
    result = enqueue(wf["id"], payload, idem)
    return JSONResponse(status_code=202 if not result["duplicate"] else 200, content=result)
