"""Low-stock threshold management and event-driven transition engine for BC Bisnis.

Design invariants:
- Canonical stock source: `multichannel.inventory_balance` (available = on_hand - reserved - safety_stock).
- Thresholds: Configurable per-SKU and per-business via `local_business.low_stock_threshold`.
  If no threshold is configured, returns None (no alert is fired; never invents an unconfigured threshold).
- Event-driven re-arming state: Managed via `local_business.low_stock_alert_state` keyed by (business_id, warehouse_id, master_sku_id).
  - Downward crossing (> T -> <= T): Fires exactly one alert for the episode (alert_cycle).
  - Remaining below (<= T -> <= T): No repeated alerts (anti-spam).
  - Upward recovery (<= T -> > T): Re-arms the state (is_alerted = False).
  - Subsequent drop (> T -> <= T): Fires one new alert with incremented cycle.
- Outbox integration: Enqueues into `local_business.telegram_alert_outbox` with unique event_key:
  LOW_STOCK:{business_id}:{warehouse_id}:{sku}:{alert_cycle}
- Safety: Alert failure never affects or rolls back the calling business/inventory mutation.
"""

from __future__ import annotations

import json
import secrets
from datetime import datetime, timezone, timedelta

from ..persistence.db import koneksi as _pg


def set_threshold(
    *,
    business_id: int,
    threshold: int,
    master_sku_id: int | None = None,
    cur=None,
) -> dict:
    """Set low-stock threshold for a business default or specific SKU override."""
    if threshold < 0:
        raise ValueError("threshold harus >= 0")

    own = cur is None
    if own:
        c = _pg()
        cur = c.cursor()
    try:
        if master_sku_id is not None:
            cur.execute(
                """INSERT INTO local_business.low_stock_threshold
                   (business_id, master_sku_id, threshold, updated_at)
                   VALUES (%s, %s, %s, now())
                   ON CONFLICT (business_id, master_sku_id) WHERE master_sku_id IS NOT NULL
                   DO UPDATE SET threshold=EXCLUDED.threshold, updated_at=now()
                   RETURNING id, business_id, master_sku_id, threshold""",
                (business_id, master_sku_id, threshold),
            )
        else:
            cur.execute(
                """INSERT INTO local_business.low_stock_threshold
                   (business_id, master_sku_id, threshold, updated_at)
                   VALUES (%s, NULL, %s, now())
                   ON CONFLICT (business_id) WHERE master_sku_id IS NULL
                   DO UPDATE SET threshold=EXCLUDED.threshold, updated_at=now()
                   RETURNING id, business_id, master_sku_id, threshold""",
                (business_id, threshold),
            )
        row = cur.fetchone()
        if own:
            c.commit()
        return dict(row)
    except Exception:
        if own:
            c.rollback()
        raise


def remove_threshold(
    *,
    business_id: int,
    master_sku_id: int,
    cur=None,
) -> dict:
    """Remove SKU-specific threshold for a business."""
    own = cur is None
    if own:
        c = _pg()
        cur = c.cursor()
    try:
        cur.execute(
            """DELETE FROM local_business.low_stock_threshold
               WHERE business_id=%s AND master_sku_id=%s
               RETURNING id, business_id, master_sku_id, threshold""",
            (business_id, master_sku_id),
        )
        row = cur.fetchone()
        if own:
            c.commit()
        return {"ok": True, "deleted": row is not None, "row": dict(row) if row else None}
    except Exception:
        if own:
            c.rollback()
        raise


def get_threshold(
    *,
    business_id: int,
    master_sku_id: int | None = None,
    cur=None,
) -> int | None:
    """Resolve active low-stock threshold.

    1. Checks SKU-specific override.
    2. Falls back to business-level default.
    3. Returns None if unconfigured.
    """
    own = cur is None
    if own:
        c = _pg()
        cur = c.cursor()
    try:
        if master_sku_id is not None:
            cur.execute(
                """SELECT threshold FROM local_business.low_stock_threshold
                   WHERE business_id=%s AND master_sku_id=%s""",
                (business_id, master_sku_id),
            )
            row = cur.fetchone()
            if row is not None:
                return int(row["threshold"])

        cur.execute(
            """SELECT threshold FROM local_business.low_stock_threshold
               WHERE business_id=%s AND master_sku_id IS NULL""",
            (business_id,),
        )
        row = cur.fetchone()
        if row is not None:
            return int(row["threshold"])
        return None
    finally:
        if own:
            c.close()


