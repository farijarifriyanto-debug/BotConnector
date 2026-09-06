"""Telegram Intake Adapter for BotConnector BC Bisnis (owner-only pilot).

Real-channel long polling is separate (bot_poller.py + bot_client.py). This
module owns the durable, server-side state and pure logic:

  - owner pairing tokens (one-time, expiring, hashed, single-use)
  - /start <payload> pairing resolution
  - durable Telegram update idempotency (update_id boundary)
  - hardened Mini App initData validation (auth_date freshness, constant-time)
  - document/text -> canonical Intake Engine draft (NO business mutation)
  - explicit confirmation gate (re-check pairing/batch, no replay)

Telegram data NEVER mutates Product/Inventory/Finance directly; everything
flows through the existing canonical intake.create_draft / confirm_batch.
"""

from __future__ import annotations

import hashlib
import hmac
import os
import json
import re
import secrets
from datetime import datetime, timezone, timedelta

from ..persistence.db import koneksi as _pg

# Truthful connectivity: token may come from dedicated env (handled by runtime
# that loads /etc/botconnector/bisnis-telegram.env). This module does NOT read
# the secret itself; runtime passes it in for validation/pairing.
INITDATA_MAX_AGE_SECONDS = int(os.environ.get(
    "BC_BISNIS_TELEGRAM_INITDATA_MAX_AGE_SECONDS", "300"))
PAIRING_TTL_SECONDS = int(os.environ.get(
    "BC_BISNIS_TELEGRAM_PAIRING_TTL_SECONDS", "600"))
# Telegram start parameter constraint: 1-64 chars, a-z A-Z 0-9 _ -
START_PARAM_MAX = 64


def connectivity_status() -> str:
    """Truthful real-channel status (never invented)."""
    token = os.environ.get("BC_BISNIS_TELEGRAM_BOT_TOKEN", "").strip()
    return "ENABLED" if token else "BLOCKED_EXTERNAL_TOKEN"


# ============================================================ update idempotency
def _update_seen(update_id: int) -> bool:
    with _pg() as c:
        cur = c.cursor()
        cur.execute(
            "SELECT 1 FROM local_business.telegram_update WHERE update_id=%s",
            (update_id,))
        return cur.fetchone() is not None


def record_update(*, update_id: int, chat_id: int, telegram_user_id: int,
                  kind: str, file_unique_id: str = "", batch_id: str = "") -> bool:
    """Record a processed Telegram update. Returns True if newly processed.

    update_id is the delivery idempotency boundary: replaying the same
    update_id is a no-op (returns False) and cannot duplicate effects.
    """
    with _pg() as c:
        cur = c.cursor()
        try:
            cur.execute(
                """INSERT INTO local_business.telegram_update
                   (update_id, chat_id, telegram_user_id, kind, file_unique_id, batch_id)
                   VALUES (%s,%s,%s,%s,%s,%s)""",
                (update_id, chat_id, telegram_user_id, kind, file_unique_id, batch_id))
            c.commit()
            return True
        except Exception:
            c.rollback()
            return False


def current_offset() -> int:
    with _pg() as c:
        cur = c.cursor()
        cur.execute("SELECT poll_offset FROM local_business.telegram_offset WHERE id=1")
        row = cur.fetchone()
        return int(row["poll_offset"]) if row else 0


def save_offset(new_offset: int) -> None:
    with _pg() as c:
        cur = c.cursor()
        cur.execute(
            "UPDATE local_business.telegram_offset SET poll_offset=%s, updated_at=now() WHERE id=1",
            (new_offset,))
        c.commit()


# ============================================================ Mini App initData
def _hash_digest(data: bytes, key: bytes) -> str:
    return hmac.new(key, data, hashlib.sha256).hexdigest()


def _compute_auth_hash(parsed: dict, token: str) -> str:
    data_check = "\n".join(
        f"{k}={v}" for k, v in sorted(parsed.items()) if k != "hash"
    ).encode()
    secret_key = hmac.new(b"WebAppData", token.encode(), hashlib.sha256).digest()
    return _hash_digest(data_check, secret_key)


