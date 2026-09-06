"""
BotConnector Admin Gate — central admin identity + control panel.

Admin logs in with their REAL BotConnector account (email + password validated
by Core :8050/v1/auth/login). If the email is in the ADMIN_EMAILS allowlist, we
set a **domain-wide** signed cookie `bc_admin` (Domain=.botconnector.id) so EVERY
subdomain/app can see it. Any feature gates itself to admins by verifying that
cookie with the shared secret (copy `verify_admin`, or call GET /panel/check).
We never store the password — Core validates it; the allowlist decides who's admin.

The dashboard (GET /panel/) is a real admin control center: live AI-Gateway
monitoring + service health. Add more panels over time.

Env (~/admin-gate/.env): ADMIN_EMAILS, ADMIN_SECRET, CORE_LOGIN_URL, COOKIE_DOMAIN.
Served under /panel/ on botconnector.id (nginx strips the prefix).
"""
import asyncio
import base64
import hashlib
import hmac
import os
import time

import httpx
from fastapi import FastAPI, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse

ADMIN_EMAILS = {e.strip().lower() for e in os.environ.get("ADMIN_EMAILS", "").split(",") if e.strip()}
SECRET = os.environ.get("ADMIN_SECRET", "").encode()
CORE_LOGIN_URL = os.environ.get("CORE_LOGIN_URL", "http://127.0.0.1:8050/v1/auth/login")
COOKIE_DOMAIN = os.environ.get("COOKIE_DOMAIN", ".botconnector.id").strip()
GATEWAY = os.environ.get("GATEWAY_URL", "http://127.0.0.1:18130")
SUPPORT_MONITOR_URL = os.environ.get(
    "SUPPORT_MONITOR_URL",
    "http://127.0.0.1:8031/connect-v2/api/internal/support-email-status",
).strip()
SUPPORT_MONITOR_TOKEN = os.environ.get("SUPPORT_MONITOR_TOKEN", "").strip()
COOKIE = "bc_admin"

CORE_SESSION_COOKIE = "bc_session"

CORE_SESSION_TTL = 604800

CORE_API_BASE = (
    CORE_LOGIN_URL
    .rsplit(
        "/v1/auth/login",
        1,
    )[0]
    .rstrip("/")
)
TTL = 60 * 60 * 24 * 30

# name → health URL (any HTTP response = up)
# HPANEL_BUSINESS_DASHBOARD_V1
SERVICES = [
    ("Website", "http://127.0.0.1:8020/"),
    ("Hpanel / Admin Gate", "http://127.0.0.1:18160/health"),
    ("PowerPoint Studio", "http://127.0.0.1:18140/health"),
    ("AI Workspace", "http://127.0.0.1:18170/health"),
    ("Document Assistant", "http://127.0.0.1:8096/health"),
    ("Spreadsheet Assistant", "http://127.0.0.1:8100/health"),
    ("Document Intelligence", "http://127.0.0.1:8101/health"),
    ("BotConnector Connect", "http://127.0.0.1:8030/health"),
    ("AI Gateway", "http://127.0.0.1:18130/health"),
]

app = FastAPI(title="BotConnector Admin Gate", version="1.1.0")


# ── shared token helpers (COPY verify_admin into any app that needs gating) ──
def _sign(payload: str) -> str:
    return hmac.new(SECRET, payload.encode(), hashlib.sha256).hexdigest()


def issue(email: str) -> str:
    payload = f"{email}|{int(time.time()) + TTL}"
    b = base64.urlsafe_b64encode(payload.encode()).decode()
    return f"{b}.{_sign(payload)}"


def verify_admin(token: str) -> str | None:
    if not token or "." not in token or not SECRET:
        return None
    b, sig = token.rsplit(".", 1)
    try:
        payload = base64.urlsafe_b64decode(b.encode()).decode()
    except Exception:
        return None
    if not hmac.compare_digest(sig, _sign(payload)):
        return None
    email, _, exp = payload.partition("|")
    if not exp.isdigit() or int(exp) < time.time():
        return None
    return email


def current_admin(request: Request) -> str | None:
    return verify_admin(request.cookies.get(COOKIE, ""))


# HPANEL_STORAGE_QUOTA_V1
async def core_login_session(
    email: str,
    password: str,
) -> tuple[bool, str | None]:

    try:

        async with httpx.AsyncClient(
            timeout=12
        ) as client:

            response = await client.post(
                CORE_LOGIN_URL,
                json={
                    "email": email,
                    "password": password,
                },
            )


        if response.status_code != 200:
            return (
                False,
                None,
            )


        token = response.cookies.get(
            CORE_SESSION_COOKIE
        )


        if not token:

            for header in response.headers.get_list(
                "set-cookie"
            ):

                first = header.split(
                    ";",
                    1,
                )[0]

                key, sep, value = (
                    first.partition("=")
                )

                if (
                    sep
                    and key.strip()
                    == CORE_SESSION_COOKIE
                ):
                    token = value.strip()
                    break


        if not token:
            return (
                False,
                None,
            )


        return (
            True,
            token,
        )


    except Exception:

        return (
            False,
            None,
        )


async def core_login_ok(
    email: str,
    password: str,
) -> bool:

    ok, _ = await core_login_session(
        email,
        password,
    )

    return ok


def storage_csrf(
    email: str,
) -> str:

    if not SECRET:
        return ""

    return hmac.new(
        SECRET,
        (
            "storage-csrf|"
            + email.lower()
        ).encode(),
        hashlib.sha256,
    ).hexdigest()


async def core_json(
    method: str,
    endpoint: str,
    session_token: str,
    *,
    json_data: dict | None = None,
    csrf_token: str | None = None,
) -> dict:

    headers = {
        "Accept":
            "application/json",
    }


    if json_data is not None:

        headers[
            "Content-Type"
        ] = "application/json"


    if csrf_token:

        headers[
            "X-CSRF-Token"
        ] = csrf_token


    try:

        async with httpx.AsyncClient(
            timeout=20
        ) as client:

            response = await client.request(
                method,
                (
                    CORE_API_BASE
                    + "/"
                    + endpoint.lstrip("/")
                ),
                headers=headers,
                cookies={
                    CORE_SESSION_COOKIE:
                        session_token,
                },
                json=json_data,
            )


    except Exception:

        raise HTTPException(
            status_code=502,
            detail=(
                "Core BotConnector tidak "
                "dapat dihubungi."
            ),
        )


    if response.status_code >= 400:

        detail = None

        try:

            payload = response.json()

            if isinstance(
                payload,
                dict,
            ):

                value = payload.get(
                    "detail"
                )

                if isinstance(
                    value,
                    str,
                ):
                    detail = value

        except Exception:
            pass


        raise HTTPException(
            status_code=response.status_code,
            detail=(
                detail
                or (
                    "Permintaan Storage "
                    "tidak berhasil."
                )
            ),
        )


    try:

        payload = response.json()

    except Exception:

        raise HTTPException(
            status_code=502,
            detail=(
                "Respons Core tidak valid."
            ),
        )


    if not isinstance(
        payload,
        dict,
    ):
        raise HTTPException(
            status_code=502,
            detail=(
                "Respons Core tidak valid."
            ),
        )


    return payload


async def core_csrf_token(
    session_token: str,
) -> str:

    payload = await core_json(
        "GET",
        "/v1/me",
        session_token,
    )

    token = payload.get(
        "csrf_token"
    )

    if not isinstance(
        token,
        str,
    ) or not token:

        raise HTTPException(
            status_code=401,
            detail=(
                "Sesi keamanan Core "
                "tidak tersedia."
            ),
        )

    return token


# ── monitoring ──────────────────────────────────────────────────────────────
async def _ping(client, name, url):
    try:
        r = await client.get(url, timeout=5)
        code = r.status_code
        return {
            "name": name,
            "up": 200 <= code < 400,
            "code": code,
        }
    except Exception:
        return {
            "name": name,
            "up": False,
            "code": 0,
        }


def _read_business_metrics() -> dict:
    import json

    path = "/var/lib/hpanel-metrics/business.json"

    try:
        with open(
            path,
            "r",
            encoding="utf-8",
        ) as stream:
            data = json.load(stream)

        if not isinstance(data, dict):
            return {"ok": False}

        return data

    except Exception:
        return {"ok": False}


async def gather_overview() -> dict:
    async with httpx.AsyncClient() as c:
        svc = await asyncio.gather(*[_ping(c, n, u) for n, u in SERVICES])
        providers, stats = [], {}
        try:
            r = await c.get(f"{GATEWAY}/v1/providers/status", timeout=6)
            providers = r.json().get("providers", [])
        except Exception:
            pass
        try:
            r = await c.get(f"{GATEWAY}/v1/stats", timeout=6)
            stats = r.json().get("router", {})
        except Exception:
            pass
        # Provider status and counters are separate gateway contracts. Merge
        # them here so Hpanel can show accurate per-provider usage.
        by_provider = stats.get("by_provider", {}) if isinstance(stats, dict) else {}
        enriched_providers = []
        for provider in providers:
            if not isinstance(provider, dict):
                continue
            item = dict(provider)
            counters = by_provider.get(item.get("name"), {})
            if not isinstance(counters, dict):
                counters = {}
            item["usage_attempts"] = int(counters.get("attempts", 0) or 0)
            item["usage_success"] = int(counters.get("success", 0) or 0)
            item["usage_errors"] = int(counters.get("errors", 0) or 0)
            enriched_providers.append(item)
        providers = enriched_providers
        support_email = {
            "ok": False,
            "error": "monitor_not_configured",
        }
        if SUPPORT_MONITOR_URL and SUPPORT_MONITOR_TOKEN:
            try:
                r = await c.get(
                    SUPPORT_MONITOR_URL,
                    timeout=8,
                    headers={
                        "X-Panel-Monitor-Token": SUPPORT_MONITOR_TOKEN,
                        "Accept": "application/json",
                    },
                )
                if r.status_code == 200 and isinstance(r.json(), dict):
                    support_email = r.json()
                else:
                    support_email = {
                        "ok": False,
                        "error": f"monitor_http_{r.status_code}",
                    }
            except Exception as exc:
                support_email = {
                    "ok": False,
                    "error": type(exc).__name__,
                }
    business = await asyncio.to_thread(
        _read_business_metrics
    )

    return {
        "services": svc,
        "providers": providers,
        "stats": stats,
        "business": business,
        "support_email": support_email,
    }


