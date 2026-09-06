"""BC Bisnis Telegram owner-alert outbound dispatcher.

Handles:
  - Destination resolution (Private chats & Groups via notification rules or legacy accounts)
  - Multi-destination outbox enqueuing with deduplication
  - Multi-bot client dispatching (Global Bot vs BYOB Bot via BotApiClient)
  - Multi-tenant daily summary scheduling across all active businesses

Telegram delivery is a SIDE EFFECT only. A Telegram failure must NEVER roll
back or alter sale/inventory/Product/price/Finance/reporting.

Delivery states: PENDING -> SENDING -> SENT / FAILED / UNKNOWN / CANCELLED.
"""

from __future__ import annotations

import os
import sys
import json
import logging
from datetime import datetime, timezone, timedelta, date as _date

from ..persistence.db import koneksi as _pg, ambil, semua
from .bot_client import BotApiClient, TelegramError
from . import telegram_registry as reg

TOKEN_ENV = "BC_BISNIS_TELEGRAM_BOT_TOKEN"
ALERT_STATES = ("PENDING", "SENDING", "SENT", "FAILED", "UNKNOWN", "CANCELLED")

log = logging.getLogger("bc.bisnis.telegram.outbound")


# --------------------------------------------------------------------------- destination resolution
def resolve_destinations_for_event(
    *,
    business_id: int,
    event_type: str,
    branch_id: int | None = None,
) -> list[dict]:
    """Resolve all active destinations matching an event type and optional branch."""
    with _pg() as c:
        cur = c.cursor()
        # 1. Query explicit notification rules
        cur.execute(
            """
            SELECT d.id as destination_id, d.chat_id, d.chat_type, d.telegram_bot_id,
                   d.business_id, b.bot_type, b.token_ciphertext
            FROM local_business.telegram_notification_rule r
            JOIN local_business.telegram_destination d ON d.id = r.destination_id
            LEFT JOIN local_business.telegram_bot b ON b.id = d.telegram_bot_id
            WHERE r.business_id = %s
              AND r.event_type = %s
              AND r.enabled = TRUE
              AND d.status = 'ACTIVE'
              AND (r.branch_id IS NULL OR r.branch_id = %s)
            """,
            (business_id, event_type, branch_id),
        )
        destinations = cur.fetchall()
        if destinations:
            return [dict(d) for d in destinations]

        # 2. Fallback to legacy telegram_account
        cur.execute(
            """
            SELECT NULL as destination_id, telegram_user_id as chat_id, 'PRIVATE' as chat_type,
                   NULL as telegram_bot_id, COALESCE(business_id, owner_id) as business_id,
                   'SYSTEM_GLOBAL' as bot_type, NULL as token_ciphertext
            FROM local_business.telegram_account
            WHERE (business_id = %s OR owner_id = %s)
            ORDER BY id DESC LIMIT 1
            """,
            (business_id, business_id),
        )
        legacy = cur.fetchone()
        if legacy and legacy.get("chat_id"):
            return [dict(legacy)]

    return []


def resolve_owner_destination(*, business_id: int) -> dict:
    """Legacy helper: Resolve the single primary private Telegram user ID."""
    dests = resolve_destinations_for_event(business_id=business_id, event_type="DAILY_SUMMARY")
    if dests:
        return {
            "ok": True,
            "owner_id": business_id,
            "telegram_user_id": dests[0]["chat_id"],
            "destination_id": dests[0].get("destination_id"),
            "telegram_bot_id": dests[0].get("telegram_bot_id"),
        }
    return {
        "ok": False,
        "reason": "NO_DESTINATION",
        "owner_id": business_id,
        "telegram_user_id": None,
    }


# --------------------------------------------------------------------------- outbox
def _enqueue(
    *,
    business_id: int,
    owner_id: int,
    notification_type: str,
    event_key: str,
    local_date,
    payload: dict,
    destination_id: int | None = None,
    chat_id: int | None = None,
    telegram_bot_id: int | None = None,
) -> dict:
    """Insert an outbox item idempotently. Same logical key -> one row."""
    with _pg() as c:
        cur = c.cursor()
        cur.execute(
            """INSERT INTO local_business.telegram_alert_outbox
               (business_id, owner_id, notification_type, event_key, local_date,
                payload, status, destination_id, chat_id, telegram_bot_id)
               VALUES (%s,%s,%s,%s,%s,%s,'PENDING',%s,%s,%s)
               ON CONFLICT (notification_type, event_key)
               DO NOTHING
               RETURNING id""",
            (
                business_id,
                owner_id,
                notification_type,
                event_key,
                local_date,
                json.dumps(payload, default=str),
                destination_id,
                chat_id,
                telegram_bot_id,
            ),
        )
        row = cur.fetchone()
        c.commit()
    return {"ok": True, "deduped": row is None, "outbox_id": row["id"] if row else None}


