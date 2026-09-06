"""Telegram V2 Bot Registry, Destination Manager, and Execution Context.

Owns:
  - SYSTEM_GLOBAL vs CUSTOMER_BYOB Bot Registry
  - Bot Scopes (BUSINESS, BRANCH, INVENTORY, RESTAURANT, KITCHEN, FINANCE, ADMIN)
  - Destinations (Private, Group, Supergroup)
  - Notification Rules (LOW_STOCK, OUT_OF_STOCK, DAILY_SUMMARY, DAILY_SUMMARY_FINAL)
  - TelegramExecutionContext resolution & multi-tenant business context switching
"""

from __future__ import annotations

import os
import uuid
import secrets
from dataclasses import dataclass
from typing import Any

from ..persistence.db import koneksi as _pg, ambil, semua, jalankan
from . import crypto
from .bot_client import BotApiClient, TelegramError


@dataclass
class TelegramExecutionContext:
    telegram_user_id: int
    chat_id: int
    business_id: int
    core_user_id: str | None
    membership_id: int | None
    role: str
    branch_id: int | None
    warehouse_id: int | None
    bot_id: int | None
    source_type: str  # 'GLOBAL_POLLER' | 'BYOB_WEBHOOK'
    is_group: bool
    available_businesses: list[dict]
    business_name: str = ""
    branch_name: str = ""

    @property
    def is_admin(self) -> bool:
        return self.role in ("owner", "admin")

    @property
    def can_manage_inventory(self) -> bool:
        return self.role in ("owner", "admin", "inventory_manager", "staff")

    @property
    def can_manage_procurement(self) -> bool:
        return self.role in ("owner", "admin", "procurement")

    @property
    def can_manage_finance(self) -> bool:
        return self.role in ("owner", "admin", "finance")


# ============================================================ BOT REGISTRY
def register_byob_bot(
    *,
    business_id: int,
    raw_token: str,
    display_name: str = "",
    created_by_core_user_id: str | None = None,
    public_base_url: str = "https://botconnector.id",
) -> dict:
    """Register a new customer-owned BYOB Telegram Bot."""
    if not raw_token or not raw_token.strip():
        return {"ok": False, "error": "Token BotFather tidak boleh kosong"}

    clean_token = raw_token.strip()

    # 1. Validate with getMe
    try:
        temp_client = BotApiClient(clean_token, timeout=10.0)
        me = temp_client.get_me()
        temp_client.close()
    except TelegramError as exc:
        return {"ok": False, "error": f"Token Telegram tidak valid: {exc}"}
    except Exception as exc:
        return {"ok": False, "error": f"Gagal memverifikasi token dengan Telegram: {type(exc).__name__}"}

    bot_id = int(me.get("id", 0))
    username = str(me.get("username", "")).lstrip("@")
    bot_name = display_name.strip() or str(me.get("first_name", ""))

    if not bot_id or not username:
        return {"ok": False, "error": "Respons bot Telegram tidak lengkap"}

    # 2. Check if bot_id is already active anywhere
    with _pg() as c:
        cur = c.cursor()
        cur.execute(
            "SELECT id, business_id FROM local_business.telegram_bot WHERE bot_id=%s AND status='ACTIVE'",
            (bot_id,),
        )
        existing = cur.fetchone()
        if existing:
            if int(existing["business_id"]) == business_id:
                return {"ok": False, "error": f"Bot @{username} sudah terdaftar aktif untuk bisnis ini"}
            return {"ok": False, "error": f"Bot @{username} sudah aktif terdaftar pada bisnis lain"}

    # 3. Encrypt token & generate webhook credentials
    ciphertext = crypto.encrypt_token(clean_token)
    public_id = "bot-" + uuid.uuid4().hex[:16]
    webhook_secret = secrets.token_urlsafe(32)
    secret_hash = crypto.hash_secret(webhook_secret)

    # 4. Configure Webhook on Telegram
    webhook_url = f"{public_base_url.rstrip('/')}/bisnis/api/webhooks/telegram/{public_id}"
    try:
        setup_client = BotApiClient(clean_token, timeout=10.0)
        set_ok = setup_client.set_webhook(
            url=webhook_url,
            secret_token=webhook_secret,
            drop_pending_updates=False,
        )
        setup_client.close()
        if not set_ok:
            return {"ok": False, "error": "Telegram setWebhook mengembalikan False"}
    except Exception as exc:
        return {"ok": False, "error": f"Gagal mengonfigurasi webhook Telegram: {exc}"}

    # 5. Insert into DB
    with _pg() as c:
        cur = c.cursor()
        cur.execute(
            """
            INSERT INTO local_business.telegram_bot
            (public_id, business_id, bot_type, bot_id, bot_username, display_name,
             token_ciphertext, webhook_secret_hash, status, created_by_core_user_id)
            VALUES (%s, %s, 'CUSTOMER_BYOB', %s, %s, %s, %s, %s, 'ACTIVE', %s)
            RETURNING id, public_id, bot_id, bot_username, display_name, status, created_at
            """,
            (
                public_id,
                business_id,
                bot_id,
                username,
                bot_name,
                ciphertext,
                secret_hash,
                created_by_core_user_id,
            ),
        )
        row = cur.fetchone()
        bot_db_id = row["id"]

        # Default business-wide scope
        cur.execute(
            """
            INSERT INTO local_business.telegram_bot_scope (telegram_bot_id, scope_type, scope_id)
            VALUES (%s, 'BUSINESS', %s)
            """,
            (bot_db_id, business_id),
        )
        c.commit()

    return {
        "ok": True,
        "bot": {
            "id": row["id"],
            "public_id": row["public_id"],
            "bot_id": row["bot_id"],
            "bot_username": row["bot_username"],
            "display_name": row["display_name"],
            "status": row["status"],
            "created_at": row["created_at"].isoformat() if row.get("created_at") else "",
        },
    }


