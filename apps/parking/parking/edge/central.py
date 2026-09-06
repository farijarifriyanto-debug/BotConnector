"""M9: Central-side sync receiver.

Applies edge events idempotently using stable event_id, produces machine-readable
reconciliation results, and returns an acknowledgement set. Never silently
overwrites central truth.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone

from sqlalchemy import select

from parking.domain.enums import ConflictClass, EdgeSyncState
from parking.domain.errors import ErrorCode, ParkingError
from parking.models import ParkingEdge, ParkingEdgeSyncEvent
from parking.repositories.base import ScopedRepository


class EdgeRepository(ScopedRepository):
    def get_by_edge_id(self, edge_id: str) -> ParkingEdge:
        edge = self.session.scalar(
            select(ParkingEdge).where(ParkingEdge.tenant_id == self.tenant_id, ParkingEdge.edge_id == edge_id)
        )
        if edge is None:
            raise ParkingError(ErrorCode.EDGE_NOT_AUTHORIZED, "edge not authorized", status=403)
        return edge


class EdgeSyncRepository(ScopedRepository):
    def get_by_event_id(self, event_id: str) -> ParkingEdgeSyncEvent | None:
        return self.session.scalar(
            select(ParkingEdgeSyncEvent).where(
                ParkingEdgeSyncEvent.tenant_id == self.tenant_id,
                ParkingEdgeSyncEvent.event_id == event_id,
            )
        )

    def record(self, *, event_id: str, edge_id: str, site_id: int, event_type: str,
               sequence_number: int, occurred_at: datetime, payload: dict) -> ParkingEdgeSyncEvent:
        rec = ParkingEdgeSyncEvent(
            event_id=event_id, edge_id=edge_id, tenant_id=self.tenant_id, site_id=site_id,
            event_type=event_type, sequence_number=sequence_number, occurred_at=occurred_at,
            payload=payload, sync_state=EdgeSyncState.SYNCED.value,
        )
        self.session.add(rec)
        self.session.flush()
        return rec


@dataclass(frozen=True)
class Reconciliation:
    acknowledged: list[str]
    conflicts: list[dict]
    sequence_gap: bool = False


class CentralSyncService:
    """Applies edge event batches idempotently."""

    def __init__(self, session, scope):
        self.session = session
        self.scope = scope
        self.tenant_id = scope.tenant_id
        self.edges = EdgeRepository(session, scope.tenant_id)
        self.sync = EdgeSyncRepository(session, scope.tenant_id)

    def _authorize_edge(self, edge_id: str, site_id: int) -> ParkingEdge:
        edge = self.edges.get_by_edge_id(edge_id)
        if edge.site_id != site_id:
            raise ParkingError(ErrorCode.EDGE_NOT_AUTHORIZED, "edge not assigned to this site", status=403)
        return edge

    def receive_batch(self, *, edge_id: str, site_id: int, events: list[dict]) -> Reconciliation:
        """Apply a batch of edge events. Duplicates are acknowledged (idempotent);
        conflicts produce machine-readable results."""
        self._authorize_edge(edge_id, site_id)
        acknowledged: list[str] = []
        conflicts: list[dict] = []
        sequence_gap = False
        last_seq = 0

        for ev in events:
            event_id = ev["event_id"]
            seq = int(ev["sequence_number"])
            event_type = ev["event_type"]
            occurred_at = datetime.fromisoformat(ev["occurred_at"])
            payload = ev.get("payload", {})
            if isinstance(payload, str):
                import json
                payload = json.loads(payload)

            # Duplicate event -> acknowledge (idempotent).
            existing = self.sync.get_by_event_id(event_id)
            if existing is not None:
                acknowledged.append(event_id)
                continue

            # Sequence gap detection (per edge).
            if seq != last_seq + 1:
                sequence_gap = True
                conflicts.append({
                    "event_id": event_id, "class": ConflictClass.SEQUENCE_GAP.value,
                    "expected": last_seq + 1, "got": seq,
                })
                last_seq = seq
                continue

            # Apply the event (idempotently).
            conflict = self._apply_event(event_id, edge_id, site_id, event_type, occurred_at, payload)
            if conflict is not None:
                conflicts.append(conflict)
                continue

            self.sync.record(event_id=event_id, edge_id=edge_id, site_id=site_id, event_type=event_type,
                             sequence_number=seq, occurred_at=occurred_at, payload=payload)
            acknowledged.append(event_id)
            last_seq = seq

        self.session.commit()
        return Reconciliation(acknowledged=acknowledged, conflicts=conflicts, sequence_gap=sequence_gap)

    def _apply_event(self, event_id, edge_id, site_id, event_type, occurred_at, payload) -> dict | None:
        """Apply a single edge event. Returns a conflict dict or None on success."""
        if event_type == "ENTRY":
            # Idempotent by public_reference.
            from parking.models import ParkingSession
            ref = payload.get("public_reference")
            existing = self.session.scalar(
                select(ParkingSession).where(
                    ParkingSession.tenant_id == self.tenant_id, ParkingSession.public_reference == ref
                )
            )
            if existing is not None:
                return {"event_id": event_id, "class": ConflictClass.DUPLICATE_EVENT.value,
                        "detail": "session already exists"}
            return None
        if event_type == "EXIT":
            from parking.models import ParkingSession
            ref = payload.get("public_reference")
            session = self.session.scalar(
                select(ParkingSession).where(
                    ParkingSession.tenant_id == self.tenant_id, ParkingSession.public_reference == ref
                )
            )
            if session is None:
                return {"event_id": event_id, "class": ConflictClass.UNKNOWN_SESSION.value,
                        "detail": "session not found"}
            if session.state == SessionState.CLOSED.value:
                return {"event_id": event_id, "class": ConflictClass.SESSION_ALREADY_CLOSED.value,
                        "detail": "session already closed"}
            return None
        return {"event_id": event_id, "class": ConflictClass.DUPLICATE_EVENT.value,
                "detail": f"unhandled event type {event_type}"}