def enqueue_daily_summary(*, business_id: int, local_date, timezone: str = "UTC") -> dict:
    """Build today's daily summary and enqueue for all matching destinations."""
    from . import reporting as R

    summary = R.daily_summary(business_id=business_id, local_date=local_date, timezone=timezone)
    if not summary.get("ok"):
        return summary

    dests = resolve_destinations_for_event(
        business_id=business_id, event_type="DAILY_SUMMARY"
    )
    if not dests:
        return {"ok": False, "reason": "NO_DESTINATION", "summary": summary}

    enqueued_ids = []
    for d in dests:
        dest_suffix = f":dest-{d['destination_id']}" if d.get("destination_id") else ""
        event_key = f"DAILY_SUMMARY:{business_id}:{local_date}:{timezone}{dest_suffix}"
        res = _enqueue(
            business_id=business_id,
            owner_id=business_id,
            notification_type="DAILY_SUMMARY",
            event_key=event_key,
            local_date=local_date,
            payload={"summary": summary},
            destination_id=d.get("destination_id"),
            chat_id=d.get("chat_id"),
            telegram_bot_id=d.get("telegram_bot_id"),
        )
        if res.get("outbox_id"):
            enqueued_ids.append(res["outbox_id"])

    return {"ok": True, "enqueued_ids": enqueued_ids, "summary": summary}


def render_daily_message(summary: dict) -> str:
    """Render a concise Indonesian daily summary message."""
    biz = summary.get("business_name", "-")
    omzet = summary.get("omzet", 0)
    count = summary.get("transaction_count", 0)
    local_date = summary.get("local_date", "")
    lines = [
        "📊 RINGKASAN HARIAN",
        biz,
        local_date or "",
        "",
        f"Omzet: Rp {omzet:,.0f}".replace(",", "."),
        f"Transaksi: {count}",
    ]
    methods = summary.get("payment_methods") or {}
    if methods:
        lines.append("")
        for method, total in methods.items():
            lines.append(f"{method}: Rp{total:,.0f}".replace(",", "."))
    return "\n".join(lines)


def render_low_stock_message(payload: dict) -> str:
    """Render a concise Indonesian low-stock / out-of-stock message."""
    biz_name = payload.get("business_name") or ""
    branch_name = payload.get("branch_name") or payload.get("branch_code") or ""
    sku = payload.get("sku", "")
    name = payload.get("product_name") or sku
    stock = payload.get("available_after", 0)
    threshold = payload.get("threshold", 0)
    is_oos = payload.get("is_out_of_stock", False) or stock <= 0

    header = "🚨 STOK HABIS" if is_oos else "⚠️ STOK MENIPIS"
    lines = [
        header,
    ]
    if biz_name or branch_name:
        loc = f"{biz_name} — {branch_name}" if (biz_name and branch_name) else (biz_name or branch_name)
        lines.append(loc)
    lines.extend([
        "",
        f"Produk: {name}",
        f"SKU: {sku}",
        f"Sisa Stok: {stock}",
        f"Batas Minimum: {threshold}",
    ])
    return "\n".join(lines).strip()


def render_outbound_message(notification_type: str, payload: dict) -> str:
    """Route notification rendering by notification_type."""
    if notification_type in ("DAILY_SUMMARY", "DAILY_SUMMARY_FINAL"):
        return render_daily_message(payload.get("summary", {}))
    if notification_type in ("LOW_STOCK", "OUT_OF_STOCK"):
        return render_low_stock_message(payload)
    return str(payload)


# --------------------------------------------------------------------------- dispatch
def _claim_next(*, max_rows: int = 5) -> list[dict]:
    """Atomically claim due PENDING/FAILED(eligible) rows as SENDING."""
    with _pg() as c:
        cur = c.cursor()
        cur.execute(
            """UPDATE local_business.telegram_alert_outbox
               SET status='SENDING', attempt_count=attempt_count+1, updated_at=now()
               WHERE id IN (
                 SELECT id FROM local_business.telegram_alert_outbox
                 WHERE status='PENDING' AND next_attempt_at <= now()
                 ORDER BY id
                 LIMIT %s
               )
               RETURNING id, business_id, owner_id, notification_type, event_key,
                         payload, telegram_message_id, destination_id, chat_id, telegram_bot_id""",
            (max_rows,),
        )
        rows = cur.fetchall()
        c.commit()
        return [dict(r) for r in rows]