def list_business_bots(business_id: int) -> list[dict]:
    """List all registered bots for a business (never returns tokens)."""
    with _pg() as c:
        cur = c.cursor()
        cur.execute(
            """
            SELECT b.id, b.public_id, b.bot_type, b.bot_id, b.bot_username, b.display_name,
                   b.status, b.created_at, b.updated_at,
                   COUNT(DISTINCT d.id) as destination_count
            FROM local_business.telegram_bot b
            LEFT JOIN local_business.telegram_destination d ON d.telegram_bot_id = b.id AND d.status='ACTIVE'
            WHERE b.business_id = %s
            GROUP BY b.id
            ORDER BY b.id ASC
            """,
            (business_id,),
        )
        rows = cur.fetchall()
        result = []
        for r in rows:
            # Fetch scopes
            cur.execute(
                "SELECT scope_type, scope_id FROM local_business.telegram_bot_scope WHERE telegram_bot_id=%s",
                (r["id"],),
            )
            scopes = cur.fetchall()
            result.append({
                "id": r["id"],
                "public_id": r["public_id"],
                "bot_type": r["bot_type"],
                "bot_id": r["bot_id"],
                "bot_username": r["bot_username"],
                "display_name": r["display_name"],
                "status": r["status"],
                "destination_count": int(r["destination_count"] or 0),
                "scopes": [dict(s) for s in scopes],
                "created_at": r["created_at"].isoformat() if r.get("created_at") else "",
            })
        return result


def get_bot_by_public_id(public_id: str) -> dict | None:
    """Lookup bot by public_id (for webhook incoming update routing)."""
    with _pg() as c:
        cur = c.cursor()
        cur.execute(
            """
            SELECT id, public_id, business_id, bot_type, bot_id, bot_username,
                   display_name, token_ciphertext, webhook_secret_hash, status
            FROM local_business.telegram_bot
            WHERE public_id=%s
            """,
            (public_id,),
        )
        return cur.fetchone()


def get_bot_client(bot_record: dict) -> BotApiClient:
    """Instantiate a safe BotApiClient for a bot record."""
    if bot_record.get("bot_type") == "SYSTEM_GLOBAL":
        token = os.environ.get("BC_BISNIS_TELEGRAM_BOT_TOKEN", "").strip()
    else:
        ciphertext = bot_record.get("token_ciphertext", "")
        token = crypto.decrypt_token(ciphertext)
    return BotApiClient(token)