# ── pages ───────────────────────────────────────────────────────────────────
# ============================================================
# HPANEL_CONSOLIDATED_V1
# UI only.
#
# Authentication, signing, cookies, routes, overview gathering,
# permissions, admin allowlist and service health logic remain
# outside this block and are intentionally untouched.
# ============================================================

CSS = """
<style>
:root {
  --bg: #f4f6f8;
  --surface: #ffffff;
  --surface-soft: #f8fafb;
  --sidebar: #10131a;
  --sidebar-soft: #181d27;
  --ink: #151922;
  --muted: #6d7480;
  --line: #e5e8ed;
  --brand: #6547ed;
  --brand-soft: #f0edff;
  --success: #18875f;
  --success-soft: #e9f7f1;
  --danger: #c93f4b;
  --danger-soft: #fff0f1;
  --warning: #aa7217;
  --warning-soft: #fff7e7;
  --shadow: 0 14px 42px rgba(20, 26, 38, .07);
  --radius: 18px;
}

* {
  box-sizing: border-box;
}

html {
  color-scheme: light;
}

body {
  margin: 0;
  color: var(--ink);
  background: var(--bg);
  font-family:
    Inter,
    ui-sans-serif,
    system-ui,
    -apple-system,
    BlinkMacSystemFont,
    "Segoe UI",
    sans-serif;
  -webkit-font-smoothing: antialiased;
}

button,
input,
a {
  font: inherit;
}

button,
a {
  -webkit-tap-highlight-color: transparent;
}

a {
  color: inherit;
}

button:focus-visible,
a:focus-visible,
input:focus-visible {
  outline: 3px solid rgba(101, 71, 237, .28);
  outline-offset: 3px;
}

.hp-brand-mark {
  display: grid;
  width: 40px;
  height: 40px;
  place-items: center;
  border-radius: 12px;
  color: white;
  background:
    linear-gradient(
      145deg,
      #7559ff,
      #5036d8
    );
  font-weight: 900;
  letter-spacing: -.04em;
}

.hp-button {
  min-height: 44px;
  padding: 0 17px;
  border: 0;
  border-radius: 11px;
  cursor: pointer;
  font-weight: 760;
  transition:
    transform .16s ease,
    background .16s ease,
    border-color .16s ease;
}

.hp-button:hover {
  transform: translateY(-1px);
}

.hp-button-primary {
  color: white;
  background: var(--brand);
}

.hp-button-primary:hover {
  background: #563bd9;
}

.hp-button-secondary {
  border: 1px solid var(--line);
  color: var(--ink);
  background: var(--surface);
}

.hp-button-danger {
  border: 1px solid #f0d5d8;
  color: #a52d38;
  background: #fff7f8;
}


/* ==========================================================
   LOGIN
   ========================================================== */

.hp-login-body {
  min-height: 100vh;
  display: grid;
  place-items: center;
  padding: 28px;
  background:
    radial-gradient(
      circle at 18% 10%,
      rgba(101, 71, 237, .16),
      transparent 34%
    ),
    radial-gradient(
      circle at 90% 90%,
      rgba(61, 180, 147, .10),
      transparent 30%
    ),
    #f7f8fb;
}

.hp-login-shell {
  width: min(100%, 980px);
  min-height: 600px;
  display: grid;
  grid-template-columns: 1.05fr .95fr;
  overflow: hidden;
  border: 1px solid rgba(34, 40, 55, .08);
  border-radius: 26px;
  background: var(--surface);
  box-shadow: 0 28px 80px rgba(28, 31, 42, .12);
}

.hp-login-brand {
  position: relative;
  padding: 50px;
  overflow: hidden;
  color: white;
  background:
    radial-gradient(
      circle at 100% 0,
      rgba(127, 101, 255, .44),
      transparent 38%
    ),
    linear-gradient(
      150deg,
      #111522,
      #171c2d
    );
}

.hp-login-brand::after {
  position: absolute;
  width: 320px;
  height: 320px;
  right: -120px;
  bottom: -150px;
  border: 1px solid rgba(255,255,255,.08);
  border-radius: 50%;
  content: "";
}

.hp-login-brand-head {
  display: flex;
  align-items: center;
  gap: 13px;
  font-size: 15px;
  font-weight: 850;
  letter-spacing: .04em;
}

.hp-login-copy {
  max-width: 440px;
  margin-top: 110px;
}

.hp-login-kicker {
  color: #a99cff;
  font-size: 12px;
  font-weight: 850;
  letter-spacing: .15em;
}

.hp-login-copy h1 {
  margin: 13px 0 16px;
  font-size: clamp(36px, 5vw, 56px);
  line-height: 1.02;
  letter-spacing: -.045em;
}

.hp-login-copy p {
  margin: 0;
  color: #b8bfce;
  font-size: 15px;
  line-height: 1.75;
}

.hp-login-form-wrap {
  display: flex;
  align-items: center;
  padding: 52px;
}

.hp-login-form {
  width: 100%;
}

.hp-login-form h2 {
  margin: 0;
  font-size: 28px;
  letter-spacing: -.025em;
}

.hp-login-form > p {
  margin: 9px 0 30px;
  color: var(--muted);
  font-size: 14px;
  line-height: 1.6;
}

.hp-field {
  margin-top: 18px;
}

.hp-field label {
  display: block;
  margin-bottom: 7px;
  font-size: 13px;
  font-weight: 740;
}

.hp-field input {
  width: 100%;
  min-height: 48px;
  padding: 0 14px;
  border: 1px solid #dfe3e9;
  border-radius: 11px;
  color: var(--ink);
  background: white;
  transition:
    border-color .15s ease,
    box-shadow .15s ease;
}

.hp-field input:focus {
  border-color: #8874ed;
  box-shadow: 0 0 0 4px rgba(101,71,237,.08);
  outline: 0;
}

.hp-login-submit {
  width: 100%;
  margin-top: 24px;
}

.hp-auth-error {
  margin: 0 0 18px;
  padding: 11px 13px;
  border: 1px solid #f2cfd3;
  border-radius: 10px;
  color: #a72c38;
  background: var(--danger-soft);
  font-size: 13px;
  line-height: 1.5;
}

.hp-login-security {
  margin-top: 20px;
  color: #858b95;
  font-size: 12px;
  line-height: 1.55;
}


/* ==========================================================
   DASHBOARD
   ========================================================== */

.hp-dashboard {
  min-height: 100vh;
  display: grid;
  grid-template-columns: 250px minmax(0, 1fr);
}

.hp-sidebar {
  position: sticky;
  top: 0;
  height: 100vh;
  display: flex;
  flex-direction: column;
  padding: 22px 18px;
  color: #d6dae4;
  background: var(--sidebar);
}

.hp-sidebar-brand {
  display: flex;
  align-items: center;
  gap: 11px;
  padding: 4px 7px 25px;
}

.hp-sidebar-brand strong {
  display: block;
  color: white;
  font-size: 14px;
  letter-spacing: .05em;
}

.hp-sidebar-brand small {
  display: block;
  margin-top: 2px;
  color: #7f8797;
  font-size: 11px;
}

.hp-nav-label {
  margin: 19px 10px 8px;
  color: #666e7d;
  font-size: 10px;
  font-weight: 850;
  letter-spacing: .14em;
}

.hp-nav {
  display: grid;
  gap: 4px;
}

.hp-nav a {
  min-height: 42px;
  display: flex;
  align-items: center;
  gap: 11px;
  padding: 0 11px;
  border-radius: 10px;
  color: #aeb5c3;
  text-decoration: none;
  font-size: 13px;
  font-weight: 680;
}

.hp-nav a:hover,
.hp-nav a.hp-active {
  color: white;
  background: var(--sidebar-soft);
}

.hp-nav-icon {
  width: 20px;
  color: #8e82dd;
  text-align: center;
}

.hp-sidebar-bottom {
  margin-top: auto;
  padding: 14px 7px 4px;
}

.hp-admin-mini {
  padding: 12px;
  border: 1px solid #272d39;
  border-radius: 12px;
  background: #151a23;
}

.hp-admin-mini strong {
  display: block;
  overflow: hidden;
  color: white;
  font-size: 12px;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.hp-admin-mini span {
  display: block;
  margin-top: 3px;
  color: #7e8797;
  font-size: 11px;
}

.hp-main {
  min-width: 0;
}

.hp-topbar {
  position: sticky;
  z-index: 20;
  top: 0;
  min-height: 70px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 18px;
  padding: 0 34px;
  border-bottom: 1px solid var(--line);
  background: rgba(255,255,255,.92);
  backdrop-filter: blur(14px);
}

.hp-topbar-title strong {
  display: block;
  font-size: 14px;
}

.hp-topbar-title span {
  display: block;
  margin-top: 2px;
  color: var(--muted);
  font-size: 11px;
}

.hp-topbar-actions {
  display: flex;
  align-items: center;
  gap: 10px;
}

.hp-content {
  width: min(100%, 1400px);
  margin: 0 auto;
  padding: 34px;
}

.hp-page-head {
  display: flex;
  align-items: end;
  justify-content: space-between;
  gap: 24px;
  margin-bottom: 26px;
}

.hp-page-head small {
  display: block;
  margin-bottom: 7px;
  color: var(--brand);
  font-size: 11px;
  font-weight: 850;
  letter-spacing: .13em;
}

.hp-page-head h1 {
  margin: 0;
  font-size: clamp(28px, 3.3vw, 40px);
  letter-spacing: -.035em;
}

.hp-page-head p {
  max-width: 580px;
  margin: 9px 0 0;
  color: var(--muted);
  font-size: 14px;
  line-height: 1.65;
}

.hp-live-pill {
  display: inline-flex;
  min-height: 32px;
  align-items: center;
  gap: 7px;
  padding: 0 11px;
  border-radius: 999px;
  color: var(--success);
  background: var(--success-soft);
  font-size: 12px;
  font-weight: 760;
}

.hp-live-dot {
  width: 7px;
  height: 7px;
  border-radius: 50%;
  background: #38a978;
  box-shadow: 0 0 0 4px rgba(56,169,120,.10);
}

.hp-kpi-grid {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 14px;
}

.hp-kpi {
  min-height: 126px;
  padding: 20px;
  border: 1px solid var(--line);
  border-radius: var(--radius);
  background: var(--surface);
  box-shadow: 0 5px 20px rgba(30,36,48,.035);
}

.hp-kpi-label {
  color: var(--muted);
  font-size: 12px;
  font-weight: 700;
}

.hp-kpi-value {
  margin-top: 13px;
  font-size: 27px;
  font-weight: 860;
  letter-spacing: -.035em;
}

.hp-kpi-foot {
  margin-top: 7px;
  color: #8a9099;
  font-size: 11px;
}

.hp-section {
  margin-top: 30px;
}

.hp-section-head {
  display: flex;
  align-items: end;
  justify-content: space-between;
  gap: 20px;
  margin-bottom: 14px;
}

.hp-section-head h2 {
  margin: 0;
  font-size: 19px;
  letter-spacing: -.015em;
}

.hp-section-head p {
  margin: 4px 0 0;
  color: var(--muted);
  font-size: 12px;
}

.hp-service-grid,
.hp-provider-grid,
.hp-access-grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 14px;
}

.hp-service-card,
.hp-provider-card,
.hp-access-card,
.hp-detail-panel {
  border: 1px solid var(--line);
  border-radius: var(--radius);
  background: var(--surface);
  box-shadow: 0 5px 20px rgba(30,36,48,.035);
}

.hp-service-card,
.hp-provider-card {
  min-height: 125px;
  padding: 18px;
}

.hp-card-head {
  display: flex;
  align-items: start;
  justify-content: space-between;
  gap: 12px;
}

.hp-card-name {
  min-width: 0;
  font-size: 14px;
  font-weight: 800;
}

.hp-status {
  display: inline-flex;
  min-height: 25px;
  align-items: center;
  padding: 0 8px;
  border-radius: 999px;
  font-size: 10px;
  font-weight: 800;
  white-space: nowrap;
}

.hp-status-ok {
  color: var(--success);
  background: var(--success-soft);
}

.hp-status-bad {
  color: var(--danger);
  background: var(--danger-soft);
}

.hp-status-warn {
  color: var(--warning);
  background: var(--warning-soft);
}

.hp-card-meta {
  margin-top: 14px;
  color: var(--muted);
  font-size: 12px;
  line-height: 1.55;
  word-break: break-word;
}

.hp-access-card {
  min-height: 128px;
  display: flex;
  flex-direction: column;
  padding: 18px;
  text-decoration: none;
  transition:
    transform .16s ease,
    border-color .16s ease,
    box-shadow .16s ease;
}

.hp-access-card:hover {
  transform: translateY(-2px);
  border-color: #cfc7f4;
  box-shadow: var(--shadow);
}

.hp-access-card strong {
  font-size: 14px;
}

.hp-access-card p {
  margin: 8px 0 18px;
  color: var(--muted);
  font-size: 12px;
  line-height: 1.55;
}

.hp-access-card span {
  margin-top: auto;
  color: var(--brand);
  font-size: 12px;
  font-weight: 800;
}

.hp-detail-panel {
  padding: 18px;
}

.hp-detail-grid {
  display: grid;
  grid-template-columns:
    repeat(4, minmax(0, 1fr));
  gap: 10px;
}

.hp-detail-item {
  min-width: 0;
  padding: 13px;
  border-radius: 11px;
  background: var(--surface-soft);
}

.hp-detail-item strong {
  display: block;
  overflow: hidden;
  font-size: 11px;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.hp-detail-item span {
  display: block;
  margin-top: 5px;
  overflow-wrap: anywhere;
  color: var(--muted);
  font-size: 11px;
}

.hp-empty {
  grid-column: 1 / -1;
  padding: 24px;
  border: 1px dashed #d8dce3;
  border-radius: 14px;
  color: var(--muted);
  text-align: center;
  font-size: 12px;
}

.hp-error-box {
  margin-bottom: 18px;
  padding: 12px 14px;
  border: 1px solid #f0d2d6;
  border-radius: 11px;
  color: #a72f3a;
  background: var(--danger-soft);
  font-size: 12px;
}

.hp-hidden {
  display: none !important;
}

@media (max-width: 1120px) {
  .hp-kpi-grid {
    grid-template-columns:
      repeat(2, minmax(0, 1fr));
  }

  .hp-service-grid,
  .hp-provider-grid,
  .hp-access-grid {
    grid-template-columns:
      repeat(2, minmax(0, 1fr));
  }

  .hp-detail-grid {
    grid-template-columns:
      repeat(2, minmax(0, 1fr));
  }
}

@media (max-width: 820px) {
  .hp-dashboard {
    display: block;
  }

  .hp-sidebar {
    position: static;
    width: 100%;
    height: auto;
    padding: 12px 15px;
  }

  .hp-sidebar-brand {
    padding: 0 3px 12px;
  }

  .hp-nav-label {
    display: none;
  }

  .hp-nav {
    display: flex;
    gap: 6px;
    overflow-x: auto;
    padding-bottom: 4px;
  }

  .hp-nav a {
    flex: 0 0 auto;
  }

  .hp-sidebar-bottom {
    display: none;
  }

  .hp-topbar {
    top: 0;
    min-height: 62px;
    padding: 0 18px;
  }

  .hp-content {
    padding: 25px 18px 40px;
  }

  .hp-page-head {
    display: block;
  }

  .hp-page-head .hp-live-pill {
    margin-top: 16px;
  }
}

@media (max-width: 620px) {
  .hp-login-body {
    padding: 14px;
  }

  .hp-login-shell {
    min-height: 0;
    grid-template-columns: 1fr;
    border-radius: 20px;
  }

  .hp-login-brand {
    padding: 28px;
  }

  .hp-login-copy {
    margin-top: 48px;
  }

  .hp-login-copy h1 {
    font-size: 36px;
  }

  .hp-login-form-wrap {
    padding: 30px 24px;
  }

  .hp-kpi-grid,
  .hp-service-grid,
  .hp-provider-grid,
  .hp-access-grid,
  .hp-detail-grid {
    grid-template-columns: 1fr;
  }

  .hp-topbar-title span {
    display: none;
  }

  .hp-topbar-actions .hp-button-secondary {
    display: none;
  }

  .hp-section {
    margin-top: 24px;
  }
}

@media (prefers-reduced-motion: reduce) {
  *,
  *::before,
  *::after {
    scroll-behavior: auto !important;
    transition: none !important;
  }
}


/* HPANEL_STORAGE_QUOTA_V1 */

.hp-storage-toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 14px;
  margin: 16px 0;
}

.hp-storage-search {
  width: min(100%, 320px);
  min-height: 40px;
  padding: 0 12px;
  border: 1px solid var(--line);
  border-radius: 10px;
  background: white;
  color: var(--text);
  font: inherit;
}

.hp-storage-summary {
  display: grid;
  grid-template-columns:
    repeat(3, minmax(0, 1fr));
  gap: 12px;
  margin-top: 18px;
}

.hp-storage-summary-card {
  padding: 16px;
  border: 1px solid var(--line);
  border-radius: 14px;
  background: white;
}

.hp-storage-summary-card span {
  display: block;
  color: var(--muted);
  font-size: 11px;
  font-weight: 700;
}

.hp-storage-summary-card strong {
  display: block;
  margin-top: 5px;
  font-size: 20px;
}

.hp-storage-table-wrap {
  overflow: auto;
  border: 1px solid var(--line);
  border-radius: 14px;
  background: white;
}

.hp-storage-table {
  width: 100%;
  min-width: 1050px;
  border-collapse: collapse;
}

.hp-storage-table th,
.hp-storage-table td {
  padding: 13px 14px;
  border-bottom: 1px solid var(--line);
  text-align: left;
  vertical-align: middle;
}

.hp-storage-table th {
  color: var(--muted);
  background: #f8f9fb;
  font-size: 10px;
  letter-spacing: .06em;
  text-transform: uppercase;
}

.hp-storage-user strong {
  display: block;
  font-size: 12px;
}

.hp-storage-user span,
.hp-storage-sub {
  display: block;
  margin-top: 3px;
  color: var(--muted);
  font-size: 11px;
}

.hp-storage-progress {
  width: 110px;
  height: 7px;
  overflow: hidden;
  border-radius: 99px;
  background: #e8ebf0;
}

.hp-storage-progress i {
  display: block;
  height: 100%;
  border-radius: inherit;
  background: #6558d3;
}

.hp-storage-form {
  display: flex;
  align-items: center;
  gap: 6px;
  flex-wrap: wrap;
}

.hp-storage-select,
.hp-storage-custom {
  min-height: 34px;
  padding: 0 8px;
  border: 1px solid var(--line);
  border-radius: 8px;
  background: white;
  color: var(--text);
  font: inherit;
  font-size: 12px;
}

.hp-storage-custom {
  width: 85px;
}

.hp-storage-message {
  margin: 12px 0;
  padding: 12px 14px;
  border-radius: 10px;
  background: #eef3ff;
  color: #334155;
  font-size: 12px;
}

.hp-storage-message.hp-error {
  background: #fff0f0;
  color: #a33a3a;
}

.hp-support-status-grid {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 14px;
}

.hp-support-attention {
  display: grid;
  gap: 10px;
  margin-top: 16px;
}

.hp-support-item {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  padding: 14px 16px;
  border: 1px solid var(--line);
  border-radius: 13px;
  background: var(--surface-soft);
}

.hp-support-item strong,
.hp-support-item span {
  display: block;
}

.hp-support-item span {
  margin-top: 4px;
  color: var(--muted);
  font-size: 12px;
}

@media (max-width: 820px) {
  .hp-support-status-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  .hp-support-item {
    align-items: flex-start;
    flex-direction: column;
  }
  .hp-storage-summary {
    grid-template-columns: 1fr;
  }

  .hp-storage-toolbar {
    align-items: stretch;
    flex-direction: column;
  }

  .hp-storage-search {
    width: 100%;
  }
}

</style>
"""