def list_thresholds(business_id: int, cur=None) -> list[dict]:
    """List all configured SKU-specific thresholds for a business."""
    own = cur is None
    if own:
        c = _pg()
        cur = c.cursor()
    try:
        cur.execute(
            """SELECT t.id, t.business_id, t.master_sku_id, t.threshold,
                      m.sku, p.name AS product_name
               FROM local_business.low_stock_threshold t
               JOIN multichannel.master_sku m ON m.id=t.master_sku_id
               JOIN multichannel.product p ON p.id=m.product_id
               WHERE t.business_id=%s AND t.master_sku_id IS NOT NULL
               ORDER BY m.sku""",
            (business_id,),
        )
        return cur.fetchall()
    finally:
        if own:
            c.close()


def list_low_stock_products(business_id: int, cur=None) -> list[dict]:
    """List products currently at or below their configured threshold for a business."""
    own = cur is None
    if own:
        c = _pg()
        cur = c.cursor()
    try:
        cur.execute(
            """SELECT m.id AS master_sku_id, m.sku, p.name AS product_name,
                      ib.warehouse_id, w.code AS warehouse_code, b.name AS branch_name,
                      ib.on_hand, ib.reserved, ib.safety_stock, ib.available
               FROM local_business.branch b
               JOIN multichannel.warehouse w ON w.id=b.warehouse_id
               JOIN multichannel.inventory_balance ib ON ib.warehouse_id=w.id
               JOIN multichannel.master_sku m ON m.id=ib.master_sku_id
               JOIN multichannel.product p ON p.id=m.product_id
               WHERE b.business_id=%s
               ORDER BY m.sku""",
            (business_id,),
        )
        products = cur.fetchall()
        low_items = []
        for p in products:
            t = get_threshold(business_id=business_id, master_sku_id=p["master_sku_id"], cur=cur)
            if t is not None and p["available"] <= t:
                low_items.append({
                    "master_sku_id": p["master_sku_id"],
                    "sku": p["sku"],
                    "product_name": p["product_name"],
                    "warehouse_id": p["warehouse_id"],
                    "branch_name": p["branch_name"],
                    "available": p["available"],
                    "threshold": t,
                })
        return low_items
    finally:
        if own:
            c.close()


def resolve_sku_product(business_id: int, sku: str, cur=None) -> dict | None:
    """Resolve a product by SKU for a business, checking location balance."""
    own = cur is None
    if own:
        c = _pg()
        cur = c.cursor()
    try:
        cur.execute(
            """SELECT m.id AS master_sku_id, m.sku, p.name AS product_name,
                      COALESCE(ib.available, 0) AS available,
                      b.id AS branch_id, b.warehouse_id
               FROM multichannel.master_sku m
               JOIN multichannel.product p ON p.id=m.product_id
               LEFT JOIN local_business.branch b ON b.business_id=%s
               LEFT JOIN multichannel.inventory_balance ib ON ib.master_sku_id=m.id AND ib.warehouse_id=b.warehouse_id
               WHERE UPPER(m.sku)=UPPER(%s) AND b.business_id=%s
               LIMIT 1""",
            (business_id, sku, business_id),
        )
        row = cur.fetchone()
        return dict(row) if row else None
    finally:
        if own:
            c.close()