def delete_bot(business_id: int, bot_id_or_public_id: str | int) -> dict:
    """Delete a BYOB bot and remove its webhook."""
    with _pg() as c:
        cur = c.cursor()
        if isinstance(bot_id_or_public_id, int) or str(bot_id_or_public_id).isdigit():
            cur.execute(
                "SELECT * FROM local_business.telegram_bot WHERE id=%s AND business_id=%s",
                (int(bot_id_or_public_id), business_id),
            )
        else:
            cur.execute(
                "SELECT * FROM local_business.telegram_bot WHERE public_id=%s AND business_id=%s",
                (str(bot_id_or_public_id), business_id),
            )
        bot = cur.fetchone()
        if not bot:
            return {"ok": False, "error": "Bot tidak ditemukan"}

        # Delete webhook on Telegram
        try:
            client = get_bot_client(bot)
            client.delete_webhook(drop_pending_updates=False)
            client.close()
        except Exception:
            pass

        cur.execute("DELETE FROM local_business.telegram_bot WHERE id=%s", (bot["id"],))
        c.commit()

    return {"ok": True, "deleted": True}


# ============================================================ DESTINATIONS
def create_destination_pairing(
    *,
    business_id: int,
    core_user_id: str | None = None,
    telegram_bot_id: int | None = None,
    destination_type: str = "PRIVATE",
    branch_id: int | None = None,
    purpose: str = "GENERAL",
    ttl_seconds: int = 600,
) -> dict:
    """Create a pairing token for linking a private or group destination."""
    from . import telegram_intake

    token_res = telegram_intake.create_pairing_token(
        owner_id=business_id,
        business_id=business_id,
        ttl_seconds=ttl_seconds,
    )
    raw_token = token_res["raw_token"]
    h = telegram_intake._hash_token(raw_token)

    with _pg() as c:
        cur = c.cursor()
        cur.execute(
            """
            UPDATE local_business.telegram_pairing
            SET core_user_id=%s, destination_type=%s, telegram_bot_id=%s,
                branch_id=%s, purpose=%s
            WHERE token_hash=%s
            """,
            (core_user_id, destination_type, telegram_bot_id, branch_id, purpose, h),
        )
        c.commit()

    # Determine bot username
    bot_username = ""
    if telegram_bot_id:
        b = ambil(
            "SELECT id, bot_username FROM local_business.telegram_bot WHERE id=%s AND business_id=%s AND status='ACTIVE'",
            (telegram_bot_id, business_id),
        )
        if b:
            bot_username = b["bot_username"]
        else:
            return {"ok": False, "error": "Bot kustom tidak ditemukan untuk bisnis ini"}
    if not bot_username:
        bot_username = os.environ.get("BC_BISNIS_TELEGRAM_BOT_USERNAME", "Botconector_Bot")

    deep_link = (
        f"https://t.me/{bot_username}?startgroup={raw_token}"
        if destination_type in ("GROUP", "SUPERGROUP")
        else f"https://t.me/{bot_username}?start={raw_token}"
    )

    return {
        "ok": True,
        "pairing_token": raw_token,
        "destination_type": destination_type,
        "bot_username": bot_username,
        "pairing_url": deep_link,
        "expires_at": token_res["expires_at"].isoformat() if hasattr(token_res["expires_at"], "isoformat") else str(token_res["expires_at"]),
    }