def login_form(err: str = "") -> str:
    safe_err = (
        err.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )

    error_html = (
        '<div class="hp-auth-error" role="alert">'
        + safe_err
        + "</div>"
        if safe_err
        else ""
    )

    return (
        """<!doctype html>
<html lang="id">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="robots" content="noindex,nofollow">
<title>BotConnector · Hpanel</title>
"""
        + CSS
        + """
</head>
<body class="hp-login-body">
<!-- HPANEL_CONSOLIDATED_V1 -->
<main class="hp-login-shell">
  <section class="hp-login-brand">
    <div class="hp-login-brand-head">
      <span class="hp-brand-mark" aria-hidden="true">BC</span>
      <span>BOTCONNECTOR</span>
    </div>

    <div class="hp-login-copy">
      <div class="hp-login-kicker">ADMIN CONTROL CENTER</div>
      <h1>Hpanel</h1>
      <p>
        Pusat kendali internal BotConnector untuk memantau
        layanan, AI Gateway, provider, dan akses aplikasi admin.
      </p>
    </div>
  </section>

  <section class="hp-login-form-wrap">
    <form
      class="hp-login-form"
      method="post"
      action="login"
    >
      <h2>Masuk sebagai admin</h2>

      <p>
        Gunakan akun BotConnector yang memiliki akses admin.
      </p>
"""
        + error_html
        + """
      <div class="hp-field">
        <label for="hp-email">Email</label>
        <input
          id="hp-email"
          type="email"
          name="email"
          autocomplete="username"
          inputmode="email"
          required
        >
      </div>

      <div class="hp-field">
        <label for="hp-password">Password</label>
        <input
          id="hp-password"
          type="password"
          name="password"
          autocomplete="current-password"
          required
        >
      </div>

      <button
        class="hp-button hp-button-primary hp-login-submit"
        type="submit"
      >
        Masuk ke Hpanel
      </button>

      <div class="hp-login-security">
        Akses ini khusus administrator.
        Sesi admin tetap menggunakan mekanisme keamanan
        BotConnector yang sudah berjalan.
      </div>
    </form>
  </section>
</main>
</body>
</html>"""
    )