def validate_init_data(init_data: str, token: str = "",
                       max_age_seconds: int | None = None,
                       now: datetime | None = None) -> dict:
    """Validate Telegram.WebApp.initData server-side.

    - never trusts initDataUnsafe
    - HMAC must verify (constant-time)
    - auth_date must exist, be fresh (<= max_age), not absurdly in the future
    - returns user_id only after all checks pass
    """
    max_age_seconds = max_age_seconds or INITDATA_MAX_AGE_SECONDS
    now = now or datetime.now(timezone.utc)
    if not token:
        return {"valid": False, "user_id": None, "reason": "no_bot_token"}

    try:
        parsed = dict(pair.split("=", 1) for pair in init_data.split("&"))
    except Exception:
        return {"valid": False, "user_id": None, "reason": "malformed"}

    received_hash = parsed.get("hash", "")
    if not received_hash:
        return {"valid": False, "user_id": None, "reason": "no_hash"}

    calc = _compute_auth_hash(parsed, token)
    if not hmac.compare_digest(calc, received_hash):
        return {"valid": False, "user_id": None, "reason": "hash_mismatch"}

    # auth_date freshness
    raw_auth = parsed.get("auth_date", "")
    if not raw_auth:
        return {"valid": False, "user_id": None, "reason": "missing_auth_date"}
    try:
        auth_dt = datetime.fromtimestamp(int(raw_auth), tz=timezone.utc)
    except Exception:
        return {"valid": False, "user_id": None, "reason": "bad_auth_date"}

    skew = 30  # small clock-skew tolerance
    if auth_dt > now + timedelta(seconds=skew):
        return {"valid": False, "user_id": None, "reason": "future_auth_date"}
    if (now - auth_dt).total_seconds() > max_age_seconds:
        return {"valid": False, "user_id": None, "reason": "stale_auth_date"}

    try:
        user = json.loads(parsed.get("user", "{}"))
        user_id = int(user.get("id", 0))
    except Exception:
        return {"valid": False, "user_id": None, "reason": "bad_user"}

    return {"valid": True, "user_id": user_id or None, "reason": "ok"}


# ============================================================ pairing
def _hash_token(raw: str) -> str:
    return hashlib.sha256(("bc-pair:" + raw).encode()).hexdigest()


def create_pairing_token(*, owner_id: int, business_id: int,
                         core_user_id: str | None = None,
                         ttl_seconds: int | None = None,
                         now: datetime | None = None) -> dict:
    """Create a one-time, expiring, owner-scoped pairing token (stored hashed)."""
    import uuid
    now = now or datetime.now(timezone.utc)
    ttl = ttl_seconds or PAIRING_TTL_SECONDS
    raw = "P-" + uuid.uuid4().hex + secrets.token_urlsafe(12)
    h = _hash_token(raw)
    expires = now + timedelta(seconds=ttl)
    with _pg() as c:
        cur = c.cursor()
        cur.execute(
            """INSERT INTO local_business.telegram_pairing
               (owner_id, business_id, core_user_id, token_hash, expires_at)
               VALUES (%s,%s,%s,%s,%s)
               RETURNING id""",
            (owner_id, business_id, core_user_id, h, expires))
        row = cur.fetchone()
        c.commit()
    return {"ok": True, "pairing_id": row["id"], "raw_token": raw, "expires_at": expires}


def resolve_pairing(raw_token: str, telegram_user_id: int,
                    now: datetime | None = None) -> dict:
    """Resolve /start <raw_token> into a durable pairing.

    Single-use, expiring, unguessable. Replay fails. Never by username.
    """
    now = now or datetime.now(timezone.utc)
    h = _hash_token(raw_token)
    with _pg() as c:
        cur = c.cursor()
        cur.execute(
            "SELECT * FROM local_business.telegram_pairing WHERE token_hash=%s FOR UPDATE",
            (h,))
        p = cur.fetchone()
        if not p:
            return {"ok": False, "error": "unknown_token"}
        if p["consumed_at"] is not None:
            return {"ok": False, "error": "token_already_used"}
        if p["expires_at"] is None or p["expires_at"] < now:
            return {"ok": False, "error": "token_expired"}
        owner_id = p["owner_id"]
        business_id = p["business_id"] or owner_id
        core_user_id = p.get("core_user_id")
        cur.execute(
            "UPDATE local_business.telegram_pairing SET consumed_at=now() WHERE id=%s",
            (p["id"],))
        # durable owner<->telegram mapping with business_id and core_user_id
        cur.execute(
            """INSERT INTO local_business.telegram_account
               (owner_id, business_id, telegram_user_id, core_user_id, role, actor)
               VALUES (%s,%s,%s,%s,'owner',%s)
               ON CONFLICT (owner_id, telegram_user_id)
               DO UPDATE SET business_id=EXCLUDED.business_id,
                             core_user_id=COALESCE(EXCLUDED.core_user_id, local_business.telegram_account.core_user_id),
                             updated_at=now()
               RETURNING id""",
            (owner_id, business_id, telegram_user_id, core_user_id, f"tg:{telegram_user_id}"))
        acc = cur.fetchone()
        c.commit()
    return {"ok": True, "owner_id": owner_id, "business_id": business_id,
            "telegram_user_id": telegram_user_id, "account_id": acc["id"]}