def create_threshold_draft(
    *,
    business_id: int,
    owner_id: int,
    telegram_user_id: int,
    sku: str,
    action: str,  # 'SET' | 'REMOVE'
    new_threshold: int | None = None,
    ttl_seconds: int = 600,
    cur=None,
) -> dict:
    """Create a threshold draft with preview info."""
    prod = resolve_sku_product(business_id=business_id, sku=sku, cur=cur)
    if not prod:
        return {"ok": False, "error": "unknown_sku", "sku": sku}

    master_sku_id = prod["master_sku_id"]
    old_threshold = get_threshold(business_id=business_id, master_sku_id=master_sku_id, cur=cur)

    if action == "SET":
        if new_threshold is None or new_threshold < 0:
            return {"ok": False, "error": "invalid_threshold"}
    elif action == "REMOVE":
        new_threshold = None
    else:
        return {"ok": False, "error": "invalid_action"}

    draft_token = "th_" + secrets.token_hex(8)
    expires_at = datetime.now(timezone.utc) + timedelta(seconds=ttl_seconds)

    own = cur is None
    if own:
        c = _pg()
        cur = c.cursor()
    try:
        cur.execute(
            """INSERT INTO local_business.telegram_threshold_draft
               (draft_token, business_id, owner_id, telegram_user_id,
                master_sku_id, sku, action, new_threshold, old_threshold,
                status, expires_at)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, 'PENDING', %s)
               RETURNING id""",
            (draft_token, business_id, owner_id, telegram_user_id,
             master_sku_id, prod["sku"], action, new_threshold, old_threshold,
             expires_at),
        )
        row = cur.fetchone()
        if own:
            c.commit()
        return {
            "ok": True,
            "draft_token": draft_token,
            "master_sku_id": master_sku_id,
            "sku": prod["sku"],
            "product_name": prod["product_name"],
            "available": prod["available"],
            "action": action,
            "old_threshold": old_threshold,
            "new_threshold": new_threshold,
            "expires_at": expires_at,
        }
    except Exception:
        if own:
            c.rollback()
        raise


def confirm_threshold_draft(
    *,
    draft_token: str,
    telegram_user_id: int,
    business_id: int,
    owner_id: int,
) -> dict:
    """Confirm and commit a pending threshold draft."""
    with _pg() as c:
        cur = c.cursor()
        cur.execute(
            """SELECT * FROM local_business.telegram_threshold_draft
               WHERE draft_token=%s FOR UPDATE""",
            (draft_token,),
        )
        draft = cur.fetchone()
        if not draft:
            return {"ok": False, "error": "no_draft"}
        if draft["business_id"] != business_id or draft["owner_id"] != owner_id:
            return {"ok": False, "error": "draft_wrong_business"}
        if draft["telegram_user_id"] != telegram_user_id:
            return {"ok": False, "error": "wrong_user"}

        if draft["status"] == "CONFIRMED":
            # Idempotent re-confirm
            return {
                "ok": True,
                "idempotent": True,
                "action": draft["action"],
                "sku": draft["sku"],
                "new_threshold": draft["new_threshold"],
            }
        if draft["status"] == "CANCELLED":
            return {"ok": False, "error": "draft_cancelled"}
        if draft["expires_at"] < datetime.now(timezone.utc):
            cur.execute(
                "UPDATE local_business.telegram_threshold_draft SET status='EXPIRED' WHERE id=%s",
                (draft["id"],),
            )
            c.commit()
            return {"ok": False, "error": "draft_expired"}

        # Commit change
        master_sku_id = draft["master_sku_id"]
        if draft["action"] == "SET":
            set_threshold(
                business_id=business_id,
                threshold=draft["new_threshold"],
                master_sku_id=master_sku_id,
                cur=cur,
            )
        elif draft["action"] == "REMOVE":
            remove_threshold(
                business_id=business_id,
                master_sku_id=master_sku_id,
                cur=cur,
            )

        cur.execute(
            """UPDATE local_business.telegram_threshold_draft
               SET status='CONFIRMED', confirmed_at=now()
               WHERE id=%s""",
            (draft["id"],),
        )
        c.commit()
        return {
            "ok": True,
            "idempotent": False,
            "action": draft["action"],
            "sku": draft["sku"],
            "new_threshold": draft["new_threshold"],
        }