def dashboard(email: str) -> str:
    safe_email = (
        email.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )

    return (
        """<!doctype html>
<html lang="id">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="robots" content="noindex,nofollow">
<title>BotConnector · Hpanel</title>
"""
        + CSS
        + """
</head>

<body>
<!-- HPANEL_CONSOLIDATED_V1 -->

<div class="hp-dashboard">

  <aside class="hp-sidebar">
    <div class="hp-sidebar-brand">
      <span class="hp-brand-mark" aria-hidden="true">BC</span>

      <div>
        <strong>BOTCONNECTOR</strong>
        <small>Hpanel</small>
      </div>
    </div>

    <div class="hp-nav-label">CONTROL CENTER</div>

    <nav class="hp-nav" aria-label="Navigasi Hpanel">
      <a class="hp-active" href="#overview">
        <span class="hp-nav-icon" aria-hidden="true">⌂</span>
        Overview
      </a>

      <a href="#services">
        <span class="hp-nav-icon" aria-hidden="true">◈</span>
        Layanan
      </a>
      <a href="#support-email">
        <span class="hp-nav-icon" aria-hidden="true">@</span>
        Help Email
      </a>

      <a href="#providers">
        <span class="hp-nav-icon" aria-hidden="true">AI</span>
        Provider AI
      </a>

      <a href="#applications">
        <span class="hp-nav-icon" aria-hidden="true">↗</span>
        Aplikasi
      </a>

      <a href="#storage">
        <span class="hp-nav-icon" aria-hidden="true">▣</span>
        Storage &amp; Quota
      </a>

      <a href="/">
        <span class="hp-nav-icon" aria-hidden="true">←</span>
        Home
      </a>
          <!-- RESTAURANT_SELLER_NAV_V1 -->
      <a href="/panel/restaurant/">
        <span class="hp-nav-icon" aria-hidden="true">▣</span>
        Restaurant
      </a>
</nav>

    <div class="hp-sidebar-bottom">
      <div class="hp-admin-mini">
        <strong>"""
        + safe_email
        + """</strong>
        <span>Administrator aktif</span>
      </div>
    </div>
  </aside>


  <main class="hp-main">

    <header class="hp-topbar">
      <div class="hp-topbar-title">
        <strong>Hpanel</strong>
        <span>BotConnector Administration</span>
      </div>

      <div class="hp-topbar-actions">

        <button
          id="hp-refresh"
          class="hp-button hp-button-secondary"
          type="button"
        >
          Refresh status
        </button>

        <form
          method="post"
          action="logout"
        >
          <button
            class="hp-button hp-button-danger"
            type="submit"
          >
            Keluar
          </button>
        </form>

      </div>
    </header>


    <div class="hp-content">

      <section
        id="overview"
        class="hp-page-head"
      >
        <div>
          <small>ADMIN CONTROL CENTER</small>

          <h1>Overview</h1>

          <p>
            Pantau status layanan BotConnector dan buka
            aplikasi internal dari satu tempat.
          </p>
        </div>

        <div class="hp-live-pill">
          <span class="hp-live-dot" aria-hidden="true"></span>
          <span id="hp-overall-state">Memuat status</span>
        </div>
      </section>


      <div
        id="hp-load-error"
        class="hp-error-box hp-hidden"
        role="alert"
      ></div>


      <section
        class="hp-kpi-grid"
        aria-label="Ringkasan platform"
      >

        <article class="hp-kpi">
          <div class="hp-kpi-label">Total Akun</div>
          <div
            id="hp-account-total"
            class="hp-kpi-value"
          >—</div>
          <div class="hp-kpi-foot">
            <span id="hp-account-active">—</span> aktif
            ·
            <span id="hp-account-verified">—</span> terverifikasi
          </div>
        </article>

        <article class="hp-kpi">
          <div class="hp-kpi-label">Pendaftar Hari Ini</div>
          <div
            id="hp-registered-today"
            class="hp-kpi-value"
          >—</div>
          <div class="hp-kpi-foot">
            <span id="hp-registered-7d">—</span>
            registrasi / 7 hari
          </div>
        </article>

        <article class="hp-kpi">
          <div class="hp-kpi-label">Login Hari Ini</div>
          <div
            id="hp-login-today"
            class="hp-kpi-value"
          >—</div>
          <div class="hp-kpi-foot">
            <span id="hp-login-7d">—</span>
            akun login / 7 hari
          </div>
        </article>

        <article class="hp-kpi">
          <div class="hp-kpi-label">Pengunjung Hari Ini</div>
          <div
            id="hp-visitors-today"
            class="hp-kpi-value"
          >—</div>
          <div class="hp-kpi-foot">
            Estimasi browser unik ·
            <span id="hp-visitors-3d">—</span>
            / 3 hari
          </div>
        </article>

        <article class="hp-kpi">
          <div class="hp-kpi-label">Page View Hari Ini</div>
          <div
            id="hp-pageviews-today"
            class="hp-kpi-value"
          >—</div>
          <div class="hp-kpi-foot">
            <span id="hp-pageviews-3d">—</span>
            page view / 3 hari
          </div>
        </article>

        <article class="hp-kpi">
          <div class="hp-kpi-label">Layanan Aktif</div>
          <div
            id="hp-services-up"
            class="hp-kpi-value"
          >—</div>
          <div class="hp-kpi-foot">
            Dari
            <span id="hp-services-total">—</span>
            layanan dipantau
          </div>
        </article>

        <article class="hp-kpi">
          <div class="hp-kpi-label">Provider AI</div>
          <div
            id="hp-provider-total"
            class="hp-kpi-value"
          >—</div>
          <div class="hp-kpi-foot">
            Provider yang terdeteksi
          </div>
        </article>

        <article class="hp-kpi">
          <div class="hp-kpi-label">Terakhir Diperbarui</div>
          <div
            id="hp-updated"
            class="hp-kpi-value"
            style="font-size:17px"
          >—</div>
          <div class="hp-kpi-foot">
            Status dari /overview
          </div>
        </article>

      </section>


      <section
        id="support-email"
        class="hp-section"
      >
        <div class="hp-section-head">
          <div>
            <h2>Notifikasi Help ke Admin</h2>
            <p>
              Pantau antrean, retry, keberhasilan, dan kegagalan email Help.
              Tujuan: <strong id="hp-support-recipient">—</strong>
            </p>
          </div>
          <a class="hp-button hp-button-secondary" href="/connect-v2/sso">
            Buka Dashboard Webhook
          </a>
        </div>

        <div class="hp-support-status-grid">
          <article class="hp-kpi">
            <div class="hp-kpi-label">Menunggu / Retry</div>
            <div id="hp-support-pending" class="hp-kpi-value">—</div>
            <div class="hp-kpi-foot">Termasuk jadwal percobaan berikutnya</div>
          </article>
          <article class="hp-kpi">
            <div class="hp-kpi-label">Sedang Mengirim</div>
            <div id="hp-support-sending" class="hp-kpi-value">—</div>
            <div class="hp-kpi-foot">Sedang diproses worker</div>
          </article>
          <article class="hp-kpi">
            <div class="hp-kpi-label">Terkirim</div>
            <div id="hp-support-sent" class="hp-kpi-value">—</div>
            <div class="hp-kpi-foot">Terakhir: <span id="hp-support-last-sent">—</span></div>
          </article>
          <article class="hp-kpi">
            <div class="hp-kpi-label">Perlu Tindakan</div>
            <div id="hp-support-failed" class="hp-kpi-value">—</div>
            <div class="hp-kpi-foot">Gagal atau email nonaktif</div>
          </article>
        </div>

        <div id="hp-support-monitor-error" class="hp-error-box hp-hidden"></div>
        <div id="hp-support-attention" class="hp-support-attention">
          <div class="hp-empty">Memuat status email Help…</div>
        </div>
      </section>


      <section
        id="services"
        class="hp-section"
      >
        <div class="hp-section-head">
          <div>
            <h2>Status layanan</h2>
            <p>
              Health service yang dipantau oleh Admin Gate.
            </p>
          </div>
        </div>

        <div
          id="hp-services"
          class="hp-service-grid"
          aria-live="polite"
        >
          <div class="hp-empty">Memuat layanan…</div>
        </div>
      </section>


      <section
        id="providers"
        class="hp-section"
      >
        <div class="hp-section-head">
          <div>
            <h2>Provider AI</h2>
            <p>
              Status provider dari AI Gateway.
            </p>
          </div>
        </div>

        <div
          id="hp-providers"
          class="hp-provider-grid"
          aria-live="polite"
        >
          <div class="hp-empty">Memuat provider…</div>
        </div>
      </section>


      <section class="hp-section">
        <div class="hp-section-head">
          <div>
            <h2>AI Gateway & sistem</h2>
            <p>
              Ringkasan data tambahan dari endpoint overview.
            </p>
          </div>
        </div>

        <div class="hp-detail-panel">
          <div
            id="hp-details"
            class="hp-detail-grid"
          >
            <div class="hp-empty">Memuat informasi…</div>
          </div>
        </div>
      </section>


      <section
        id="applications"
        class="hp-section"
      >
        <div class="hp-section-head">
          <div>
            <h2>Akses cepat</h2>
            <p>
              Buka aplikasi BotConnector tanpa mencari URL.
            </p>
          </div>
        </div>

        <div class="hp-access-grid">

          <a
            class="hp-access-card"
            href="https://studio.botconnector.id/"
          >
            <strong>PowerPoint Studio</strong>
            <p>
              AI Presentation Studio BotConnector.
            </p>
            <span>Buka Studio →</span>
          </a>

          <a
            class="hp-access-card"
            href="/workspace"
          >
            <strong>AI Workspace</strong>
            <p>
              Study AI dan Coding AI.
            </p>
            <span>Buka Workspace →</span>
          </a>

          <a
            class="hp-access-card"
            href="/document-assistant/"
          >
            <strong>Document Assistant</strong>
            <p>
              Dokumen, spreadsheet, dan intelligence.
            </p>
            <span>Buka Dokumen →</span>
          </a>

          <a
            class="hp-access-card"
            href="/photo-ai"
          >
            <strong>Photo AI</strong>
            <p>
              Studio pengolahan foto berbasis AI.
            </p>
            <span>Buka Photo AI →</span>
          </a>

          <a
            class="hp-access-card"
            href="/connect-v2"
          >
            <strong>BotConnector Connect</strong>
            <p>
              TradingView, webhook, MetaTrader, dan koneksi.
            </p>
            <span>Buka Connect →</span>
          </a>

          <a
            class="hp-access-card"
            href="/"
          >
            <strong>Homepage</strong>
            <p>
              Kembali ke halaman utama BotConnector.
            </p>
            <span>Buka Home →</span>
          </a>

        </div>
      </section>


      <section
        id="storage"
        class="hp-section"
      >
        <div class="hp-section-head">
          <div>
            <h2>Storage &amp; Quota</h2>
            <p>
              Atur kapasitas BotConnector Drive
              untuk setiap pengguna.
            </p>
          </div>
        </div>

        <div class="hp-storage-summary">

          <div class="hp-storage-summary-card">
            <span>DEFAULT QUOTA</span>
            <strong id="hp-storage-default">
              100 GiB
            </strong>
          </div>

          <div class="hp-storage-summary-card">
            <span>TOTAL PENGGUNA</span>
            <strong id="hp-storage-users">
              —
            </strong>
          </div>

          <div class="hp-storage-summary-card">
            <span>TOTAL TERPAKAI</span>
            <strong id="hp-storage-used">
              —
            </strong>
          </div>

        </div>

        <div
          id="hp-storage-message"
          class="hp-storage-message hp-hidden"
        ></div>

        <div class="hp-storage-toolbar">

          <div>
            <strong>Pengguna Drive</strong>
            <div class="hp-storage-sub">
              Perubahan quota langsung berlaku
              tanpa restart Drive.
            </div>
          </div>

          <input
            id="hp-storage-search"
            class="hp-storage-search"
            type="search"
            placeholder="Cari email atau nama..."
            autocomplete="off"
          >

        </div>

        <div class="hp-storage-table-wrap">

          <table class="hp-storage-table">

            <thead>
              <tr>
                <th>Pengguna</th>
                <th>Terpakai</th>
                <th>Kuota</th>
                <th>Sisa</th>
                <th>Pemakaian</th>
                <th>Pengaturan</th>
              </tr>
            </thead>

            <tbody id="hp-storage-rows">
              <tr>
                <td colspan="6">
                  <div class="hp-empty">
                    Memuat data storage…
                  </div>
                </td>
              </tr>
            </tbody>

          </table>

        </div>
      </section>

    </div>
  </main>
</div>


<script>
(() => {
  "use strict";

  const byId = (id) =>
    document.getElementById(id);

  const servicesEl =
    byId("hp-services");

  const providersEl =
    byId("hp-providers");

  const detailsEl =
    byId("hp-details");

  const errorEl =
    byId("hp-load-error");

  const refreshButton =
    byId("hp-refresh");

  const supportAttentionEl =
    byId("hp-support-attention");

  const supportMonitorErrorEl =
    byId("hp-support-monitor-error");


  function clear(el) {
    while (el.firstChild) {
      el.removeChild(el.firstChild);
    }
  }


  function text(el, value) {
    el.textContent =
      value === null || value === undefined
        ? "—"
        : String(value);
  }


  function itemName(item, fallback) {
    if (!item || typeof item !== "object") {
      return fallback;
    }

    return (
      item.name ||
      item.provider ||
      item.service ||
      item.id ||
      item.model ||
      fallback
    );
  }


  function itemOk(item) {
    if (!item || typeof item !== "object") {
      return false;
    }

    if (typeof item.ok === "boolean") {
      return item.ok;
    }

    if (typeof item.up === "boolean") {
      return item.up;
    }

    if (typeof item.healthy === "boolean") {
      return item.healthy;
    }

    const value = String(
      item.status || item.state || ""
    ).toLowerCase();

    return [
      "ok",
      "up",
      "healthy",
      "active",
      "ready",
      "online",
      "pass"
    ].includes(value);
  }


  function providerReady(item) {
    if (!item || typeof item !== "object") {
      return false;
    }

    if (typeof item.has_key === "boolean") {
      return item.has_key;
    }

    if (typeof item.enabled === "boolean") {
      return item.enabled;
    }

    return itemOk(item);
  }


  function providerDisplayName(value) {
    const raw =
      String(value || "");

    const names = {
      "cerebras": "Cerebras",
      "groq": "Groq",
      "nvidia": "NVIDIA",
      "google": "Google",
      "openrouter": "OpenRouter",
      "deepseek": "DeepSeek",
      "glm": "GLM"
    };

    return (
      names[raw.toLowerCase()]
      || raw
    );
  }


  function makeStatus(ok, kind) {
    const span =
      document.createElement("span");

    span.className =
      "hp-status "
      + (
        ok
          ? "hp-status-ok"
          : (
              kind === "provider"
                ? "hp-status-warn"
                : "hp-status-bad"
            )
      );

    if (kind === "provider") {
      span.textContent =
        ok
          ? "Siap"
          : "Key belum ada";
    } else {
      span.textContent =
        ok
          ? "Aktif"
          : "Periksa";
    }

    return span;
  }


  function compactMeta(item) {
    if (!item || typeof item !== "object") {
      return "";
    }

    const parts = [];

    for (const [key, value] of Object.entries(item)) {

      if (
        [
          "name",
          "provider",
          "service",
          "id",
          "model",
          "ok",
          "up",
          "healthy"
        ].includes(key)
      ) {
        continue;
      }

      if (
        value === null ||
        ["string", "number", "boolean"].includes(
          typeof value
        )
      ) {
        parts.push(
          key + ": " + String(value)
        );
      }

      if (parts.length >= 3) {
        break;
      }
    }

    return parts.join(" · ");
  }


  function providerMeta(item) {
    const key = item && item.key_masked ? String(item.key_masked) : "—";
    const attempts = Number(item && item.usage_attempts || 0);
    const success = Number(item && item.usage_success || 0);
    const errors = Number(item && item.usage_errors || 0);
    const rpmUsed = Number(item && item.rpm_used || 0);
    const rpmLimit = Number(item && item.rpm_limit || 0);

    return (
      "Key: " + key
      + " · Pemakaian: " + attempts
      + " · Sukses: " + success
      + " · Gagal: " + errors
      + " · RPM: " + rpmUsed + "/" + rpmLimit
    );
  }

  function renderStatusCards(
    container,
    items,
    kind
  ) {
    clear(container);

    if (!items.length) {
      const empty =
        document.createElement("div");

      empty.className = "hp-empty";

      empty.textContent =
        kind === "provider"
          ? "Belum ada data provider."
          : "Belum ada data layanan.";

      container.appendChild(empty);

      return;
    }

    items.forEach((item, index) => {
      const card =
        document.createElement("article");

      card.className =
        kind === "provider"
          ? "hp-provider-card"
          : "hp-service-card";

      const head =
        document.createElement("div");

      head.className =
        "hp-card-head";

      const name =
        document.createElement("div");

      name.className =
        "hp-card-name";

      const rawName =
        itemName(
          item,
          kind === "provider"
            ? "Provider " + (index + 1)
            : "Service " + (index + 1)
        );

      name.textContent =
        kind === "provider"
          ? providerDisplayName(rawName)
          : rawName;

      head.appendChild(name);

      const ready =
        kind === "provider"
          ? providerReady(item)
          : itemOk(item);

      head.appendChild(
        makeStatus(
          ready,
          kind
        )
      );

      card.appendChild(head);

      const meta =
        document.createElement("div");

      meta.className =
        "hp-card-meta";

      meta.textContent =
        (kind === "provider" ? providerMeta(item) : compactMeta(item))
        || (
          kind === "provider"
            ? (
                ready
                  ? "API key provider tersedia."
                  : "API key provider belum dikonfigurasi."
              )
            : (
                ready
                  ? "Service merespons normal."
                  : "Status membutuhkan pemeriksaan."
              )
        );

      card.appendChild(meta);

      container.appendChild(card);
    });
  }


  function scalarRows(data) {
    const rows = [];

    for (
      const [key, value]
      of Object.entries(data || {})
    ) {
      if (
        key === "services" ||
        key === "providers"
      ) {
        continue;
      }

      if (
        value === null ||
        [
          "string",
          "number",
          "boolean"
        ].includes(typeof value)
      ) {
        rows.push([
          key,
          value
        ]);

        continue;
      }

      if (
        value &&
        typeof value === "object" &&
        !Array.isArray(value)
      ) {
        for (
          const [subKey, subValue]
          of Object.entries(value)
        ) {
          if (
            subValue === null ||
            [
              "string",
              "number",
              "boolean"
            ].includes(typeof subValue)
          ) {
            rows.push([
              key + "." + subKey,
              subValue
            ]);
          }

          if (rows.length >= 12) {
            break;
          }
        }
      }

      if (rows.length >= 12) {
        break;
      }
    }

    return rows;
  }


  function renderDetails(data) {
    clear(detailsEl);

    const rows =
      scalarRows(data);

    if (!rows.length) {
      const empty =
        document.createElement("div");

      empty.className =
        "hp-empty";

      empty.textContent =
        "Tidak ada KPI tambahan.";

      detailsEl.appendChild(empty);

      return;
    }

    rows.forEach(([key, value]) => {
      const item =
        document.createElement("div");

      item.className =
        "hp-detail-item";

      const label =
        document.createElement("strong");

      label.textContent = key;

      const val =
        document.createElement("span");

      val.textContent =
        String(value);

      item.appendChild(label);
      item.appendChild(val);

      detailsEl.appendChild(item);
    });
  }


  function hpBusinessNumber(id, value) {
    const el = byId(id);

    if (!el) return;

    const number = Number(value);

    el.textContent =
      Number.isFinite(number)
        ? number.toLocaleString("id-ID")
        : "—";
  }


  function applyBusinessMetrics(business) {
    const account =
      business &&
      business.account &&
      business.account.ok
        ? business.account
        : {};

    const traffic =
      business &&
      business.traffic &&
      business.traffic.ok
        ? business.traffic
        : {};

    hpBusinessNumber(
      "hp-account-total",
      account.total_users
    );

    hpBusinessNumber(
      "hp-account-active",
      account.active_users
    );

    hpBusinessNumber(
      "hp-account-verified",
      account.verified_users
    );

    hpBusinessNumber(
      "hp-registered-today",
      account.registered_today
    );

    hpBusinessNumber(
      "hp-registered-7d",
      account.registered_7d
    );

    hpBusinessNumber(
      "hp-login-today",
      account.logged_in_today
    );

    hpBusinessNumber(
      "hp-login-7d",
      account.logged_in_7d
    );

    hpBusinessNumber(
      "hp-visitors-today",
      traffic.visitors_today
    );

    hpBusinessNumber(
      "hp-visitors-3d",
      traffic.visitors_3d
    );

    hpBusinessNumber(
      "hp-pageviews-today",
      traffic.pageviews_today
    );

    hpBusinessNumber(
      "hp-pageviews-3d",
      traffic.pageviews_3d
    );
  }


  function formatSupportTime(value) {
    if (!value) return "—";
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) return "—";
    return new Intl.DateTimeFormat(
      "id-ID",
      {dateStyle: "medium", timeStyle: "short"}
    ).format(date);
  }


  function renderSupportEmail(data) {
    const monitor = data && typeof data === "object" ? data : {};
    const counts = monitor.counts && typeof monitor.counts === "object"
      ? monitor.counts : {};

    hpBusinessNumber("hp-support-pending", counts.pending || 0);
    hpBusinessNumber("hp-support-sending", counts.sending || 0);
    hpBusinessNumber("hp-support-sent", counts.sent || 0);
    hpBusinessNumber(
      "hp-support-failed",
      Number(counts.failed || 0) + Number(counts.disabled || 0)
    );
    text(byId("hp-support-recipient"), monitor.recipient || "—");
    text(byId("hp-support-last-sent"), formatSupportTime(monitor.last_sent_at));

    clear(supportAttentionEl);
    supportMonitorErrorEl.classList.add("hp-hidden");

    if (!monitor.ok) {
      supportMonitorErrorEl.textContent =
        "Monitoring email Help tidak tersedia: " + (monitor.error || "unknown");
      supportMonitorErrorEl.classList.remove("hp-hidden");
      const empty = document.createElement("div");
      empty.className = "hp-empty";
      empty.textContent = "Status delivery belum dapat dimuat.";
      supportAttentionEl.appendChild(empty);
      return;
    }

    const attention = Array.isArray(monitor.needs_attention)
      ? monitor.needs_attention : [];
    if (!attention.length) {
      const empty = document.createElement("div");
      empty.className = "hp-empty";
      empty.textContent = "Tidak ada email Help yang memerlukan tindakan.";
      supportAttentionEl.appendChild(empty);
      return;
    }

    attention.forEach((item) => {
      const row = document.createElement("div");
      row.className = "hp-support-item";
      const info = document.createElement("div");
      const title = document.createElement("strong");
      title.textContent = "Pesan #" + item.id + " · "
        + String(item.email_delivery_status || "unknown").toUpperCase();
      const meta = document.createElement("span");
      meta.textContent = "Percobaan " + Number(item.email_delivery_attempts || 0)
        + "/" + Number(monitor.max_attempts || 5)
        + (item.email_delivery_last_error
          ? " · " + item.email_delivery_last_error : "")
        + (item.email_delivery_next_attempt_at
          ? " · Retry " + formatSupportTime(item.email_delivery_next_attempt_at) : "");
      info.appendChild(title);
      info.appendChild(meta);
      const status = document.createElement("span");
      const failed = ["failed", "disabled"].includes(
        String(item.email_delivery_status || "").toLowerCase()
      );
      status.className = "hp-status "
        + (failed ? "hp-status-bad" : "hp-status-warn");
      status.textContent = failed ? "Perlu tindakan" : "Diproses";
      row.appendChild(info);
      row.appendChild(status);
      supportAttentionEl.appendChild(row);
    });
  }


  async function loadOverview() {
    refreshButton.disabled = true;

    errorEl.classList.add(
      "hp-hidden"
    );

    try {
      const response =
        await fetch(
          "overview",
          {
            method: "GET",
            credentials: "same-origin",
            cache: "no-store",
            headers: {
              "Accept":
                "application/json"
            }
          }
        );

      if (!response.ok) {
        throw new Error(
          response.status === 403
            ? "Sesi admin tidak valid atau telah berakhir."
            : "HTTP " + response.status
        );
      }

      const data =
        await response.json();

      const services =
        Array.isArray(data.services)
          ? data.services
          : [];

      const providers =
        Array.isArray(data.providers)
          ? data.providers
          : [];

      applyBusinessMetrics(
        data.business || {}
      );

      renderSupportEmail(
        data.support_email || {}
      );

      const up =
        services.filter(
          itemOk
        ).length;

      text(
        byId("hp-services-up"),
        up
      );

      text(
        byId("hp-services-total"),
        services.length
      );

      text(
        byId("hp-provider-total"),
        providers.length
      );

      text(
        byId("hp-updated"),
        new Intl.DateTimeFormat(
          "id-ID",
          {
            hour: "2-digit",
            minute: "2-digit",
            second: "2-digit"
          }
        ).format(new Date())
      );

      text(
        byId("hp-overall-state"),
        services.length === 0
          ? "Status tersedia"
          : (
              up === services.length
                ? "Semua layanan sehat"
                : up + "/" + services.length
                  + " layanan aktif"
            )
      );

      renderStatusCards(
        servicesEl,
        services,
        "service"
      );

      renderStatusCards(
        providersEl,
        providers,
        "provider"
      );

      renderDetails(data);

    } catch (error) {
      errorEl.textContent =
        "Gagal memuat overview: "
        + (
          error &&
          error.message
            ? error.message
            : String(error)
        );

      errorEl.classList.remove(
        "hp-hidden"
      );

      text(
        byId("hp-overall-state"),
        "Status tidak tersedia"
      );

    } finally {
      refreshButton.disabled = false;
    }
  }


  refreshButton.addEventListener(
    "click",
    loadOverview
  );

  loadOverview();
})();


(() => {
  "use strict";

  const rowsEl =
    document.getElementById(
      "hp-storage-rows"
    );

  const searchEl =
    document.getElementById(
      "hp-storage-search"
    );

  const messageEl =
    document.getElementById(
      "hp-storage-message"
    );

  const defaultEl =
    document.getElementById(
      "hp-storage-default"
    );

  const usersEl =
    document.getElementById(
      "hp-storage-users"
    );

  const usedEl =
    document.getElementById(
      "hp-storage-used"
    );

  let csrfToken = "";
  let storageRows = [];


  function esc(value) {

    return String(
      value ?? ""
    )
      .replaceAll(
        "&",
        "&amp;"
      )
      .replaceAll(
        "<",
        "&lt;"
      )
      .replaceAll(
        ">",
        "&gt;"
      )
      .replaceAll(
        '"',
        "&quot;"
      )
      .replaceAll(
        "'",
        "&#39;"
      );
  }


  function humanBytes(value) {

    if (
      value === null
      || value === undefined
    ) {
      return "Unlimited";
    }

    let size =
      Number(value);

    if (
      !Number.isFinite(size)
      || size < 0
    ) {
      return "—";
    }

    const units = [
      "B",
      "KiB",
      "MiB",
      "GiB",
      "TiB"
    ];

    let index = 0;

    while (
      size >= 1024
      && index < units.length - 1
    ) {
      size /= 1024;
      index += 1;
    }

    if (index === 0) {
      return (
        Math.round(size)
        + " "
        + units[index]
      );
    }

    return (
      size.toFixed(2)
      + " "
      + units[index]
    );
  }


  function showMessage(
    text,
    error = false
  ) {

    if (!messageEl) {
      return;
    }

    messageEl.textContent =
      text || "";

    messageEl.classList.toggle(
      "hp-hidden",
      !text
    );

    messageEl.classList.toggle(
      "hp-error",
      Boolean(error)
    );
  }


  function quotaSelect(
    row
  ) {

    const override =
      row.quota_override_bytes;

    let current =
      override === null
      || override === undefined
        ? 100
        : (
            Number(override) === 0
              ? 0
              : Math.round(
                  Number(override)
                  / (1024 ** 3)
                )
          );

    const presets = [
      10,
      25,
      50,
      100,
      250,
      500,
      1024,
      0
    ];

    const known =
      presets.includes(current);

    const option = (
      value,
      label
    ) => (
      '<option value="'
      + value
      + '"'
      + (
          known
          && current === value
            ? " selected"
            : ""
        )
      + ">"
      + label
      + "</option>"
    );

    return (
      '<select class="hp-storage-select" '
      + 'name="quota_choice">'
      + option(10, "10 GiB")
      + option(25, "25 GiB")
      + option(50, "50 GiB")
      + option(100, "100 GiB")
      + option(250, "250 GiB")
      + option(500, "500 GiB")
      + option(1024, "1 TiB")
      + option(0, "Unlimited")
      + '<option value="custom"'
      + (
          !known
            ? " selected"
            : ""
        )
      + '>Custom</option>'
      + "</select>"
      + '<input '
      + 'class="hp-storage-custom" '
      + 'name="custom_gib" '
      + 'type="number" '
      + 'min="1" max="16384" '
      + 'placeholder="GiB" '
      + (
          !known
            ? (
                'value="'
                + esc(current)
                + '"'
              )
            : "hidden"
        )
      + ">"
    );
  }


  function renderStorage() {

    if (!rowsEl) {
      return;
    }

    const query =
      (
        searchEl?.value
        || ""
      )
      .trim()
      .toLowerCase();

    const visible =
      storageRows.filter(
        row => (
          (
            String(row.email || "")
            + " "
            + String(
                row.display_name
                || ""
              )
          )
          .toLowerCase()
          .includes(query)
        )
      );


    if (!visible.length) {

      rowsEl.innerHTML =
        '<tr><td colspan="6">'
        + '<div class="hp-empty">'
        + (
            query
              ? "Pengguna tidak ditemukan."
              : "Belum ada pengguna."
          )
        + "</div></td></tr>";

      return;
    }


    rowsEl.innerHTML =
      visible.map(
        row => {

          const used =
            Number(
              row.used_bytes
              || 0
            );

          const limit =
            row.limit_bytes;

          const remaining =
            row.remaining_bytes;

          let percent = 0;

          if (
            limit !== null
            && limit !== undefined
            && Number(limit) > 0
          ) {
            percent = Math.min(
              100,
              (
                used
                / Number(limit)
                * 100
              )
            );
          }


          const source =
            row.quota_source
            === "override"
              ? (
                  Number(
                    row.quota_override_bytes
                  ) === 0
                    ? "Unlimited"
                    : "Override"
                )
              : "Default";


          const resetButton =
            row.quota_source
            === "override"
              ? (
                  '<button '
                  + 'class="hp-button '
                  + 'hp-button-secondary" '
                  + 'type="submit" '
                  + 'name="action" '
                  + 'value="reset">'
                  + "Reset"
                  + "</button>"
                )
              : "";


          return (
            '<tr data-storage-search="'
            + esc(
                (
                  row.email
                  || ""
                )
                + " "
                + (
                  row.display_name
                  || ""
                )
              )
            + '">'

            + '<td class="hp-storage-user">'
            + "<strong>"
            + esc(row.email)
            + "</strong>"
            + "<span>"
            + esc(
                row.display_name
                || "-"
              )
            + "</span>"
            + "</td>"

            + "<td>"
            + humanBytes(used)
            + "</td>"

            + "<td><strong>"
            + humanBytes(limit)
            + "</strong>"
            + '<span class="hp-storage-sub">'
            + esc(source)
            + "</span></td>"

            + "<td>"
            + humanBytes(remaining)
            + "</td>"

            + "<td>"
            + '<div class="hp-storage-progress">'
            + '<i style="width:'
            + percent.toFixed(1)
            + '%"></i></div>'
            + '<span class="hp-storage-sub">'
            + percent.toFixed(1)
            + "%"
            + "</span>"
            + "</td>"

            + "<td>"
            + '<form class="hp-storage-form" '
            + 'data-user-id="'
            + esc(row.user_id)
            + '">'
            + quotaSelect(row)
            + '<button '
            + 'class="hp-button '
            + 'hp-button-primary" '
            + 'type="submit" '
            + 'name="action" '
            + 'value="set">'
            + "Simpan"
            + "</button>"
            + resetButton
            + "</form>"
            + "</td>"

            + "</tr>"
          );
        }
      ).join("");
  }


  async function loadStorage() {

    if (!rowsEl) {
      return;
    }

    try {

      showMessage("");

      const response =
        await fetch(
          "storage-data",
          {
            method: "GET",
            credentials:
              "same-origin",
            cache: "no-store",
            headers: {
              "Accept":
                "application/json"
            }
          }
        );


      if (!response.ok) {

        let detail = "";

        try {

          const payload =
            await response.json();

          detail =
            payload.detail
            || "";

        } catch {}


        throw new Error(
          detail
          || (
              response.status
              === 401
                ? (
                    "Sesi Core belum tersedia. "
                    + "Keluar lalu login kembali "
                    + "ke Hpanel."
                  )
                : (
                    "HTTP "
                    + response.status
                  )
            )
        );
      }


      const data =
        await response.json();

      storageRows =
        Array.isArray(
          data.users
        )
          ? data.users
          : [];


      if (defaultEl) {
        defaultEl.textContent =
          humanBytes(
            data.default_quota_bytes
          );
      }

      if (usersEl) {
        usersEl.textContent =
          String(
            storageRows.length
          );
      }

      if (usedEl) {

        const total =
          storageRows.reduce(
            (
              sum,
              row
            ) => (
              sum
              + Number(
                  row.used_bytes
                  || 0
                )
            ),
            0
          );

        usedEl.textContent =
          humanBytes(total);
      }


      renderStorage();


    } catch (error) {

      rowsEl.innerHTML =
        '<tr><td colspan="6">'
        + '<div class="hp-empty">'
        + "Data storage tidak tersedia."
        + "</div></td></tr>";

      showMessage(
        (
          error
          && error.message
            ? error.message
            : String(error)
        ),
        true
      );
    }
  }


  async function getCsrf() {

    if (csrfToken) {
      return csrfToken;
    }

    const response =
      await fetch(
        "storage-token",
        {
          method: "GET",
          credentials:
            "same-origin",
          cache: "no-store",
          headers: {
            "Accept":
              "application/json"
          }
        }
      );


    if (!response.ok) {
      throw new Error(
        "Sesi keamanan Hpanel tidak valid."
      );
    }


    const payload =
      await response.json();

    csrfToken =
      payload.csrf_token
      || "";

    if (!csrfToken) {
      throw new Error(
        "Token keamanan tidak tersedia."
      );
    }

    return csrfToken;
  }


  document.addEventListener(
    "change",
    event => {

      const select =
        event.target.closest(
          ".hp-storage-select"
        );

      if (!select) {
        return;
      }

      const custom =
        select.parentElement
        ?.querySelector(
          ".hp-storage-custom"
        );

      if (!custom) {
        return;
      }

      custom.hidden =
        select.value !== "custom";
    }
  );


  document.addEventListener(
    "submit",
    async event => {

      const form =
        event.target.closest(
          ".hp-storage-form"
        );

      if (!form) {
        return;
      }

      event.preventDefault();


      try {

        const submitter =
          event.submitter;

        const action =
          submitter?.value
          || "set";

        const data =
          new FormData();

        data.set(
          "user_id",
          form.dataset.userId
          || ""
        );

        data.set(
          "action",
          action
        );


        if (action === "set") {

          const select =
            form.querySelector(
              ".hp-storage-select"
            );

          const custom =
            form.querySelector(
              ".hp-storage-custom"
            );

          const raw =
            select?.value
            === "custom"
              ? custom?.value
              : select?.value;

          const quota =
            Number(raw);


          if (
            !Number.isInteger(quota)
            || quota < 0
            || quota > 16384
          ) {
            throw new Error(
              "Kuota harus 0–16384 GiB."
            );
          }


          data.set(
            "quota_gib",
            String(quota)
          );
        }


        const csrf =
          await getCsrf();


        const response =
          await fetch(
            "storage-quota",
            {
              method: "POST",
              credentials:
                "same-origin",
              headers: {
                "X-HPANEL-CSRF":
                  csrf,
              },
              body: data,
            }
          );


        const payload =
          await response.json()
          .catch(
            () => ({})
          );


        if (!response.ok) {

          throw new Error(
            payload.detail
            || (
                "Perubahan kuota "
                + "tidak berhasil."
              )
          );
        }


        showMessage(
          payload.message
          || "Kuota berhasil diperbarui."
        );


        csrfToken = "";

        await loadStorage();


      } catch (error) {

        showMessage(
          (
            error
            && error.message
              ? error.message
              : String(error)
          ),
          true
        );
      }
    }
  );


  if (searchEl) {

    searchEl.addEventListener(
      "input",
      renderStorage
    );
  }


  const storageLink =
    document.querySelector(
      '.hp-nav a[href="#storage"]'
    );


  if (storageLink) {

    storageLink.addEventListener(
      "click",
      () => {

        document
          .querySelectorAll(
            ".hp-nav a"
          )
          .forEach(
            item => item
              .classList
              .remove(
                "hp-active"
              )
          );

        storageLink.classList.add(
          "hp-active"
        );
      }
    );
  }


  loadStorage();
})();

</script>

</body>
</html>"""
    )