def resolve_destination_pairing(
    raw_token: str,
    chat_id: int,
    telegram_user_id: int,
    chat_title: str = "",
    chat_type: str = "private",
) -> dict:
    """Resolve /start or /startgroup pairing token and register destination."""
    from . import telegram_intake

    h = telegram_intake._hash_token(raw_token)
    with _pg() as c:
        cur = c.cursor()
        cur.execute(
            "SELECT * FROM local_business.telegram_pairing WHERE token_hash=%s FOR UPDATE",
            (h,),
        )
        p = cur.fetchone()
        if not p:
            return {"ok": False, "error": "unknown_token"}
        if p["consumed_at"] is not None:
            return {"ok": False, "error": "token_already_used"}
        if p["expires_at"] is not None and p["expires_at"] < telegram_intake.datetime.now(telegram_intake.timezone.utc):
            return {"ok": False, "error": "token_expired"}

        business_id = p["business_id"] or p["owner_id"]
        core_user_id = p["core_user_id"]
        bot_id = p["telegram_bot_id"]
        branch_id = p["branch_id"]
        purpose = p["purpose"] or "GENERAL"
        dest_type = "GROUP" if chat_id < 0 or chat_type in ("group", "supergroup") else "PRIVATE"
        display_name = chat_title if dest_type == "GROUP" else f"User {telegram_user_id}"

        cur.execute(
            "UPDATE local_business.telegram_pairing SET consumed_at=now() WHERE id=%s",
            (p["id"],),
        )

        # 1. Register / Update telegram_destination
        cur.execute(
            """
            INSERT INTO local_business.telegram_destination
            (business_id, telegram_bot_id, chat_id, chat_type, display_name, branch_id, purpose, status, created_by_core_user_id)
            VALUES (%s, %s, %s, %s, %s, %s, %s, 'ACTIVE', %s)
            ON CONFLICT (business_id, telegram_bot_id, chat_id)
            DO UPDATE SET status='ACTIVE', display_name=EXCLUDED.display_name, branch_id=EXCLUDED.branch_id, updated_at=now()
            RETURNING id
            """,
            (business_id, bot_id, chat_id, dest_type, display_name, branch_id, purpose, core_user_id),
        )
        dest_row = cur.fetchone()

        # 2. Also register telegram_account for private users
        if dest_type == "PRIVATE":
            cur.execute(
                """
                INSERT INTO local_business.telegram_account
                (owner_id, business_id, telegram_user_id, core_user_id, role, actor)
                VALUES (%s, %s, %s, %s, 'owner', %s)
                ON CONFLICT (owner_id, telegram_user_id)
                DO UPDATE SET business_id=EXCLUDED.business_id, core_user_id=COALESCE(EXCLUDED.core_user_id, local_business.telegram_account.core_user_id), updated_at=now()
                """,
                (business_id, business_id, telegram_user_id, core_user_id, f"tg:{telegram_user_id}"),
            )
            # Default notification rules for private owner
            _ensure_default_rules(cur, business_id, dest_row["id"])

        c.commit()

    return {
        "ok": True,
        "business_id": business_id,
        "destination_id": dest_row["id"],
        "destination_type": dest_type,
        "chat_id": chat_id,
    }


def _ensure_default_rules(cur, business_id: int, destination_id: int):
    """Ensure standard notification rules exist for newly connected destination."""
    for event_type in ("LOW_STOCK", "DAILY_SUMMARY_FINAL"):
        cur.execute(
            """
            INSERT INTO local_business.telegram_notification_rule
            (business_id, destination_id, event_type, enabled)
            VALUES (%s, %s, %s, TRUE)
            ON CONFLICT (business_id, destination_id, event_type, branch_id) DO NOTHING
            """,
            (business_id, destination_id, event_type),
        )


def list_destinations(business_id: int) -> list[dict]:
    """List all registered destinations for a business."""
    with _pg() as c:
        cur = c.cursor()
        cur.execute(
            """
            SELECT d.id, d.business_id, d.telegram_bot_id, d.chat_id, d.chat_type,
                   d.display_name, d.branch_id, d.purpose, d.status, d.created_at,
                   b.bot_username, br.name as branch_name
            FROM local_business.telegram_destination d
            LEFT JOIN local_business.telegram_bot b ON b.id = d.telegram_bot_id
            LEFT JOIN local_business.branch br ON br.id = d.branch_id
            WHERE d.business_id = %s
            ORDER BY d.id ASC
            """,
            (business_id,),
        )
        rows = cur.fetchall()
        result = []
        for r in rows:
            # Fetch active notification rules
            cur.execute(
                "SELECT id, event_type, enabled FROM local_business.telegram_notification_rule WHERE destination_id=%s",
                (r["id"],),
            )
            rules = cur.fetchall()
            result.append({
                "id": r["id"],
                "telegram_bot_id": r["telegram_bot_id"],
                "bot_username": r["bot_username"] or "Botconector_Bot",
                "chat_id": r["chat_id"],
                "chat_type": r["chat_type"],
                "display_name": r["display_name"],
                "branch_id": r["branch_id"],
                "branch_name": r["branch_name"] or "Semua Cabang",
                "purpose": r["purpose"],
                "status": r["status"],
                "rules": [dict(rl) for rl in rules],
                "created_at": r["created_at"].isoformat() if r.get("created_at") else "",
            })
        return result