def cancel_threshold_draft(
    *,
    draft_token: str,
    telegram_user_id: int,
    business_id: int,
    owner_id: int,
) -> dict:
    """Cancel a pending threshold draft."""
    with _pg() as c:
        cur = c.cursor()
        cur.execute(
            """SELECT * FROM local_business.telegram_threshold_draft
               WHERE draft_token=%s FOR UPDATE""",
            (draft_token,),
        )
        draft = cur.fetchone()
        if not draft:
            return {"ok": False, "error": "no_draft"}
        if draft["business_id"] != business_id or draft["owner_id"] != owner_id:
            return {"ok": False, "error": "draft_wrong_business"}
        if draft["telegram_user_id"] != telegram_user_id:
            return {"ok": False, "error": "wrong_user"}

        if draft["status"] == "CANCELLED":
            return {"ok": True, "idempotent": True}
        if draft["status"] == "CONFIRMED":
            return {"ok": False, "error": "already_confirmed"}

        cur.execute(
            """UPDATE local_business.telegram_threshold_draft
               SET status='CANCELLED'
               WHERE id=%s""",
            (draft["id"],),
        )
        c.commit()
        return {"ok": True, "cancelled": True}


def render_threshold_preview(draft_res: dict) -> str:
    """Render preview text for threshold confirmation."""
    sku = draft_res["sku"]
    name = draft_res.get("product_name") or sku
    avail = draft_res.get("available", 0)
    old_t = draft_res.get("old_threshold")
    old_str = f"{old_t}" if old_t is not None else "Belum diatur"

    if draft_res["action"] == "REMOVE":
        new_str = "Nonaktif (off)"
    else:
        new_str = f"{draft_res['new_threshold']}"

    lines = [
        "⚙️ ATUR STOK MINIMUM",
        "",
        f"Produk: {name}",
        f"SKU: {sku}",
        f"Stok sekarang: {avail}",
        "",
        f"Batas lama: {old_str}",
        f"Batas baru: {new_str}",
    ]
    return "\n".join(lines)


def get_alert_state(
    *,
    business_id: int,
    warehouse_id: int,
    master_sku_id: int,
    cur=None,
) -> dict | None:
    """Return the current alert state for a given location and SKU."""
    own = cur is None
    if own:
        c = _pg()
        cur = c.cursor()
    try:
        cur.execute(
            """SELECT id, business_id, warehouse_id, master_sku_id,
                      is_alerted, alert_cycle, last_alerted_at, last_rearmed_at
               FROM local_business.low_stock_alert_state
               WHERE business_id=%s AND warehouse_id=%s AND master_sku_id=%s""",
            (business_id, warehouse_id, master_sku_id),
        )
        return cur.fetchone()
    finally:
        if own:
            c.close()