@app.get("/", response_class=HTMLResponse)
async def home(request: Request):
    email = current_admin(request)
    return dashboard(email) if email else login_form()


@app.post("/login")
async def login(
    request: Request,
    email: str = Form(""),
    password: str = Form(""),
):

    em = (
        email.strip().lower()
    )


    if em not in ADMIN_EMAILS:

        return HTMLResponse(
            login_form(
                "Email ini bukan admin."
            ),
            status_code=403,
        )


    if not SECRET:

        return HTMLResponse(
            login_form(
                "Konfigurasi admin "
                "belum siap."
            ),
            status_code=503,
        )


    ok, core_session = (
        await core_login_session(
            em,
            password,
        )
    )


    if (
        not ok
        or not core_session
    ):

        return HTMLResponse(
            login_form(
                "Email atau password salah."
            ),
            status_code=401,
        )


    resp = RedirectResponse(
        url=".",
        status_code=303,
    )


    resp.set_cookie(
        COOKIE,
        issue(em),
        max_age=TTL,
        domain=COOKIE_DOMAIN,
        path="/",
        httponly=True,
        secure=True,
        samesite="lax",
    )


    # Core session dipertahankan agar
    # Hpanel dapat memakai API admin resmi.
    resp.set_cookie(
        CORE_SESSION_COOKIE,
        core_session,
        max_age=CORE_SESSION_TTL,
        path="/",
        httponly=True,
        secure=True,
        samesite="lax",
    )


    return resp


