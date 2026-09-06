"""Outbox worker + sinkronisasi + drift detection.

Worker membaca antrean inventory_sync_outbox dan memanggil adapter provider.

Alur (bounded backoff, dedup, LATEST quantity convergence):
  1. Ambil baris outbox PENDING/FAILED (attempts < max) FOR UPDATE SKIP LOCKED.
  2. Ambil desired_qty TERBARU dari sync_state (bukan nilai lama outbox), sehingga
     provider yang sempat tidak tersedia tetap konvergen ke nilai terkini.
  3. Kalau GLOBAL_MULTICHANNEL_STOCK_WRITE=OFF -> drop, tidak menulis (loop protection).
  4. Panggil adapter provider.write_stock(...). Setelah tulis, read-after-write.
  5. Perbarui sync_state + outbox (SENT/FAILED) + tulis attempt audit.

LOOP PROTECTION:
  - write_origin='system' dicatat saat kita menulis ke provider.
  - Saat event provider masuk dan remote==desired dengan origin system, tidak
    ditulis outbox baru (tidak loop).

DRIFT:
  - reconcile() membaca remote lalu menulis inventory_drift (read-only,
    tidak menimpa; AUTO_STOCK_DRIFT_REPAIR default OFF).
"""

from __future__ import annotations

from ..persistence.db import koneksi as _pg_koneksi


class ProviderSyncError(RuntimeError):
    pass


class ZoomNowError(RuntimeError):
    pass


# ============================================================ config flags
def config_get(key: str, default: str = "OFF") -> str:
    with _pg_koneksi() as c:
        cur = c.cursor()
        cur.execute("SELECT value FROM multichannel.inventory_config WHERE key=%s", (key,))
        r = cur.fetchone()
    return r["value"] if r else default


def config_set(key: str, value: str) -> None:
    with _pg_koneksi() as c:
        cur = c.cursor()
        cur.execute(
            "INSERT INTO multichannel.inventory_config (key,value) VALUES (%s,%s) "
            "ON CONFLICT (key) DO UPDATE SET value=EXCLUDED.value, updated_at=now()",
            (key, value))
        c.commit()


def global_write_enabled() -> bool:
    return config_get("GLOBAL_MULTICHANNEL_STOCK_WRITE") == "ON"


def set_global_write(value: str) -> None:
    if value not in ("ON", "OFF"):
        raise ValueError("nilai harus ON/OFF")
    config_set("GLOBAL_MULTICHANNEL_STOCK_WRITE", value)


# ============================================================ worker
def process_outbox(
    adapter_map: dict[str, object],
    limit: int = 50,
    max_attempts: int = 5,
) -> dict:
    """Proses satu batch outbox. adapter_map: provider -> adapter (dengan .write_stock)."""
    if not global_write_enabled():
        n = drop_pending()
        return {"status": "global_off", "dropped": n, "sent": 0, "failed": 0}

    processed = sent = failed = 0
    with _pg_koneksi() as c:
        cur = c.cursor()
        cur.execute(
            """SELECT o.id, o.provider, o.shop_id, o.channel_sku, o.master_sku_id,
                      ss.desired_qty AS desired, o.attempts, ss.last_written_qty,
                      ss.id AS sync_state_id
               FROM multichannel.inventory_sync_outbox o
               JOIN multichannel.inventory_sync_state ss ON ss.id=o.sync_state_id
               WHERE o.status IN ('PENDING','FAILED') AND o.attempts < %s
               ORDER BY o.id LIMIT %s FOR UPDATE SKIP LOCKED""",
            (max_attempts, limit),
        )
        rows = cur.fetchall()
        for o in rows:
            adapter = adapter_map.get(o["provider"])
            attempts = o["attempts"] + 1
            ok, remote, err = _dispatch(adapter, o)
            if ok:
                cur.execute(
                    """UPDATE multichannel.inventory_sync_state
                       SET desired_qty=%s, last_written_qty=%s, remote_qty=%s,
                           last_write_at=now(), last_read_at=now(), status='MATCHED',
                           last_error='', write_origin='system', updated_at=now()
                       WHERE id=%s""",
                    (o["desired"], o["desired"], remote_qty(o, remote), o["sync_state_id"]))
                cur.execute(
                    "UPDATE multichannel.inventory_sync_outbox SET status='SENT', attempts=%s, sent_at=now() WHERE id=%s",
                    (attempts, o["id"]))
                _insert_attempt(cur, o["id"], o["provider"], "SENT", remote_qty(o, remote))
                sent += 1
            else:
                cur.execute(
                    "UPDATE multichannel.inventory_sync_state SET status='FAILED', last_error=%s, updated_at=now() WHERE id=%s",
                    (err, o["sync_state_id"]))
                if attempts >= max_attempts:
                    cur.execute("UPDATE multichannel.inventory_sync_outbox SET status='FAILED', attempts=%s, last_error=%s WHERE id=%s",
                                (attempts, err[:300], o["id"]))
                else:
                    cur.execute("UPDATE multichannel.inventory_sync_outbox SET attempts=%s, last_error=%s WHERE id=%s",
                                (attempts, err[:300], o["id"]))
                _insert_attempt(cur, o["id"], o["provider"], "FAILED", -1, err)
                failed += 1
            processed += 1
        c.commit()
    return {"status": "done", "processed": processed, "sent": sent, "failed": failed}