def pairing_status(owner_id: int) -> dict:
    """Return current pairing state for an owner (username never used)."""
    with _pg() as c:
        cur = c.cursor()
        cur.execute(
            "SELECT telegram_user_id, created_at FROM local_business.telegram_account "
            "WHERE (owner_id=%s OR business_id=%s) ORDER BY id DESC LIMIT 1",
            (owner_id, owner_id))
        acc = cur.fetchone()
    if acc:
        return {"paired": True, "telegram_user_id": acc["telegram_user_id"],
                "created_at": acc["created_at"]}
    return {"paired": False, "telegram_user_id": None}


def account_for_telegram_user(telegram_user_id: int) -> dict | None:
    """Telegram-user-facing lookup: resolve durable account BY telegram_user_id.

    Telegram numeric user_id is identity authority; username is never used.
    Returns None when no durable pairing binds this Telegram user. This is the
    distinct reverse direction from pairing_status(owner_id); it is not an
    owner-scoped lookup and never takes a username.
    """
    with _pg() as c:
        cur = c.cursor()
        cur.execute(
            "SELECT id, owner_id, business_id, core_user_id, role, telegram_user_id, created_at "
            "FROM local_business.telegram_account "
            "WHERE telegram_user_id=%s ORDER BY id DESC LIMIT 1",
            (telegram_user_id,))
        acc = cur.fetchone()
    if acc:
        return {"account_id": acc["id"], "owner_id": acc["owner_id"],
                "business_id": acc.get("business_id") or acc["owner_id"],
                "core_user_id": acc.get("core_user_id"),
                "role": acc.get("role") or "owner",
                "telegram_user_id": acc["telegram_user_id"],
                "created_at": acc["created_at"]}
    return None


def unpair(owner_id: int) -> dict:
    """Remove pairing. Does NOT delete historical intake/audit data."""
    with _pg() as c:
        cur = c.cursor()
        cur.execute("DELETE FROM local_business.telegram_account WHERE owner_id=%s OR business_id=%s",
                    (owner_id, owner_id))
        c.commit()
    return {"ok": True, "unpaired": True}


def is_paired(owner_id: int, telegram_user_id: int) -> bool:
    """Authorize by user_id only; username is never authority."""
    with _pg() as c:
        cur = c.cursor()
        cur.execute(
            "SELECT 1 FROM local_business.telegram_account "
            "WHERE (owner_id=%s OR business_id=%s) AND telegram_user_id=%s",
            (owner_id, owner_id, telegram_user_id))
        return cur.fetchone() is not None


# ============================================================ confirmation gate
def confirm_pending(*, batch_id: str, owner_id: int, telegram_user_id: int,
                    business_id: int, tenant_id: str, branch_id: int,
                    warehouse_id: int) -> dict:
    """Explicit confirmation gate for Telegram inline callbacks.

    Re-checks: pairing active, same telegram_user_id, batch belongs to same
    business, batch confirmable. Replays return the stored idempotent result
    (no duplicate business/Finance effect).
    """
    if not is_paired(owner_id, telegram_user_id):
        return {"ok": False, "error": "unpaired"}

    from . import intake

    # verify batch belongs to business (batch_id is the durable string key)
    with _pg() as c:
        cur = c.cursor()
        cur.execute(
            "SELECT batch_id, status, business_id FROM local_business.intake_batch WHERE batch_id=%s",
            (batch_id,))
        b = cur.fetchone()
        if not b:
            return {"ok": False, "error": "no_batch"}
        if b["business_id"] != business_id:
            return {"ok": False, "error": "batch_wrong_business"}
        batch_key = b["batch_id"]
        cur.execute(
            "SELECT status FROM local_business.intake_batch WHERE batch_id=%s", (batch_id,))
        b2 = cur.fetchone()
        if b2["status"] not in ("PREVIEW", "COMMITTED"):
            return {"ok": False, "error": f"batch_{b2['status']}"}

    return intake.confirm_batch(
        batch_id=batch_key, business_id=business_id, tenant_id=tenant_id,
        branch_id=branch_id, warehouse_id=warehouse_id, actor=f"tg:{telegram_user_id}")


