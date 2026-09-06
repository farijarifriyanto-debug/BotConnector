"""M7: ANPR Runtime — normalize events, apply confidence policy, and route to the
authoritative M4 Gate Runtime. ANPR recognition alone NEVER authorizes a gate;
it only feeds the admission decision.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone

from parking.anpr.adapters import AnprAdapter, RawAnprEvent
from parking.anpr.repo import AnprEventRepository
from parking.anpr.simulator import SimulatedAnprAdapter
from parking.domain.enums import AnprConfidenceClass, AnprEventState, EventType
from parking.domain.errors import ErrorCode, ParkingError
from parking.domain.plate import normalize_plate
from parking.gate.runtime import AdmissionResult, GateRuntimeService
from parking.models import ParkingAnprEvent
from parking.repositories.registry import SiteRepository
from parking.repositories.session_repo import SessionRepository
from parking.services.auth import Scope


@dataclass(frozen=True)
class ConfidencePolicy:
    high_threshold: float = 0.85
    low_threshold: float = 0.60

    def classify(self, confidence: float) -> AnprConfidenceClass:
        if confidence >= self.high_threshold:
            return AnprConfidenceClass.AUTO_CANDIDATE
        if confidence >= self.low_threshold:
            return AnprConfidenceClass.MANUAL_REVIEW
        return AnprConfidenceClass.REJECT


@dataclass(frozen=True)
class AnprResult:
    event: ParkingAnprEvent
    confidence_class: str
    admission: AdmissionResult | None = None
    duplicate: bool = False
    details: dict = field(default_factory=dict)


class AnprService:
    def __init__(self, session, scope: Scope, adapter: AnprAdapter | None = None,
                 policy: ConfidencePolicy | None = None):
        self.session = session
        self.scope = scope
        self.tenant_id = scope.tenant_id
        self.adapter = adapter or SimulatedAnprAdapter()
        self.policy = policy or ConfidencePolicy()
        self.repo = AnprEventRepository(session, scope.tenant_id)

    def _authorize_device(self, raw: RawAnprEvent) -> None:
        """Device identity determines authorized scope server-side. A device
        assigned to Tenant A / Site A must not submit an event for another scope."""
        if raw.tenant_id != self.tenant_id:
            raise ParkingError(ErrorCode.ANPR_DEVICE_NOT_AUTHORIZED, "device tenant mismatch", status=403)
        # Site must belong to the authorized tenant.
        SiteRepository(self.session, self.tenant_id).get(raw.site_id)

    def process(self, raw_payload: dict) -> AnprResult:
        raw = self.adapter.parse(raw_payload)
        self._authorize_device(raw)

        # Idempotency: same event_id already processed -> return prior result.
        existing = self.repo.get_by_event_id(raw.event_id)
        if existing is not None:
            return AnprResult(event=existing, confidence_class=existing.state, duplicate=True,
                              details={"duplicate": True, "event_id": raw.event_id})

        norm = normalize_plate(raw.plate_raw)
        event = ParkingAnprEvent(
            event_id=raw.event_id,
            tenant_id=self.tenant_id,
            site_id=raw.site_id,
            gate_id=raw.gate_id,
            lane_id=raw.lane_id,
            device_id=raw.device_id,
            captured_at=raw.captured_at,
            plate_raw=raw.plate_raw,
            plate_normalized=norm,
            confidence=raw.confidence,
            vehicle_type_guess=raw.vehicle_type_guess,
            direction=raw.direction,
            image_reference=raw.image_reference,
            crop_reference=raw.crop_reference,
            provider=raw.provider,
            provider_event_id=raw.provider_event_id,
            state=AnprEventState.RECEIVED.value,
            metadata_=raw.metadata,
        )
        self.repo.create(event)

        cls = self.policy.classify(raw.confidence)
        if cls == AnprConfidenceClass.REJECT:
            self.repo.set_state(event, AnprEventState.REJECTED.value)
            self.session.commit()
            return AnprResult(event=event, confidence_class=cls.value,
                              details={"reason": "LOW_CONFIDENCE", "confidence": raw.confidence})

        if cls == AnprConfidenceClass.MANUAL_REVIEW:
            self.repo.set_state(event, AnprEventState.MANUAL_REVIEW.value)
            self.session.commit()
            return AnprResult(event=event, confidence_class=cls.value,
                              details={"reason": "MANUAL_REVIEW_REQUIRED", "confidence": raw.confidence})

        # AUTO_CANDIDATE: route to authoritative M4 Gate Runtime.
        if raw.direction == "EXIT":
            # Exit flow: ANPR must not bypass payment. Route to exit runtime.
            admission = self._route_exit(raw, norm)
        else:
            admission = self._route_entry(raw, norm)

        self.repo.set_state(event, AnprEventState.PROCESSED.value)
        self.session.commit()
        self.session.refresh(event)
        return AnprResult(event=event, confidence_class=cls.value, admission=admission,
                          details={"plate_normalized": norm})

    def _route_entry(self, raw: RawAnprEvent, norm: str) -> AdmissionResult:
        if raw.gate_id is None or raw.lane_id is None:
            raise ParkingError(ErrorCode.ANPR_EVENT_INVALID, "entry ANPR event missing gate/lane", status=422)
        vehicle_type = raw.vehicle_type_guess or "CAR"
        return GateRuntimeService(self.session, self.scope).entry_request(
            site_id=raw.site_id,
            gate_id=raw.gate_id,
            lane_id=raw.lane_id,
            plate=norm,
            vehicle_type=vehicle_type,
            idempotency_key=f"anpr:{raw.event_id}",
            source="ANPR",
            metadata={"anpr_event_id": raw.event_id, "confidence": raw.confidence},
        )

    def _route_exit(self, raw: RawAnprEvent, norm: str) -> AdmissionResult:
        # ANPR exit must not bypass payment. Locate the active session by plate
        # and return a structured result; payment/exit authorization stays in M5.
        from parking.repositories.session_repo import SessionRepository
        from sqlalchemy import select
        from parking.models import ParkingSession
        from parking.domain.enums import ACTIVE_SESSION_STATES
        session = self.session.scalar(
            select(ParkingSession).where(
                ParkingSession.tenant_id == self.tenant_id,
                ParkingSession.site_id == raw.site_id,
                ParkingSession.plate_normalized == norm,
                ParkingSession.state.in_(ACTIVE_SESSION_STATES),
            ).order_by(ParkingSession.entry_at.desc()).limit(1)
        )
        if session is None:
            return AdmissionResult(decision="DENY", reason="EXIT_SESSION_NOT_FOUND",
                                   barrier_action="KEEP_CLOSED", details={"plate_normalized": norm})
        # Payment must be satisfied before exit authorization (M5 enforces this).
        from parking.exit.runtime import ExitRuntimeService
        try:
            decision = ExitRuntimeService(self.session, self.scope).exit_decision(session.public_reference)
        except ParkingError as exc:
            if exc.code == ErrorCode.PAYMENT_REQUIRED:
                return AdmissionResult(decision="DENY", reason="PAYMENT_REQUIRED",
                                       barrier_action="KEEP_CLOSED",
                                       details={"public_reference": session.public_reference})
            raise
        return AdmissionResult(decision="ALLOW" if decision.allowed else "DENY",
                               reason=decision.reason,
                               barrier_action=decision.barrier_action,
                               details={"public_reference": session.public_reference})

    def list_review(self, site_id: int | None = None, limit: int = 200) -> list[dict]:
        """List ANPR events pending manual review (operator workflow)."""
        from sqlalchemy import select
        from parking.models import ParkingAnprEvent
        stmt = select(ParkingAnprEvent).where(
            ParkingAnprEvent.tenant_id == self.tenant_id,
            ParkingAnprEvent.state == AnprEventState.MANUAL_REVIEW.value,
        )
        if site_id is not None:
            stmt = stmt.where(ParkingAnprEvent.site_id == site_id)
        stmt = stmt.order_by(ParkingAnprEvent.created_at.desc()).limit(limit)
        rows = list(self.session.scalars(stmt))
        return [
            {
                "event_id": e.event_id, "site_id": e.site_id, "gate_id": e.gate_id, "lane_id": e.lane_id,
                "plate_raw": e.plate_raw, "plate_normalized": e.plate_normalized,
                "confidence": e.confidence, "captured_at": e.captured_at,
                "image_reference": e.image_reference, "crop_reference": e.crop_reference,
            }
            for e in rows
        ]

    def correct_plate(self, event_id: str, *, corrected_plate: str, actor: str, reason: str | None = None) -> ParkingAnprEvent:
        """Audited manual plate correction. Never silently overwrites evidence."""
        event = self.repo.get_by_event_id(event_id)
        if event is None:
            raise ParkingError(ErrorCode.ANPR_EVENT_INVALID, "ANPR event not found", status=404)
        original = event.plate_normalized
        corrected = normalize_plate(corrected_plate)
        self.repo.add_correction(
            event=event, original_plate=original, corrected_plate=corrected,
            actor=actor, reason=reason, confidence=event.confidence,
        )
        event.plate_normalized = corrected
        event.plate_raw = corrected_plate
        self.repo.set_state(event, AnprEventState.CORRECTED.value)
        SessionRepository(self.session, self.tenant_id).add_event(
            self.tenant_id, event.site_id, None, EventType.MANUAL_OVERRIDE.value, actor,
            {"anpr_event_id": event_id, "original_plate": original, "corrected_plate": corrected, "reason": reason},
        )
        self.session.commit()
        self.session.refresh(event)
        return event