def _mark_sent(outbox_id: int, message_id=None) -> None:
    with _pg() as c:
        cur = c.cursor()
        cur.execute(
            """UPDATE local_business.telegram_alert_outbox
               SET status='SENT', sent_at=now(), updated_at=now(),
                   telegram_message_id=COALESCE(%s, telegram_message_id)
               WHERE id=%s""",
            (message_id, outbox_id),
        )
        c.commit()


def _mark_failed(outbox_id: int, error: str) -> None:
    with _pg() as c:
        cur = c.cursor()
        cur.execute(
            """UPDATE local_business.telegram_alert_outbox
               SET status='FAILED', last_error=%s, updated_at=now()
               WHERE id=%s""",
            (str(error)[:500], outbox_id),
        )
        c.commit()


def _mark_unknown(outbox_id: int, error: str) -> None:
    with _pg() as c:
        cur = c.cursor()
        cur.execute(
            """UPDATE local_business.telegram_alert_outbox
               SET status='UNKNOWN', last_error=%s, updated_at=now()
               WHERE id=%s""",
            (str(error)[:500], outbox_id),
        )
        c.commit()


def get_outbox_state(outbox_id: int) -> dict:
    """Return the current durable state of one outbox row (read-only)."""
    with _pg() as c:
        cur = c.cursor()
        cur.execute(
            "SELECT id, business_id, owner_id, notification_type, event_key, status, "
            "attempt_count, telegram_message_id, sent_at, last_error, "
            "destination_id, chat_id, telegram_bot_id "
            "FROM local_business.telegram_alert_outbox WHERE id=%s",
            (outbox_id,),
        )
        row = cur.fetchone()
    if not row:
        return {"ok": False, "error": "no_outbox_row", "outbox_id": outbox_id}
    return dict(row)


def _claim_one(outbox_id: int) -> dict | None:
    """Atomically claim ONE outbox row (PENDING & due) -> SENDING. None if not claimable."""
    with _pg() as c:
        cur = c.cursor()
        cur.execute(
            """UPDATE local_business.telegram_alert_outbox
               SET status='SENDING', attempt_count=attempt_count+1, updated_at=now()
               WHERE id=%s AND status='PENDING' AND next_attempt_at <= now()
               RETURNING id, business_id, owner_id, notification_type, event_key,
                         payload, telegram_message_id, destination_id, chat_id, telegram_bot_id""",
            (outbox_id,),
        )
        row = cur.fetchone()
        c.commit()
        return dict(row) if row else None