# ============================================================ cancellation gate
def cancel_pending(*, batch_id: str, owner_id: int, telegram_user_id: int,
                   business_id: int) -> dict:
    """Atomically invalidate a PREVIEW Telegram draft (canonical cancel).

    Uses durable batch state (never in-memory). Cancellation is authorized by
    the incoming numeric Telegram user_id (never username) and requires the
    batch to belong to the caller's owner/business scope.

    A PREVIEW batch is atomically set to REJECTED (the schema-documented
    invalidated/cancelled draft state, same state used to neutralize stale
    drafts). Rows and audit evidence are preserved; no Product/Inventory/
    Finance mutation occurs. A repeat cancel on an already-REJECTED batch is a
    safe idempotent no-op. A COMMITTED batch is never reverted or altered; a
    truthful already-committed response is returned.
    """
    if not is_paired(owner_id, telegram_user_id):
        return {"ok": False, "error": "unpaired"}

    with _pg() as c:
        cur = c.cursor()
        cur.execute(
            "SELECT id, batch_id, status, business_id FROM local_business.intake_batch "
            "WHERE batch_id=%s FOR UPDATE",
            (batch_id,))
        b = cur.fetchone()
        if not b:
            c.rollback()
            return {"ok": False, "error": "no_batch"}
        if b["business_id"] != business_id:
            c.rollback()
            return {"ok": False, "error": "batch_wrong_business"}
        status = b["status"]
        if status == "PREVIEW":
            cur.execute(
                "UPDATE local_business.intake_batch SET status='REJECTED' WHERE id=%s",
                (b["id"],))
            c.commit()
            return {"ok": True, "cancelled": True, "batch_id": b["batch_id"]}
        if status == "REJECTED":
            c.rollback()
            return {"ok": True, "cancelled": False, "idempotent": True,
                    "batch_id": b["batch_id"]}
        c.rollback()
        return {"ok": False, "error": f"cannot_cancel_{status}",
                "batch_id": b["batch_id"]}


# ============================================================ intake draft funnel
def submit_intake_draft(*, business_id: int, telegram_user_id: int,
                        owner_id: int, format: str, filename: str,
                        content: bytes, actor: str = "") -> dict:
    """Funnel a Telegram-originated file into the canonical Intake Engine.

    No direct Product/Inventory/Finance mutation. Returns PREVIEW batch.
    """
    from . import intake
    return intake.create_draft(
        business_id=business_id, source="TELEGRAM", filename=filename,
        format=format, content=content, actor=actor or f"tg:{telegram_user_id}")


def submit_text_product(*, business_id: int, telegram_id: int, owner_id: int,
                        text: str, actor: str = "") -> dict:
    """Parse a simple text product draft into an intake draft (preview only).

    Supports both comma and pipe separators. Field semantics are DETERMINISTIC
    and backward compatible:

      4 fields  SKU|Name|SellingPrice|Qty
         sku=1 name=2 price=3 cost=None/empty qty=4
      5 fields  SKU|Name|SellingPrice|Cost|Qty
         sku=1 name=2 price=3 cost=4 qty=5

    A 4-field input is never reinterpreted with the 4th value as cost. Any
    other field count (1,2,3,6+) is returned as a usage error and does NOT
    create a business-mutable draft.
    """
    from . import intake
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    content = "SKU,Nama Barang,Harga Jual,Harga Modal,Stok\n"
    for ln in lines:
        parts = [p.strip() for p in re.split(r"[,\|]", ln)]
        n = len(parts)
        if n not in (4, 5):
            return {
                "ok": False,
                "error": "format_salah",
                "usage": "/barang SKU|Nama|Harga|Stok atau /barang SKU|Nama|Harga|Modal|Stok",
            }
        sku = parts[0]
        name = parts[1]
        price = parts[2]
        if n == 4:
            cost = ""
            qty = parts[3]
        else:
            cost = parts[3]
            qty = parts[4]
        content += f"{sku},{name or sku},{price},{cost},{qty}\n"
    return intake.create_draft(
        business_id=business_id, source="TELEGRAM", filename="text-products.csv",
        format="CSV", content=content.encode("utf-8"), actor=actor or f"tg:{telegram_id}")