def set_destination_rules(
    business_id: int,
    destination_id: int,
    rules: list[dict],
) -> dict:
    """Update notification rules for a destination."""
    with _pg() as c:
        cur = c.cursor()
        # Verify destination belongs to business
        cur.execute(
            "SELECT id FROM local_business.telegram_destination WHERE id=%s AND business_id=%s",
            (destination_id, business_id),
        )
        if not cur.fetchone():
            return {"ok": False, "error": "Tujuan tidak ditemukan"}

        for r in rules:
            event_type = r.get("event_type")
            enabled = bool(r.get("enabled", True))
            branch_id = r.get("branch_id")
            if not event_type:
                continue
            cur.execute(
                """
                INSERT INTO local_business.telegram_notification_rule
                (business_id, destination_id, event_type, branch_id, enabled)
                VALUES (%s, %s, %s, %s, %s)
                ON CONFLICT (business_id, destination_id, event_type, branch_id)
                DO UPDATE SET enabled=EXCLUDED.enabled, updated_at=now()
                """,
                (business_id, destination_id, event_type, branch_id, enabled),
            )
        c.commit()
    return {"ok": True}


def delete_destination(business_id: int, destination_id: int) -> dict:
    with _pg() as c:
        cur = c.cursor()
        cur.execute(
            "DELETE FROM local_business.telegram_destination WHERE id=%s AND business_id=%s",
            (destination_id, business_id),
        )
        c.commit()
    return {"ok": True}


# ============================================================ CONTEXT RESOLUTION
def resolve_execution_context(
    telegram_user_id: int,
    chat_id: int,
    bot_info: dict | None = None,
) -> TelegramExecutionContext | None:
    """Derive trusted server-side TelegramExecutionContext.

    Never trusts user text for business_id. Resolves verified pairing & active state.
    """
    is_group = (chat_id < 0)

    # 1. If incoming from BYOB Webhook with explicit business_id
    if bot_info and bot_info.get("business_id"):
        biz_id = int(bot_info["business_id"])
        # Verify membership or pairing for the telegram user in this business
        biz_row = ambil("SELECT id, name FROM local_business.business WHERE id=%s AND status='ACTIVE'", (biz_id,))
        if not biz_row:
            return None

        # Check user account/membership
        acc = ambil(
            "SELECT * FROM local_business.telegram_account WHERE (business_id=%s OR owner_id=%s) AND telegram_user_id=%s",
            (biz_id, biz_id, telegram_user_id),
        )
        role = acc["role"] if acc else ("staff" if is_group else "unauthorized")
        core_user = acc["core_user_id"] if acc else None

        # If linked to core_user_id, re-check current membership table
        if core_user:
            m = ambil(
                "SELECT role, status FROM local_business.business_membership WHERE user_id=%s AND business_id=%s AND status='ACTIVE'",
                (core_user, biz_id),
            )
            if m:
                role = str(m["role"]).lower()

        # Branch resolution
        branches = semua("SELECT id, name, warehouse_id FROM local_business.branch WHERE business_id=%s AND status='ACTIVE' ORDER BY id", (biz_id,))
        branch_id = branches[0]["id"] if branches else None
        warehouse_id = branches[0]["warehouse_id"] if branches else None

        return TelegramExecutionContext(
            telegram_user_id=telegram_user_id,
            chat_id=chat_id,
            business_id=biz_id,
            core_user_id=str(core_user) if core_user else None,
            membership_id=None,
            role=role,
            branch_id=branch_id,
            warehouse_id=warehouse_id,
            bot_id=bot_info.get("id"),
            source_type="BYOB_WEBHOOK",
            is_group=is_group,
            available_businesses=[{"id": biz_id, "name": biz_row["name"]}],
            business_name=biz_row["name"],
            branch_name=branches[0]["name"] if branches else "",
        )

    # 2. Inbound from Global Bot: Resolve user's linked businesses
    accounts = semua(
        """
        SELECT a.id as account_id, a.business_id, a.owner_id, a.core_user_id, a.role,
               b.id as b_id, b.name as business_name, b.status as b_status
        FROM local_business.telegram_account a
        JOIN local_business.business b ON b.id = COALESCE(a.business_id, a.owner_id)
        WHERE a.telegram_user_id = %s AND b.status = 'ACTIVE'
        ORDER BY a.id ASC
        """,
        (telegram_user_id,),
    )

    if not accounts:
        return None

    available = [{"id": a["b_id"], "name": a["business_name"]} for a in accounts]

    # Check persisted active user state
    st = ambil("SELECT active_business_id, active_branch_id FROM local_business.telegram_user_state WHERE telegram_user_id=%s", (telegram_user_id,))
    active_biz_id = None
    if st and any(a["b_id"] == st["active_business_id"] for a in accounts):
        active_biz_id = st["active_business_id"]
    elif len(accounts) == 1:
        active_biz_id = accounts[0]["b_id"]

    if active_biz_id is None:
        # Multi-business user without active selection -> return context indicating selection needed
        return TelegramExecutionContext(
            telegram_user_id=telegram_user_id,
            chat_id=chat_id,
            business_id=0,  # 0 indicates prompt needed
            core_user_id=None,
            membership_id=None,
            role="viewer",
            branch_id=None,
            warehouse_id=None,
            bot_id=None,
            source_type="GLOBAL_POLLER",
            is_group=is_group,
            available_businesses=available,
            business_name="",
            branch_name="",
        )

    # Resolve chosen business
    matched_acc = next((a for a in accounts if a["b_id"] == active_biz_id), accounts[0])
    biz_id = matched_acc["b_id"]
    biz_name = matched_acc["business_name"]
    role = matched_acc["role"] or "owner"
    core_user = matched_acc["core_user_id"]

    # Re-verify live membership role if core_user_id is linked
    if core_user:
        m = ambil(
            "SELECT role, status FROM local_business.business_membership WHERE user_id=%s AND business_id=%s AND status='ACTIVE'",
            (core_user, biz_id),
        )
        if m:
            role = str(m["role"]).lower()

    # Resolve branch
    branches = semua("SELECT id, name, warehouse_id FROM local_business.branch WHERE business_id=%s AND status='ACTIVE' ORDER BY id", (biz_id,))
    chosen_branch_id = st.get("active_branch_id") if st else None
    active_br = next((b for b in branches if b["id"] == chosen_branch_id), branches[0] if branches else None)

    return TelegramExecutionContext(
        telegram_user_id=telegram_user_id,
        chat_id=chat_id,
        business_id=biz_id,
        core_user_id=str(core_user) if core_user else None,
        membership_id=None,
        role=role,
        branch_id=active_br["id"] if active_br else None,
        warehouse_id=active_br["warehouse_id"] if active_br else None,
        bot_id=None,
        source_type="GLOBAL_POLLER",
        is_group=is_group,
        available_businesses=available,
        business_name=biz_name,
        branch_name=active_br["name"] if active_br else "",
    )