def dispatch_one(*, outbox_id: int, client=None, token_env: str = TOKEN_ENV) -> dict:
    """Deliver exactly ONE requested outbox row to its paired destination.

    Resolves target bot (Global vs BYOB) and destination chat_id dynamically.
    """
    state = get_outbox_state(outbox_id)
    if not state.get("ok", True) or "status" not in state:
        return {"ok": False, "error": "no_outbox_row", "outbox_id": outbox_id}
    if state["status"] != "PENDING":
        return {"ok": True, "skipped": True, "reason": f"not_pending:{state['status']}", "outbox_id": outbox_id, "sent": 0}

    claimed = _claim_one(outbox_id)
    if claimed is None:
        return {"ok": True, "skipped": True, "reason": "not_claimable", "outbox_id": outbox_id, "sent": 0}

    # Resolve target chat_id
    target_chat_id = claimed.get("chat_id")
    if not target_chat_id:
        dest = resolve_owner_destination(business_id=claimed["business_id"])
        if not dest.get("ok") or not dest.get("telegram_user_id"):
            _mark_failed(claimed["id"], dest.get("reason", "NO_DESTINATION"))
            return {"ok": True, "skipped": True, "reason": "no_destination", "outbox_id": outbox_id, "sent": 0}
        target_chat_id = dest["telegram_user_id"]

    # Resolve Bot Client (BYOB vs Global)
    created_client = False
    active_client = client
    if active_client is None:
        bot_id = claimed.get("telegram_bot_id")
        if bot_id:
            bot_row = ambil("SELECT * FROM local_business.telegram_bot WHERE id=%s", (bot_id,))
            if bot_row:
                try:
                    active_client = reg.get_bot_client(bot_row)
                    created_client = True
                except Exception as exc:
                    _mark_failed(claimed["id"], f"bot_decrypt_error:{exc}")
                    return {"ok": False, "error": "bot_client_init_failed", "outbox_id": outbox_id, "sent": 0}

        if active_client is None:
            token = os.environ.get(token_env, "").strip()
            if not token:
                _mark_failed(claimed["id"], "NO_GLOBAL_BOT_TOKEN")
                return {"ok": False, "reason": "no_token", "outbox_id": outbox_id, "sent": 0}
            active_client = BotApiClient(token)
            created_client = True

    try:
        payload = claimed.get("payload") or {}
        message = render_outbound_message(claimed.get("notification_type", "DAILY_SUMMARY"), payload)
        try:
            result = active_client.send_message(target_chat_id, message)
            msg_id = result.get("message_id") if isinstance(result, dict) else None
            _mark_sent(claimed["id"], msg_id)
            return {"ok": True, "sent": 1, "outbox_id": outbox_id, "telegram_message_id": msg_id, "skipped": False}
        except TelegramError as e:
            msg = str(e)
            if "network error" in msg or "ReadTimeout" in msg or "non-json" in msg:
                _mark_unknown(claimed["id"], msg)
                return {"ok": True, "sent": 0, "outbox_id": outbox_id, "status": "UNKNOWN", "skipped": False}
            _mark_failed(claimed["id"], msg)
            return {"ok": True, "sent": 0, "outbox_id": outbox_id, "status": "FAILED", "skipped": False}
    finally:
        if created_client and active_client:
            active_client.close()


def run_daily_final(
    *,
    business_id: int,
    tz: str = "Asia/Jakarta",
    now=None,
    client=None,
    token_env: str = TOKEN_ENV,
) -> dict:
    """One final summary for the previous complete local day for a given business."""
    from datetime import date as _d
    from zoneinfo import ZoneInfo

    now = now or datetime.now(timezone.utc)
    local_now = now.astimezone(ZoneInfo(tz))
    summary_date = (local_now - timedelta(days=1)).date()

    from . import reporting as R

    summary = R.daily_summary(business_id=business_id, local_date=summary_date, timezone=tz)
    if not summary.get("ok"):
        return {"ok": False, "reason": "summary_failed", "error": summary.get("error"), "summary_date": str(summary_date)}

    dests = resolve_destinations_for_event(
        business_id=business_id, event_type="DAILY_SUMMARY_FINAL"
    )
    if not dests:
        # Fallback to DAILY_SUMMARY destinations
        dests = resolve_destinations_for_event(
            business_id=business_id, event_type="DAILY_SUMMARY"
        )
    if not dests:
        return {"ok": False, "reason": "NO_DESTINATION", "summary_date": str(summary_date), "sent": 0}

    results = []
    for d in dests:
        dest_suffix = f":dest-{d['destination_id']}" if d.get("destination_id") else ""
        event_key = f"DAILY_SUMMARY_FINAL:{business_id}:{summary_date}:{tz}{dest_suffix}"
        res = _enqueue(
            business_id=business_id,
            owner_id=business_id,
            notification_type="DAILY_SUMMARY_FINAL",
            event_key=event_key,
            local_date=summary_date,
            payload={"summary": summary},
            destination_id=d.get("destination_id"),
            chat_id=d.get("chat_id"),
            telegram_bot_id=d.get("telegram_bot_id"),
        )
        outbox_id = res.get("outbox_id")
        if res.get("deduped") or outbox_id is None:
            results.append({"outbox_id": outbox_id, "deduped": True, "sent": 0})
        else:
            disp = dispatch_one(outbox_id=outbox_id, client=client, token_env=token_env)
            disp["summary_date"] = str(summary_date)
            disp["event_key"] = event_key
            results.append(disp)

    return {"ok": True, "summary_date": str(summary_date), "dispatches": results, "sent": sum(r.get("sent", 0) for r in results)}