@app.post("/logout")
async def logout():
    resp = RedirectResponse(url=".", status_code=303)
    resp.delete_cookie(COOKIE, domain=COOKIE_DOMAIN, path="/")
    return resp


@app.get("/overview")
async def overview(request: Request):
    if not current_admin(request):
        raise HTTPException(403, "khusus admin")
    return await gather_overview()


@app.get("/check")
async def check(request: Request):
    email = current_admin(request)
    return {"admin": bool(email), "email": email}


@app.get("/health")
async def health():
    return {"ok": True, "service": "admin-gate", "admins": len(ADMIN_EMAILS)}


# =========================================================
# HPANEL_STORAGE_QUOTA_V1 ROUTES
# =========================================================

@app.get("/storage-token")
async def storage_token(
    request: Request,
):

    email = current_admin(
        request
    )

    if not email:
        raise HTTPException(
            status_code=403,
            detail=(
                "Sesi admin tidak valid."
            ),
        )


    return {
        "csrf_token":
            storage_csrf(
                email
            ),
    }


@app.get("/storage-data")
async def storage_data(
    request: Request,
):

    email = current_admin(
        request
    )

    if not email:
        raise HTTPException(
            status_code=403,
            detail=(
                "Sesi admin tidak valid."
            ),
        )


    session_token = (
        request.cookies.get(
            CORE_SESSION_COOKIE
        )
    )


    if not session_token:
        raise HTTPException(
            status_code=401,
            detail=(
                "Sesi Core belum tersedia. "
                "Keluar lalu login kembali "
                "ke Hpanel."
            ),
        )


    return await core_json(
        "GET",
        "/v1/admin/drive/quotas",
        session_token,
    )