def submit_barcode_product(*, business_id: int, telegram_id: int, owner_id: int,
                           text: str, actor: str = "") -> dict:
    """Parse a /barcode product draft into an intake draft (preview only).

    Deterministic field semantics (pipe or comma separators):

      5 fields  Barcode|SKU|Name|SellingPrice|Qty
         barcode=1 sku=2 name=3 price=4 cost=None/empty qty=5
      6 fields  Barcode|SKU|Name|SellingPrice|Cost|Qty
         barcode=1 sku=2 name=3 price=4 cost=5 qty=6

    Any other field count returns a usage error and does NOT create a
    business-mutable draft. A 5-field input is never reinterpreted with the
    5th value as cost.
    """
    from . import intake
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    content = "SKU,Nama Barang,Barcode,Harga Jual,Harga Modal,Stok\n"
    for ln in lines:
        parts = [p.strip() for p in re.split(r"[,\|]", ln)]
        n = len(parts)
        if n not in (5, 6):
            return {
                "ok": False,
                "error": "format_salah",
                "usage": "/barcode Barcode|SKU|Nama|Harga|Stok atau /barcode Barcode|SKU|Nama|Harga|Modal|Stok",
            }
        barcode = parts[0]
        sku = parts[1]
        name = parts[2]
        price = parts[3]
        if n == 5:
            cost = ""
            qty = parts[4]
        else:
            cost = parts[4]
            qty = parts[5]
        if not barcode:
            return {
                "ok": False,
                "error": "barcode_kosong",
                "usage": "/barcode Barcode|SKU|Nama|Harga|Stok atau /barcode Barcode|SKU|Nama|Harga|Modal|Stok",
            }
        content += f"{sku},{name or sku},{barcode},{price},{cost},{qty}\n"
    return intake.create_draft(
        business_id=business_id, source="TELEGRAM", filename="barcode-products.csv",
        format="CSV", content=content.encode("utf-8"), actor=actor or f"tg:{telegram_id}")


def render_text_preview(batch_id: str, *, ready_rows: int = 0,
                        warning_rows: int = 0) -> dict:
    """Build a truthful Telegram preview for a text product draft.

    Shows the exact parsed fields the human is about to commit (SKU, name,
    selling price, cost/modal or '-', opening stock, status, issues). A
    functional Confirm is offered only when at least one row is committable
    under canonical semantics (READY/WARNING committable; REJECTED not).
    Returns ok=True (attach Confirm) when committable, ok=False (no Confirm)
    otherwise.
    """
    from . import intake
    pv = intake.preview(batch_id)
    rows = pv.get("rows") or []
    if not rows:
        return {"ok": False,
                "message": "Tidak ada baris terbaca untuk preview."}

    lines = [f"Produk draft: {len(rows)} baris"]
    committable = 0
    for r in rows:
        status = r["status"]
        price = r.get("selling_price")
        cost = r.get("cost")
        qty = r.get("opening_qty")
        issues = r.get("issues") or []
        price_s = str(price) if price is not None else "-"
        cost_s = str(cost) if cost is not None else "-"
        qty_s = str(qty) if qty is not None else "-"
        block = [
            "",
            f"SKU: {r.get('sku') or '-'}",
            f"Nama: {r.get('name') or '-'}",
            f"Harga jual: {price_s}",
            f"Modal: {cost_s}",
            f"Stok: {qty_s}",
            f"Status: {status}",
        ]
        if r.get("barcode"):
            block.insert(1, f"Barcode: {r['barcode']}")
        if issues:
            block.append("Peringatan: " + "; ".join(str(i) for i in issues))
        lines.append("\n".join(block))
        if status in ("READY", "WARNING"):
            committable += 1
    message = "\n".join(lines)
    if committable == 0:
        return {"ok": False, "message": message + "\n\nTidak ada produk yang bisa dikonfirmasi (semua ditolak). Perbaiki data lalu kirim ulang /barang."}
    return {"ok": True, "message": message,
            "committable_rows": committable}
