"""M9: Edge Runtime — offline entry/exit, durable queue, sync, reconciliation.

The Edge is a separate site-local runtime. It persists events BEFORE accepting
an operation, syncs with at-least-once delivery, and relies on application-level
idempotency (stable event_id) for dedup. It never fabricates PAID status.
"""

from __future__ import annotations

import secrets
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from parking.domain.enums import (
    BarrierAction,
    ConflictClass,
    EdgeSyncState,
    FailPolicy,
    PaymentState,
    SessionState,
)
from parking.domain.errors import ErrorCode, ParkingError
from parking.domain.plate import normalize_plate
from parking.edge.store import EdgeStore

CLOCK_SKEW_THRESHOLD_SECONDS = 300  # 5 minutes


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _edge_event_id() -> str:
    return f"EDGE-{secrets.token_hex(6).upper()}"


@dataclass(frozen=True)
class EdgeResult:
    accepted: bool
    reason: str
    event_id: str | None = None
    sequence_number: int | None = None
    barrier_action: str | None = None
    details: dict = field(default_factory=dict)


@dataclass(frozen=True)
class SyncResult:
    acknowledged: list[str]
    conflicts: list[dict]
    sequence_gap: bool = False


class EdgeRuntime:
    """Deterministic Edge runtime over a durable EdgeStore."""

    def __init__(self, store: EdgeStore, *, fail_policy: str = FailPolicy.FAIL_CLOSED.value,
                 clock_skew_threshold: int = CLOCK_SKEW_THRESHOLD_SECONDS):
        self.store = store
        self.fail_policy = fail_policy
        self.clock_skew_threshold = clock_skew_threshold
        self._central_online = True

    # ---- connectivity ------------------------------------------------------
    def set_central_online(self, online: bool) -> None:
        self._central_online = online

    @property
    def central_online(self) -> bool:
        return self._central_online

    # ---- offline entry -----------------------------------------------------
    def offline_entry(self, *, plate: str, vehicle_type: str, site_id: int, gate_id: int,
                      lane_id: int, occurred_at: datetime | None = None) -> EdgeResult:
        """Process an entry while Central is unreachable, using local config and
        local duplicate guard. Persists the event before accepting."""
        config = self.store.current_config()
        if config is None:
            return EdgeResult(accepted=False, reason="NO_LOCAL_CONFIG")
        if config["site_id"] != site_id:
            return EdgeResult(accepted=False, reason="SITE_MISMATCH")

        norm = normalize_plate(plate)
        if not norm:
            return EdgeResult(accepted=False, reason="INVALID_PLATE")

        # Local duplicate guard: same plate already active locally.
        existing = self.store.find_session_by_plate(norm)
        if existing is not None:
            return EdgeResult(accepted=False, reason="DUPLICATE_ACTIVE_SESSION")

        at = occurred_at or _now()
        event_id = _edge_event_id()
        public_reference = f"PK-{site_id}-{secrets.token_hex(5).upper()}"
        payload = {
            "event_type": "ENTRY",
            "public_reference": public_reference,
            "site_id": site_id, "gate_id": gate_id, "lane_id": lane_id,
            "plate_normalized": norm, "vehicle_type": vehicle_type,
            "occurred_at": at.isoformat(),
        }
        # Persist BEFORE accepting (durable queue).
        seq = self.store.enqueue_event(event_id=event_id, event_type="ENTRY",
                                       occurred_at=at.isoformat(), payload=payload)
        self.store.cache_session(public_reference=public_reference, site_id=site_id,
                                 plate_normalized=norm, entry_at=at.isoformat(), state="PARKED")
        self.store.mark_processed(event_id)
        return EdgeResult(accepted=True, reason="OFFLINE_ENTRY_ACCEPTED", event_id=event_id,
                          sequence_number=seq, barrier_action=BarrierAction.OPEN_BARRIER.value,
                          details={"public_reference": public_reference})

    # ---- offline exit ------------------------------------------------------
    def offline_exit(self, *, public_reference: str, method: str, amount: int | None = None,
                     occurred_at: datetime | None = None) -> EdgeResult:
        """Conservative offline exit. Only CASH / COMPLIMENTARY / already-settled
        sessions may be settled locally. Unverified QRIS is never marked PAID."""
        session = self.store.get_session(public_reference)
        if session is None:
            return EdgeResult(accepted=False, reason="UNKNOWN_SESSION")

        at = occurred_at or _now()
        event_id = _edge_event_id()

        if method == "CASH":
            if amount is None:
                return EdgeResult(accepted=False, reason="AMOUNT_REQUIRED")
            payload = {
                "event_type": "EXIT", "public_reference": public_reference,
                "method": "CASH", "amount": amount, "occurred_at": at.isoformat(),
            }
            seq = self.store.enqueue_event(event_id=event_id, event_type="EXIT",
                                           occurred_at=at.isoformat(), payload=payload)
            self.store.close_session(public_reference)
            self.store.mark_processed(event_id)
            return EdgeResult(accepted=True, reason="OFFLINE_CASH_EXIT_ACCEPTED", event_id=event_id,
                              sequence_number=seq, barrier_action=BarrierAction.OPEN_BARRIER.value,
                              details={"public_reference": public_reference})
        if method == "COMPLIMENTARY":
            payload = {
                "event_type": "EXIT", "public_reference": public_reference,
                "method": "COMPLIMENTARY", "amount": 0, "occurred_at": at.isoformat(),
            }
            seq = self.store.enqueue_event(event_id=event_id, event_type="EXIT",
                                           occurred_at=at.isoformat(), payload=payload)
            self.store.close_session(public_reference)
            self.store.mark_processed(event_id)
            return EdgeResult(accepted=True, reason="OFFLINE_COMPLIMENTARY_EXIT_ACCEPTED", event_id=event_id,
                              sequence_number=seq, barrier_action=BarrierAction.OPEN_BARRIER.value,
                              details={"public_reference": public_reference})
        if method in ("QRIS_MPM_DYNAMIC", "QRIS_CPM"):
            # QRIS requires provider connectivity; cannot verify offline.
            return EdgeResult(accepted=False, reason="PAYMENT_CONNECTIVITY_REQUIRED",
                              details={"public_reference": public_reference})
        return EdgeResult(accepted=False, reason="UNSUPPORTED_METHOD")

    # ---- sync --------------------------------------------------------------
    def sync_batch(self, *, max_events: int = 100, max_bytes: int = 1_000_000) -> list[dict]:
        """Return a bounded batch of pending events for upload."""
        events = self.store.pending_events(limit=max_events)
        batch: list[dict] = []
        total = 0
        for ev in events:
            size = len(ev["payload"])
            if total + size > max_bytes:
                break
            batch.append(ev)
            total += size
        return batch

    def process_ack(self, ack: dict) -> SyncResult:
        """Process a central acknowledgement set. Only acknowledged events are
        marked synced; unacknowledged remain pending."""
        acknowledged = ack.get("acknowledged", [])
        conflicts = ack.get("conflicts", [])
        self.store.mark_synced(acknowledged)
        return SyncResult(acknowledged=acknowledged, conflicts=conflicts)

    def detect_clock_skew(self, server_time: datetime) -> bool:
        """Detect excessive clock skew between edge and central."""
        local = _now()
        return abs((server_time - local).total_seconds()) > self.clock_skew_threshold

    def health(self) -> dict:
        return {
            **self.store.health(),
            "central_online": self._central_online,
            "fail_policy": self.fail_policy,
        }