def remote_qty(o, remote):
    return remote if remote is not None else o["desired"]


def _dispatch(adapter, o):
    """Panggil adapter.write_stock; kembalikan (ok, remote, err)."""
    if adapter is None or not hasattr(adapter, "write_stock"):
        return False, None, "adapter tidak menyediakan write_stock"
    try:
        adapter.write_stock(
            provider=o["provider"], shop_id=o["shop_id"], channel_sku=o["channel_sku"],
            desired_qty=o["desired"], last_written_qty=o["last_written_qty"],
        )
        return True, o["desired"], ""
    except ZoomNowError as e:
        return False, None, str(e)
    except Exception as e:
        return False, None, f"{type(e).__name__}: {e}"


def _insert_attempt(cur, outbox_id, provider, status, remote_qty, error=""):
    cur.execute(
        """INSERT INTO multichannel.inventory_sync_attempt
           (outbox_id, provider, status, remote_qty_after, error)
           VALUES (%s,%s,%s,%s,%s)""",
        (outbox_id, provider, status, remote_qty, error))


def drop_pending() -> int:
    with _pg_koneksi() as c:
        cur = c.cursor()
        cur.execute("UPDATE multichannel.inventory_sync_outbox SET status='DROPPED' WHERE status='PENDING'")
        c.commit()
        return cur.rowcount


# ============================================================ sync helpers
def sync_state_snapshot(*, provider: str, shop_id: str, channel_sku: str) -> dict | None:
    with _pg_koneksi() as c:
        cur = c.cursor()
        cur.execute(
            """SELECT * FROM multichannel.inventory_sync_state
               WHERE provider=%s AND shop_id=%s AND channel_sku=%s""",
            (provider, shop_id, channel_sku))
        return cur.fetchone()


def update_sync_from_event(
    *, provider: str, shop_id: str, channel_sku: str,
    desired_qty: int, remote_qty: int, write_origin: str, status: str = "MATCHED",
    event_seq: str = "",
) -> dict:
    """Dipanggil saat menerima webhook/event provider stok.

    Loop protection: kalau event itu hasil tulisan kita sendiri
    (write_origin='system' dan remote==desired) jangan tambah outbox.
    """
    with _pg_koneksi() as c:
        cur = c.cursor()
        cur.execute(
            """UPDATE multichannel.inventory_sync_state
               SET desired_qty=%s, remote_qty=%s, write_origin=%s, status=%s,
                   provider_event_seq=%s, last_read_at=now(), updated_at=now()
               WHERE provider=%s AND shop_id=%s AND channel_sku=%s
               RETURNING id, status, desired_qty, remote_qty, write_origin""",
            (desired_qty, remote_qty, write_origin, status, event_seq,
             provider, shop_id, channel_sku))
        r = cur.fetchone()
        if not r:
            c.rollback()
            return {"found": False}
        # loop protection: kalau kita yang menulis & remote sudah sesuai desired, no-op
        if write_origin == "system" and remote_qty == desired_qty:
            c.commit()
            return {"found": True, "loop_suppressed": True}
        c.commit()
        return {"found": True, "loop_suppressed": False}


def write_drift(provider, shop_id, channel_sku_map_id, master_sku_id,
                desired, remote, state, delta) -> None:
    with _pg_koneksi() as c:
        cur = c.cursor()
        cur.execute(
            """INSERT INTO multichannel.inventory_drift
               (channel_sku_map_id, master_sku_id, provider, shop_id,
                desired_qty, remote_qty, state, delta)
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s)""",
            (channel_sku_map_id, master_sku_id, provider, shop_id,
             desired, remote, state, delta))
        c.commit()


def reconcile(adapter_map: dict[str, object]) -> list[dict]:
    """Read-only drift detection: bandingkan desired vs remote; TIDAK menimpa."""
    results = []
    with _pg_koneksi() as c:
        cur = c.cursor()
        cur.execute(
            """SELECT ss.id AS sync_state_id, ss.provider, ss.shop_id, ss.channel_sku,
                      ss.desired_qty, ss.channel_sku_map_id, ss.master_sku_id
               FROM multichannel.inventory_sync_state ss
               WHERE ss.provider = ANY(%s)""",
            (list(adapter_map.keys()),))
        rows = cur.fetchall()
    for ss in rows:
        adapter = adapter_map.get(ss["provider"])
        remote = None
        err = ""
        try:
            remote = adapter.read_stock(provider=ss["provider"], shop_id=ss["shop_id"],
                                        channel_sku=ss["channel_sku"])
        except Exception as e:
            err = f"{type(e).__name__}: {e}"
        if remote is None:
            state, delta = "UNKNOWN", None
        elif remote == ss["desired_qty"]:
            state, delta = "MATCHED", 0
        else:
            state, delta = "DRIFTED", remote - ss["desired_qty"]
        write_drift(ss["provider"], ss["shop_id"], ss["channel_sku_map_id"],
                    ss["master_sku_id"], ss["desired_qty"],
                    remote if remote is not None else -1, state,
                    delta if delta is not None else 0)
        results.append({"provider": ss["provider"], "channel_sku": ss["channel_sku"],
                        "desired": ss["desired_qty"], "remote": remote,
                        "state": state, "delta": delta})
    return results
