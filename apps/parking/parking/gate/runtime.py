"""M4: Gate Runtime — controlled admission decisions and barrier action intents.

No physical hardware is driven here. The runtime returns a deterministic
admission decision plus a barrier ACTION INTENT that a future BarrierAdapter
(M8) will consume.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone

from parking.domain.enums import (
    AdmissionDecision,
    BarrierAction,
    EventType,
    GateDirection,
    GateStatus,
    LaneDirection,
    LaneStatus,
    SessionState,
    VehicleType,
)
from parking.domain.errors import ErrorCode, ParkingError
from parking.domain.plate import display_plate, normalize_plate
from parking.gate.runtime_repo import (
    GateRuntimeRepository,
    IdempotencyRepository,
    LaneRuntimeRepository,
)
from parking.models import ParkingSession
from parking.repositories.registry import GateRepository, LaneRepository, SiteRepository, VehicleRepository
from parking.repositories.session_repo import SessionRepository
from parking.services.auth import Scope
from parking.services.entry import make_public_reference


@dataclass(frozen=True)
class AdmissionResult:
    decision: str
    reason: str
    barrier_action: str
    session: ParkingSession | None = None
    details: dict = field(default_factory=dict)


def _request_hash(payload: dict) -> str:
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


class GateRuntimeService:
    """Server-side gate runtime. Entry admission is idempotent by request key."""

    def __init__(self, session, scope: Scope):
        self.session = session
        self.scope = scope
        self.tenant_id = scope.tenant_id

    def _deny(self, reason: str, barrier: str = BarrierAction.KEEP_CLOSED.value, details=None) -> AdmissionResult:
        return AdmissionResult(
            decision=AdmissionDecision.DENY.value,
            reason=reason,
            barrier_action=barrier,
            details=details or {},
        )

    def _manual_review(self, reason: str, details=None) -> AdmissionResult:
        return AdmissionResult(
            decision=AdmissionDecision.MANUAL_REVIEW.value,
            reason=reason,
            barrier_action=BarrierAction.MANUAL_REVIEW.value,
            details=details or {},
        )

    def entry_request(
        self,
        *,
        site_id: int,
        gate_id: int,
        lane_id: int,
        plate: str,
        vehicle_type: str,
        idempotency_key: str,
        entry_at: datetime | None = None,
        source: str | None = "SIMULATED_ANPR",
        metadata: dict | None = None,
    ) -> AdmissionResult:
        tenant_id = self.tenant_id
        actor = self.scope.actor
        event_repo = SessionRepository(self.session, tenant_id)

        # Resolve tenant/site/gate/lane (tenant-scoped, 404 semantics).
        site = SiteRepository(self.session, tenant_id).get(site_id)
        gate = GateRepository(self.session, tenant_id).get(site_id, gate_id)
        lane = LaneRepository(self.session, tenant_id).get(site_id, gate_id, lane_id)

        # Record ENTRY_REQUESTED event.
        event_repo.add_event(
            tenant_id, site_id, None, EventType.ENTRY_REQUESTED.value, actor,
            {"gate_id": gate_id, "lane_id": lane_id, "plate": normalize_plate(plate), "idempotency_key": idempotency_key},
        )

        # Idempotency: same key + same request -> return stored result.
        idem = IdempotencyRepository(self.session, tenant_id)
        payload = {
            "site_id": site_id, "gate_id": gate_id, "lane_id": lane_id,
            "plate": plate, "vehicle_type": vehicle_type, "entry_at": entry_at.isoformat() if entry_at else None,
        }
        req_hash = _request_hash(payload)
        existing = idem.get(idempotency_key)
        if existing is not None:
            if existing.request_hash != req_hash:
                raise ParkingError(
                    ErrorCode.IDEMPOTENCY_CONFLICT,
                    "idempotency key reused with a conflicting request",
                    status=409,
                )
            # Replay: return the stored decision without creating a new session.
            return AdmissionResult(
                decision=existing.result["decision"],
                reason=existing.result["reason"],
                barrier_action=existing.result["barrier_action"],
                details=existing.result.get("details", {}),
            )

        # Gate/lane availability checks.
        if gate.status != GateStatus.ACTIVE.value:
            return self._finish_deny(idem, req_hash, idempotency_key, event_repo, tenant_id, site_id,
                                     "GATE_INACTIVE", {"gate_status": gate.status})
        if lane.status != LaneStatus.ACTIVE.value:
            return self._finish_deny(idem, req_hash, idempotency_key, event_repo, tenant_id, site_id,
                                     "LANE_INACTIVE", {"lane_status": lane.status})
        if gate.direction not in (GateDirection.ENTRY.value, GateDirection.BIDIRECTIONAL.value):
            return self._finish_deny(idem, req_hash, idempotency_key, event_repo, tenant_id, site_id,
                                     "INVALID_DIRECTION", {"gate_direction": gate.direction})
        if lane.direction not in (LaneDirection.ENTRY.value, LaneDirection.BIDIRECTIONAL.value):
            return self._finish_deny(idem, req_hash, idempotency_key, event_repo, tenant_id, site_id,
                                     "INVALID_DIRECTION", {"lane_direction": lane.direction})
        if site.status != "ACTIVE":
            return self._finish_deny(idem, req_hash, idempotency_key, event_repo, tenant_id, site_id,
                                     "SITE_CLOSED", {"site_status": site.status})

        # Runtime state.
        gate_rt = GateRuntimeRepository(self.session, tenant_id).get_or_create(site_id=site_id, gate_id=gate_id)
        lane_rt = LaneRuntimeRepository(self.session, tenant_id).get_or_create(site_id=site_id, lane_id=lane_id)
        if gate_rt.state != "ONLINE":
            return self._finish_deny(idem, req_hash, idempotency_key, event_repo, tenant_id, site_id,
                                     "GATE_NOT_AVAILABLE", {"runtime_state": gate_rt.state})
        if lane_rt.state != "ONLINE":
            return self._finish_deny(idem, req_hash, idempotency_key, event_repo, tenant_id, site_id,
                                     "LANE_NOT_AVAILABLE", {"runtime_state": lane_rt.state})

        # Normalize plate / validate vehicle type.
        norm = normalize_plate(plate)
        if not norm:
            return self._finish_deny(idem, req_hash, idempotency_key, event_repo, tenant_id, site_id,
                                     "INVALID_PLATE", {"plate": plate})
        if vehicle_type not in VehicleType.__members__:
            return self._finish_deny(idem, req_hash, idempotency_key, event_repo, tenant_id, site_id,
                                     "INVALID_VEHICLE_TYPE", {"vehicle_type": vehicle_type})
        if lane.vehicle_types and vehicle_type not in lane.vehicle_types:
            return self._finish_deny(idem, req_hash, idempotency_key, event_repo, tenant_id, site_id,
                                     "INVALID_VEHICLE_TYPE", {"vehicle_type": vehicle_type, "allowed": lane.vehicle_types})

        # Active-session guard (DB-level partial unique index protects concurrency).
        vehicle = VehicleRepository(self.session, tenant_id).create_or_get(
            plate=plate, vehicle_type=vehicle_type, metadata=metadata or {}
        )
        repo = SessionRepository(self.session, tenant_id)
        try:
            repo.check_active_duplicate(site_id, vehicle.id)
        except ParkingError as exc:
            if exc.code == ErrorCode.ACTIVE_SESSION_ALREADY_EXISTS:
                return self._finish_deny(idem, req_hash, idempotency_key, event_repo, tenant_id, site_id,
                                         "DUPLICATE_ACTIVE_SESSION", {"plate_normalized": norm})
            raise

        # Create the parking session (reuse M2 entry flow).
        at = entry_at if entry_at is not None else datetime.now(timezone.utc)
        session = repo.create(
            site_id=site_id,
            vehicle_id=vehicle.id,
            vehicle_type=vehicle_type,
            plate_normalized=norm,
            plate_display=display_plate(plate),
            entry_gate_id=gate_id,
            entry_lane_id=lane_id,
            entry_at=at,
            public_reference=make_public_reference(site.code),
            source=source,
            metadata=metadata or {},
        )
        repo.add_event(tenant_id, site_id, session.id, EventType.SESSION_CREATED.value, actor, {"plate": norm})
        repo.update_state(session, SessionState.ENTERED.value, actor)
        repo.update_state(session, SessionState.PARKED.value, actor)
        repo.add_event(
            tenant_id, site_id, session.id, EventType.VEHICLE_ENTERED.value, actor,
            {"plate_normalized": norm, "source": source, **(metadata or {})},
        )
        repo.add_event(tenant_id, site_id, session.id, EventType.ENTRY_ALLOWED.value, actor, {"plate_normalized": norm})
        repo.add_event(
            tenant_id, site_id, session.id, EventType.BARRIER_OPEN_INTENT_CREATED.value, actor,
            {"barrier_action": BarrierAction.OPEN_BARRIER.value},
        )

        result = AdmissionResult(
            decision=AdmissionDecision.ALLOW.value,
            reason="ENTRY_ALLOWED",
            barrier_action=BarrierAction.OPEN_BARRIER.value,
            session=session,
            details={"public_reference": session.public_reference, "plate_normalized": norm},
        )

        idem.record(
            idempotency_key=idempotency_key,
            operation="gate.entry",
            request_hash=req_hash,
            result={
                "decision": result.decision,
                "reason": result.reason,
                "barrier_action": result.barrier_action,
                "details": result.details,
            },
        )

        self.session.commit()
        self.session.refresh(session)
        return AdmissionResult(
            decision=result.decision,
            reason=result.reason,
            barrier_action=result.barrier_action,
            session=session,
            details=result.details,
        )

    def _finish_deny(self, idem, req_hash, idempotency_key, event_repo, tenant_id, site_id, reason, details):
        result = self._deny(reason, details=details)
        event_repo.add_event(
            tenant_id, site_id, None, EventType.ENTRY_DENIED.value, self.scope.actor,
            {"reason": reason, "details": details},
        )
        idem.record(
            idempotency_key=idempotency_key,
            operation="gate.entry",
            request_hash=req_hash,
            result={
                "decision": result.decision,
                "reason": result.reason,
                "barrier_action": result.barrier_action,
                "details": result.details,
            },
        )
        self.session.commit()
        return result