def switch_user_business(telegram_user_id: int, new_business_id: int) -> dict:
    """Switch active business context for a multi-business Telegram user."""
    # Verify user is paired to this business
    acc = ambil(
        """
        SELECT a.id, b.name as business_name
        FROM local_business.telegram_account a
        JOIN local_business.business b ON b.id = COALESCE(a.business_id, a.owner_id)
        WHERE a.telegram_user_id=%s AND b.id=%s AND b.status='ACTIVE'
        """,
        (telegram_user_id, new_business_id),
    )
    if not acc:
        return {"ok": False, "error": "Anda tidak memiliki akses ke bisnis ini"}

    with _pg() as c:
        cur = c.cursor()
        cur.execute(
            """
            INSERT INTO local_business.telegram_user_state (telegram_user_id, active_business_id, updated_at)
            VALUES (%s, %s, now())
            ON CONFLICT (telegram_user_id)
            DO UPDATE SET active_business_id=EXCLUDED.active_business_id, active_branch_id=NULL, updated_at=now()
            """,
            (telegram_user_id, new_business_id),
        )
        c.commit()

    return {"ok": True, "business_id": new_business_id, "business_name": acc["business_name"]}


def switch_user_branch(telegram_user_id: int, business_id: int, branch_id: int) -> dict:
    """Switch active branch for a user."""
    br = ambil("SELECT id, name FROM local_business.branch WHERE id=%s AND business_id=%s", (branch_id, business_id))
    if not br:
        return {"ok": False, "error": "Cabang tidak ditemukan"}

    with _pg() as c:
        cur = c.cursor()
        cur.execute(
            """
            INSERT INTO local_business.telegram_user_state (telegram_user_id, active_business_id, active_branch_id, updated_at)
            VALUES (%s, %s, %s, now())
            ON CONFLICT (telegram_user_id)
            DO UPDATE SET active_business_id=EXCLUDED.active_business_id, active_branch_id=EXCLUDED.active_branch_id, updated_at=now()
            """,
            (telegram_user_id, business_id, branch_id),
        )
        c.commit()

    return {"ok": True, "branch_id": branch_id, "branch_name": br["name"]}