def run_daily_final_all(
    *,
    tz: str = "Asia/Jakarta",
    now=None,
    client=None,
    token_env: str = TOKEN_ENV,
) -> dict:
    """Multi-tenant scheduler: Runs daily summary for all active businesses with connected Telegram."""
    businesses = semua("SELECT id, name, timezone FROM local_business.business WHERE status='ACTIVE' ORDER BY id")
    total = len(businesses)
    processed = 0
    total_sent = 0
    biz_results = []

    for b in businesses:
        biz_id = int(b["id"])
        biz_tz = b.get("timezone") or tz
        # Check if business has any destination or paired account
        dests = resolve_destinations_for_event(business_id=biz_id, event_type="DAILY_SUMMARY_FINAL")
        if not dests:
            dests = resolve_destinations_for_event(business_id=biz_id, event_type="DAILY_SUMMARY")
        if not dests:
            continue

        res = run_daily_final(
            business_id=biz_id,
            tz=biz_tz,
            now=now,
            client=client,
            token_env=token_env,
        )
        processed += 1
        total_sent += res.get("sent", 0)
        biz_results.append({"business_id": biz_id, "name": b["name"], "result": res})

    return {
        "ok": True,
        "total_businesses": total,
        "processed_businesses": processed,
        "total_sent": total_sent,
        "details": biz_results,
    }


def dispatch_due(*, client=None, max_rows: int = 5, token_env: str = TOKEN_ENV) -> dict:
    """Deliver due PENDING alerts to paired destinations."""
    claimed = _claim_next(max_rows=max_rows)
    results = {"claimed": len(claimed), "sent": 0, "failed": 0, "unknown": 0, "skipped_no_dest": 0}
    for row in claimed:
        res = dispatch_one(outbox_id=row["id"], client=client, token_env=token_env)
        if res.get("sent"):
            results["sent"] += 1
        elif res.get("status") == "UNKNOWN":
            results["unknown"] += 1
        elif res.get("reason") == "no_destination":
            results["skipped_no_dest"] += 1
        else:
            results["failed"] += 1
    return {"ok": True, **results}


# --------------------------------------------------------------------------- CLI
def _parse_date(s: str) -> _date:
    return _date.fromisoformat(s)


def main(argv=None) -> int:
    import argparse

    parser = argparse.ArgumentParser(prog="telegram_outbound")
    sub = parser.add_subparsers(dest="cmd")

    p_preview = sub.add_parser("preview-daily")
    p_preview.add_argument("--business-id", type=int, required=True)
    p_preview.add_argument("--date", required=True)
    p_preview.add_argument("--timezone", default="UTC")

    p_enq = sub.add_parser("enqueue-daily")
    p_enq.add_argument("--business-id", type=int, required=True)
    p_enq.add_argument("--date", required=True)
    p_enq.add_argument("--timezone", default="UTC")

    p_disp = sub.add_parser("dispatch")
    p_disp.add_argument("--max", type=int, default=5)

    p_disp_id = sub.add_parser("dispatch-id")
    p_disp_id.add_argument("--id", type=int, required=True)

    p_final = sub.add_parser("run-daily-final")
    p_final.add_argument("--business-id", type=int, required=True)
    p_final.add_argument("--timezone", default="Asia/Jakarta")

    p_final_all = sub.add_parser("run-daily-final-all")
    p_final_all.add_argument("--timezone", default="Asia/Jakarta")

    args = parser.parse_args(argv)
    if args.cmd == "preview-daily":
        from . import reporting as R

        d = _parse_date(args.date)
        s = R.daily_summary(business_id=args.business_id, local_date=d, timezone=args.timezone)
        if not s.get("ok"):
            print(json.dumps(s))
            return 1
        print(render_daily_message(s))
        return 0
    if args.cmd == "enqueue-daily":
        d = _parse_date(args.date)
        res = enqueue_daily_summary(business_id=args.business_id, local_date=d, timezone=args.timezone)
        print(json.dumps({k: v for k, v in res.items() if k != "summary"}, default=str))
        return 0 if res.get("ok") else 1
    if args.cmd == "dispatch":
        res = dispatch_due(max_rows=args.max)
        print(json.dumps(res))
        return 0
    if args.cmd == "dispatch-id":
        res = dispatch_one(outbox_id=args.id)
        print(json.dumps({k: v for k, v in res.items() if k not in ("payload",)}, default=str))
        return 0
    if args.cmd == "run-daily-final":
        res = run_daily_final(business_id=args.business_id, tz=args.timezone)
        print(json.dumps({k: v for k, v in res.items() if k not in ("summary", "payload")}, default=str))
        return 0 if res.get("ok") else 1
    if args.cmd == "run-daily-final-all":
        res = run_daily_final_all(tz=args.timezone)
        print(json.dumps(res, default=str))
        return 0 if res.get("ok") else 1

    parser.print_help()
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
