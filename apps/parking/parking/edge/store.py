"""M9: Edge local durable SQLite store.

Stores ONLY what offline operation requires: edge/site identity, config snapshot,
outbound event queue, processed-event IDs, sync cursors, active session cache,
pending barrier commands. Uses WAL mode for durability + concurrency.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path

_SCHEMA = """
CREATE TABLE IF NOT EXISTS edge_meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS config_snapshot (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    config_version INTEGER NOT NULL,
    site_id INTEGER NOT NULL,
    generated_at TEXT NOT NULL,
    content_hash TEXT NOT NULL,
    payload TEXT NOT NULL,
    accepted_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS outbound_event (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    event_id TEXT NOT NULL UNIQUE,
    edge_id TEXT NOT NULL,
    tenant_id INTEGER NOT NULL,
    site_id INTEGER NOT NULL,
    event_type TEXT NOT NULL,
    occurred_at TEXT NOT NULL,
    recorded_at TEXT NOT NULL,
    sequence_number INTEGER NOT NULL,
    payload TEXT NOT NULL,
    sync_state TEXT NOT NULL DEFAULT 'PENDING',
    UNIQUE(edge_id, sequence_number)
);
CREATE TABLE IF NOT EXISTS processed_event (
    event_id TEXT PRIMARY KEY,
    processed_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS active_session (
    public_reference TEXT PRIMARY KEY,
    site_id INTEGER NOT NULL,
    plate_normalized TEXT NOT NULL,
    entry_at TEXT NOT NULL,
    state TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS pending_barrier_command (
    command_id TEXT PRIMARY KEY,
    site_id INTEGER NOT NULL,
    device_id TEXT NOT NULL,
    command_type TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_outbound_pending ON outbound_event(sync_state, sequence_number);
"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class EdgeStore:
    """Durable SQLite-backed store for a single Edge site."""

    def __init__(self, path: str | Path):
        self.path = str(path)
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(self.path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA foreign_keys=ON")
        with self._conn:
            self._conn.executescript(_SCHEMA)

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    def _meta(self, key: str) -> str | None:
        row = self._conn.execute("SELECT value FROM edge_meta WHERE key=?", (key,)).fetchone()
        return row["value"] if row else None

    def _set_meta(self, key: str, value: str) -> None:
        with self._lock:
            with self._conn:
                self._conn.execute(
                    "INSERT INTO edge_meta(key,value) VALUES(?,?) "
                    "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                    (key, value),
                )

    # ---- identity ----------------------------------------------------------
    def set_identity(self, *, edge_id: str, tenant_id: int, site_id: int) -> None:
        self._set_meta("edge_id", edge_id)
        self._set_meta("tenant_id", str(tenant_id))
        self._set_meta("site_id", str(site_id))

    @property
    def edge_id(self) -> str | None:
        return self._meta("edge_id")

    @property
    def tenant_id(self) -> int | None:
        v = self._meta("tenant_id")
        return int(v) if v else None

    @property
    def site_id(self) -> int | None:
        v = self._meta("site_id")
        return int(v) if v else None

    # ---- config snapshot ---------------------------------------------------
    def accept_config(self, *, config_version: int, site_id: int, generated_at: str, payload: dict) -> bool:
        """Accept a config snapshot only if it is newer than the current one.
        Returns True if accepted, False if stale."""
        content_hash = hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()
        current = self.current_config()
        if current is not None and current["config_version"] >= config_version:
            return False
        with self._lock:
            with self._conn:
                self._conn.execute(
                    "INSERT INTO config_snapshot(config_version,site_id,generated_at,content_hash,payload,accepted_at) "
                    "VALUES(?,?,?,?,?,?)",
                    (config_version, site_id, generated_at, content_hash, json.dumps(payload), _now()),
                )
        return True

    def current_config(self) -> dict | None:
        row = self._conn.execute(
            "SELECT * FROM config_snapshot ORDER BY config_version DESC LIMIT 1"
        ).fetchone()
        if row is None:
            return None
        return {
            "config_version": row["config_version"],
            "site_id": row["site_id"],
            "generated_at": row["generated_at"],
            "content_hash": row["content_hash"],
            "payload": json.loads(row["payload"]),
        }

    # ---- outbound event queue ----------------------------------------------
    def enqueue_event(self, *, event_id: str, event_type: str, occurred_at: str, payload: dict) -> int:
        """Persist an outbound event BEFORE the operation is considered accepted.
        Returns the sequence number."""
        edge_id = self.edge_id
        tenant_id = self.tenant_id
        site_id = self.site_id
        assert edge_id and tenant_id is not None and site_id is not None
        with self._lock:
            with self._conn:
                seq = self._next_sequence(edge_id)
                self._conn.execute(
                    "INSERT INTO outbound_event(event_id,edge_id,tenant_id,site_id,event_type,occurred_at,"
                    "recorded_at,sequence_number,payload,sync_state) VALUES(?,?,?,?,?,?,?,?,?,?)",
                    (event_id, edge_id, tenant_id, site_id, event_type, occurred_at, _now(), seq,
                     json.dumps(payload), "PENDING"),
                )
        return seq

    def _next_sequence(self, edge_id: str) -> int:
        row = self._conn.execute(
            "SELECT COALESCE(MAX(sequence_number),0)+1 AS n FROM outbound_event WHERE edge_id=?", (edge_id,)
        ).fetchone()
        return int(row["n"])

    def pending_events(self, limit: int = 100) -> list[dict]:
        rows = self._conn.execute(
            "SELECT * FROM outbound_event WHERE sync_state='PENDING' ORDER BY sequence_number LIMIT ?",
            (limit,),
        ).fetchall()
        return [dict(r) for r in rows]

    def mark_synced(self, event_ids: list[str]) -> None:
        if not event_ids:
            return
        with self._lock:
            with self._conn:
                for eid in event_ids:
                    self._conn.execute(
                        "UPDATE outbound_event SET sync_state='SYNCED' WHERE event_id=?", (eid,)
                    )

    def queue_depth(self) -> int:
        row = self._conn.execute(
            "SELECT COUNT(*) AS n FROM outbound_event WHERE sync_state='PENDING'"
        ).fetchone()
        return int(row["n"])

    def oldest_pending_at(self) -> str | None:
        row = self._conn.execute(
            "SELECT recorded_at FROM outbound_event WHERE sync_state='PENDING' ORDER BY sequence_number LIMIT 1"
        ).fetchone()
        return row["recorded_at"] if row else None

    # ---- processed-event IDs (dedup) ---------------------------------------
    def mark_processed(self, event_id: str) -> None:
        with self._lock:
            with self._conn:
                self._conn.execute(
                    "INSERT OR IGNORE INTO processed_event(event_id,processed_at) VALUES(?,?)",
                    (event_id, _now()),
                )

    def is_processed(self, event_id: str) -> bool:
        row = self._conn.execute("SELECT 1 FROM processed_event WHERE event_id=?", (event_id,)).fetchone()
        return row is not None

    # ---- active session cache ----------------------------------------------
    def cache_session(self, *, public_reference: str, site_id: int, plate_normalized: str,
                      entry_at: str, state: str) -> None:
        with self._lock:
            with self._conn:
                self._conn.execute(
                    "INSERT OR REPLACE INTO active_session(public_reference,site_id,plate_normalized,entry_at,state) "
                    "VALUES(?,?,?,?,?)",
                    (public_reference, site_id, plate_normalized, entry_at, state),
                )

    def get_session(self, public_reference: str) -> dict | None:
        row = self._conn.execute(
            "SELECT * FROM active_session WHERE public_reference=?", (public_reference,)
        ).fetchone()
        return dict(row) if row else None

    def find_session_by_plate(self, plate_normalized: str) -> dict | None:
        row = self._conn.execute(
            "SELECT * FROM active_session WHERE plate_normalized=? ORDER BY entry_at DESC LIMIT 1",
            (plate_normalized,),
        ).fetchone()
        return dict(row) if row else None

    def close_session(self, public_reference: str) -> None:
        with self._lock:
            with self._conn:
                self._conn.execute("DELETE FROM active_session WHERE public_reference=?", (public_reference,))

    # ---- pending barrier commands ------------------------------------------
    def add_pending_command(self, *, command_id: str, site_id: int, device_id: str, command_type: str) -> None:
        with self._lock:
            with self._conn:
                self._conn.execute(
                    "INSERT OR IGNORE INTO pending_barrier_command(command_id,site_id,device_id,command_type,created_at) "
                    "VALUES(?,?,?,?,?)",
                    (command_id, site_id, device_id, command_type, _now()),
                )

    def pending_commands(self) -> list[dict]:
        rows = self._conn.execute("SELECT * FROM pending_barrier_command ORDER BY created_at").fetchall()
        return [dict(r) for r in rows]

    def remove_pending_command(self, command_id: str) -> None:
        with self._lock:
            with self._conn:
                self._conn.execute("DELETE FROM pending_barrier_command WHERE command_id=?", (command_id,))

    # ---- cleanup / retention ----------------------------------------------
    def compact_synced(self, keep: int = 1000) -> int:
        """Remove successfully-synced historical events beyond a retention bound.
        NEVER removes unsynced events."""
        with self._lock:
            with self._conn:
                cur = self._conn.execute(
                    "DELETE FROM outbound_event WHERE sync_state='SYNCED' AND id NOT IN "
                    "(SELECT id FROM outbound_event WHERE sync_state='SYNCED' ORDER BY id DESC LIMIT ?)",
                    (keep,),
                )
        return cur.rowcount

    def health(self) -> dict:
        return {
            "edge_id": self.edge_id,
            "site_id": self.site_id,
            "config_version": self.current_config()["config_version"] if self.current_config() else None,
            "queue_depth": self.queue_depth(),
            "oldest_pending_at": self.oldest_pending_at(),
        }
