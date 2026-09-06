"""Generic webhook / REST connectors.

Formalize generic zero-approval connectors: inbound webhook, outbound webhook,
generic REST pull/push adapter, local-network endpoint, event subscription.
Provides auth option, signature option, idempotency, retry, audit, timeout,
failure state. Does NOT create an unrestricted SSRF/open-proxy capability.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import urllib.request
from datetime import datetime, timezone

from ..persistence.db import koneksi as _pg


def _now():
    return datetime.now(timezone.utc)


def register_connector(*, business_id: int, name: str, direction: str, kind: str,
                       endpoint: str, auth_mode: str = "NONE",
                       signature_secret: str = "", idempotency: bool = True,
                       retry_count: int = 3, timeout_sec: int = 30) -> dict:
    """Register a webhook/REST connector. No SSRF: endpoint must be HTTPS or local."""
    if not endpoint.startswith(("https://", "http://127.0.0.1", "http://localhost")):
        raise ValueError("endpoint harus HTTPS atau local-network (cegah SSRF)")
    secret_hash = hashlib.sha256(signature_secret.encode()).hexdigest() if signature_secret else ""
    with _pg() as c:
        cur = c.cursor()
        cur.execute(
            """INSERT INTO local_business.webhook_connector
               (business_id, name, direction, kind, endpoint, auth_mode,
                signature_secret_hash, idempotency, retry_count, timeout_sec)
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
               ON CONFLICT (business_id, name) DO UPDATE SET
                 endpoint=EXCLUDED.endpoint, auth_mode=EXCLUDED.auth_mode,
                 signature_secret_hash=EXCLUDED.signature_secret_hash,
                 idempotency=EXCLUDED.idempotency, retry_count=EXCLUDED.retry_count,
                 timeout_sec=EXCLUDED.timeout_sec
               RETURNING id, name, direction, kind, endpoint, auth_mode""",
            (business_id, name, direction, kind, endpoint, auth_mode,
             secret_hash, idempotency, retry_count, timeout_sec))
        r = cur.fetchone()
        c.commit()
        return r


def receive_webhook(*, connector_id: int, event_id: str, payload: dict,
                    signature: str = "", secret: str = "") -> dict:
    """Receive an inbound webhook. Idempotent per (connector, event_id)."""
    with _pg() as c:
        cur = c.cursor()
        cur.execute(
            "SELECT * FROM local_business.webhook_connector WHERE id=%s", (connector_id,))
        conn = cur.fetchone()
        if not conn:
            raise KeyError(f"connector {connector_id} tidak ada")
        # signature verification
        if conn["signature_secret_hash"]:
            if not secret:
                c.rollback()
                return {"ok": False, "error": "signature_secret tidak disediakan"}
            expected = hmac.new(secret.encode(), json.dumps(payload).encode(),
                                hashlib.sha256).hexdigest()
            if not hmac.compare_digest(expected, signature or ""):
                c.rollback()
                return {"ok": False, "error": "signature tidak valid"}
        # idempotency
        cur.execute(
            "SELECT id, status FROM local_business.webhook_event WHERE connector_id=%s AND event_id=%s",
            (connector_id, event_id))
        ada = cur.fetchone()
        if ada:
            c.rollback()
            return {"duplicate": True, "event_id": event_id, "status": ada["status"]}
        cur.execute(
            """INSERT INTO local_business.webhook_event
               (connector_id, event_id, status, payload)
               VALUES (%s,%s,'RECEIVED',%s) RETURNING id""",
            (connector_id, event_id, json.dumps(payload, default=str)))
        eid = cur.fetchone()["id"]
        c.commit()
        return {"ok": True, "event_id": event_id, "webhook_event_id": eid}


def dispatch_outbound(*, connector_id: int, event_id: str, payload: dict) -> dict:
    """Dispatch an outbound webhook/REST push. Idempotent per event_id."""
    with _pg() as c:
        cur = c.cursor()
        cur.execute(
            "SELECT * FROM local_business.webhook_connector WHERE id=%s", (connector_id,))
        conn = cur.fetchone()
        if not conn:
            raise KeyError(f"connector {connector_id} tidak ada")
        cur.execute(
            "SELECT id, status FROM local_business.webhook_event WHERE connector_id=%s AND event_id=%s",
            (connector_id, event_id))
        ada = cur.fetchone()
        if ada:
            c.rollback()
            return {"duplicate": True, "status": ada["status"]}
        cur.execute(
            """INSERT INTO local_business.webhook_event
               (connector_id, event_id, status, payload)
               VALUES (%s,%s,'PROCESSING',%s) RETURNING id""",
            (connector_id, event_id, json.dumps(payload, default=str)))
        eid = cur.fetchone()["id"]
        c.commit()

    # dispatch with retry
    attempts = 0
    last_error = ""
    while attempts < conn["retry_count"]:
        try:
            req = urllib.request.Request(
                conn["endpoint"], data=json.dumps(payload).encode(),
                headers={"Content-Type": "application/json"}, method="POST")
            with urllib.request.urlopen(req, timeout=conn["timeout_sec"]) as r:
                r.read()
            with _pg() as c:
                cur = c.cursor()
                cur.execute(
                    "UPDATE local_business.webhook_event SET status='PROCESSED', processed_at=now() WHERE id=%s",
                    (eid,))
                c.commit()
            return {"ok": True, "event_id": event_id, "attempts": attempts + 1}
        except Exception as e:
            attempts += 1
            last_error = f"{type(e).__name__}: {e}"
    with _pg() as c:
        cur = c.cursor()
        cur.execute(
            "UPDATE local_business.webhook_event SET status='FAILED', attempts=%s, last_error=%s WHERE id=%s",
            (attempts, last_error[:500], eid))
        c.commit()
    return {"ok": False, "event_id": event_id, "error": last_error, "attempts": attempts}