def evaluate_transition(
    cur,
    *,
    business_id: int,
    branch_id: int = 0,
    warehouse_id: int,
    master_sku_id: int,
    sku: str,
    available_before: int,
    available_after: int,
) -> dict:
    """Evaluate inventory level change against configured low-stock threshold.

    Runs within the caller's cursor transaction.
    """
    threshold = get_threshold(business_id=business_id, master_sku_id=master_sku_id, cur=cur)
    if threshold is None:
        return {"action": "SKIPPED_NO_THRESHOLD", "threshold": None}

    # Fetch current alert state with row lock
    cur.execute(
        """SELECT id, is_alerted, alert_cycle
           FROM local_business.low_stock_alert_state
           WHERE business_id=%s AND warehouse_id=%s AND master_sku_id=%s
           FOR UPDATE""",
        (business_id, warehouse_id, master_sku_id),
    )
    state = cur.fetchone()
    is_alerted = state["is_alerted"] if state else False
    alert_cycle = state["alert_cycle"] if state else 0

    # Downward crossing: (> T -> <= T) OR (new state observing <= T for the first time)
    if (available_before > threshold and available_after <= threshold) or (state is None and available_after <= threshold):
        if is_alerted:
            return {"action": "IGNORED_ALREADY_ALERTED", "alert_cycle": alert_cycle, "threshold": threshold}

        next_cycle = alert_cycle + 1
        cur.execute(
            """INSERT INTO local_business.low_stock_alert_state
               (business_id, warehouse_id, master_sku_id, is_alerted, alert_cycle, last_alerted_at, updated_at)
               VALUES (%s, %s, %s, TRUE, %s, now(), now())
               ON CONFLICT (business_id, warehouse_id, master_sku_id)
               DO UPDATE SET is_alerted=TRUE, alert_cycle=EXCLUDED.alert_cycle,
                             last_alerted_at=now(), updated_at=now()""",
            (business_id, warehouse_id, master_sku_id, next_cycle),
        )

        # Gather metadata for message rendering
        cur.execute(
            """SELECT p.name FROM multichannel.master_sku m
               JOIN multichannel.product p ON p.id=m.product_id
               WHERE m.id=%s""",
            (master_sku_id,),
        )
        prod_row = cur.fetchone()
        product_name = prod_row["name"] if prod_row else sku

        cur.execute(
            """SELECT id, code, name FROM local_business.branch
               WHERE business_id=%s AND warehouse_id=%s LIMIT 1""",
            (business_id, warehouse_id),
        )
        branch_row = cur.fetchone()
        branch_id_resolved = branch_id or (branch_row["id"] if branch_row else 0)
        branch_code = branch_row["code"] if branch_row else ""
        branch_name = branch_row["name"] if branch_row else ""

        cur.execute(
            "SELECT name FROM local_business.business WHERE id=%s",
            (business_id,),
        )
        biz_row = cur.fetchone()
        business_name = biz_row["name"] if biz_row else ""

        # Resolve owner_id for destination
        cur.execute(
            """SELECT owner_id FROM local_business.telegram_account
               WHERE owner_id=%s ORDER BY id DESC LIMIT 1""",
            (business_id,),
        )
        acc_row = cur.fetchone()
        owner_id = acc_row["owner_id"] if acc_row else business_id

        notif_type = "OUT_OF_STOCK" if available_after <= 0 else "LOW_STOCK"
        event_key = f"LOW_STOCK:{business_id}:{warehouse_id}:{sku}:{next_cycle}"

        payload = {
            "business_id": business_id,
            "business_name": business_name,
            "branch_id": branch_id_resolved,
            "branch_code": branch_code,
            "branch_name": branch_name,
            "warehouse_id": warehouse_id,
            "master_sku_id": master_sku_id,
            "sku": sku,
            "product_name": product_name,
            "available_before": available_before,
            "available_after": available_after,
            "threshold": threshold,
            "is_out_of_stock": (available_after <= 0),
            "alert_cycle": next_cycle,
        }

        cur.execute(
            """INSERT INTO local_business.telegram_alert_outbox
               (business_id, owner_id, notification_type, event_key, payload, status)
               VALUES (%s, %s, %s, %s, %s, 'PENDING')
               ON CONFLICT (notification_type, event_key)
               DO NOTHING
               RETURNING id""",
            (business_id, owner_id, notif_type, event_key, json.dumps(payload)),
        )
        outbox_row = cur.fetchone()
        return {
            "action": "ENQUEUED",
            "notification_type": notif_type,
            "event_key": event_key,
            "alert_cycle": next_cycle,
            "outbox_id": outbox_row["id"] if outbox_row else None,
            "threshold": threshold,
        }

    # Upward recovery: (<= T -> > T)
    if available_before <= threshold and available_after > threshold:
        cur.execute(
            """INSERT INTO local_business.low_stock_alert_state
               (business_id, warehouse_id, master_sku_id, is_alerted, alert_cycle, last_rearmed_at, updated_at)
               VALUES (%s, %s, %s, FALSE, %s, now(), now())
               ON CONFLICT (business_id, warehouse_id, master_sku_id)
               DO UPDATE SET is_alerted=FALSE, last_rearmed_at=now(), updated_at=now()""",
            (business_id, warehouse_id, master_sku_id, alert_cycle),
        )
        return {"action": "REARMED", "alert_cycle": alert_cycle, "threshold": threshold}

    # Remaining below threshold without re-crossing
    if available_before <= threshold and available_after <= threshold:
        return {"action": "IN_EPISODE_NOOP", "alert_cycle": alert_cycle, "threshold": threshold}

    return {"action": "NORMAL_NOOP", "threshold": threshold}