@app.post("/storage-quota")
async def storage_quota(
    request: Request,
    user_id: str = Form(""),
    action: str = Form("set"),
    quota_gib: str = Form("100"),
):

    email = current_admin(
        request
    )


    if not email:
        raise HTTPException(
            status_code=403,
            detail=(
                "Sesi admin tidak valid."
            ),
        )


    supplied = (
        request.headers.get(
            "X-HPANEL-CSRF",
            "",
        )
    )


    expected = storage_csrf(
        email
    )


    if (
        not supplied
        or not expected
        or not hmac.compare_digest(
            supplied,
            expected,
        )
    ):
        raise HTTPException(
            status_code=403,
            detail=(
                "Token keamanan "
                "Hpanel tidak valid."
            ),
        )


    user_id = user_id.strip()

    if not user_id:
        raise HTTPException(
            status_code=422,
            detail=(
                "User ID tidak valid."
            ),
        )


    session_token = (
        request.cookies.get(
            CORE_SESSION_COOKIE
        )
    )


    if not session_token:
        raise HTTPException(
            status_code=401,
            detail=(
                "Sesi Core belum tersedia. "
                "Silakan login ulang."
            ),
        )


    csrf = await core_csrf_token(
        session_token
    )


    action = (
        action.strip().lower()
    )


    if action == "reset":

        result = await core_json(
            "DELETE",
            (
                "/v1/admin/drive/"
                "quotas/"
                + user_id
            ),
            session_token,
            csrf_token=csrf,
        )


        return {
            "ok": True,
            "message":
                (
                    "Kuota dikembalikan "
                    "ke default 100 GiB."
                ),
            "result": result,
        }


    try:

        gib = int(
            quota_gib.strip()
        )

    except Exception:

        raise HTTPException(
            status_code=422,
            detail=(
                "Nilai kuota tidak valid."
            ),
        )


    if (
        gib < 0
        or gib > 16384
    ):
        raise HTTPException(
            status_code=422,
            detail=(
                "Kuota harus "
                "0–16384 GiB."
            ),
        )


    result = await core_json(
        "PUT",
        (
            "/v1/admin/drive/"
            "quotas/"
            + user_id
        ),
        session_token,
        json_data={
            "quota_bytes":
                gib * 1024**3,
        },
        csrf_token=csrf,
    )


    return {
        "ok": True,
        "message":
            (
                "Kuota menjadi Unlimited."
                if gib == 0
                else (
                    "Kuota menjadi "
                    + str(gib)
                    + " GiB."
                )
            ),
        "result": result,
    }

