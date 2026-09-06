"""Session repository: transactional creation (with DB-level duplicate guard),
scoped lookups, state transitions with event + audit recording."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from parking.domain.errors import ErrorCode, ParkingError
from parking.domain.enums import ACTIVE_SESSION_STATES, EventType, SessionState
from parking.domain.state_machine import assert_transition
from parking.models import ParkingAuditLog, ParkingEvent, ParkingSession
from parking.repositories.base import ScopedRepository

ACTIVE_DUP_INDEX = "uq_parking_session_active_vehicle"
_LIST_LIMIT = 500


class SessionRepository(ScopedRepository):
    def create(
        self,
        *,
        site_id: int,
        vehicle_id: int,
        vehicle_type: str,
        plate_normalized: str,
        plate_display: str,
        entry_gate_id: int,
        entry_lane_id: int,
        entry_at: datetime,
        public_reference: str,
        source: str | None = None,
        metadata: dict | None = None,
    ) -> ParkingSession:
        session = ParkingSession(
            tenant_id=self.tenant_id,
            site_id=site_id,
            vehicle_id=vehicle_id,
            vehicle_type=vehicle_type,
            plate_normalized=plate_normalized,
            plate_display=plate_display,
            entry_gate_id=entry_gate_id,
            entry_lane_id=entry_lane_id,
            entry_at=entry_at,
            public_reference=public_reference,
            state=SessionState.CREATED.value,
            source=source,
            metadata_=metadata or {},
        )
        self.session.add(session)
        try:
            self.session.flush()
        except IntegrityError as exc:
            if getattr(exc.orig, "sqlstate", None) == "23505":
                constraint = getattr(getattr(exc.orig, "diag", None), "constraint_name", "") or ""
                if ACTIVE_DUP_INDEX in constraint:
                    raise ParkingError(
                        ErrorCode.ACTIVE_SESSION_ALREADY_EXISTS,
                        "this vehicle already has an active parking session at this site",
                        status=409,
                    )
                raise ParkingError(
                    ErrorCode.RESOURCE_ALREADY_EXISTS, "parking session resource conflict", status=409
                )
            raise
        return session

    def check_active_duplicate(self, site_id: int, vehicle_id: int) -> None:
        exists = self.session.scalar(
            select(ParkingSession.id)
            .where(
                ParkingSession.tenant_id == self.tenant_id,
                ParkingSession.site_id == site_id,
                ParkingSession.vehicle_id == vehicle_id,
                ParkingSession.state.in_(ACTIVE_SESSION_STATES),
            )
            .limit(1)
        )
        if exists is not None:
            raise ParkingError(
                ErrorCode.ACTIVE_SESSION_ALREADY_EXISTS,
                "this vehicle already has an active parking session at this site",
                status=409,
            )

    def get_by_public_reference(self, public_reference: str) -> ParkingSession:
        session = self.session.scalar(
            select(ParkingSession).where(
                ParkingSession.public_reference == public_reference,
                ParkingSession.tenant_id == self.tenant_id,
            )
        )
        if session is None:
            raise ParkingError(ErrorCode.SESSION_NOT_FOUND, "parking session not found", status=404)
        return session

    def get_by_id(self, session_id: int) -> ParkingSession:
        session = self.session.scalar(
            select(ParkingSession).where(
                ParkingSession.id == session_id, ParkingSession.tenant_id == self.tenant_id
            )
        )
        if session is None:
            raise ParkingError(ErrorCode.SESSION_NOT_FOUND, "parking session not found", status=404)
        return session

    def list_active(self, site_id: int | None = None) -> list[ParkingSession]:
        stmt = (
            select(ParkingSession)
            .where(
                ParkingSession.tenant_id == self.tenant_id,
                ParkingSession.state.in_(ACTIVE_SESSION_STATES),
            )
            .order_by(ParkingSession.entry_at.desc())
            .limit(_LIST_LIMIT)
        )
        if site_id is not None:
            stmt = stmt.where(ParkingSession.site_id == site_id)
        return list(self.session.scalars(stmt))

    def list_by_site(self, site_id: int, state: str | None = None) -> list[ParkingSession]:
        stmt = (
            select(ParkingSession)
            .where(ParkingSession.tenant_id == self.tenant_id, ParkingSession.site_id == site_id)
            .order_by(ParkingSession.entry_at.desc())
            .limit(_LIST_LIMIT)
        )
        if state is not None:
            stmt = stmt.where(ParkingSession.state == state)
        return list(self.session.scalars(stmt))

    def update_state(self, session: ParkingSession, target: str, actor: str) -> ParkingSession:
        current = session.state
        assert_transition(current, target)
        session.state = target
        self.session.flush()
        self.add_event(
            session.tenant_id,
            session.site_id,
            session.id,
            EventType.STATE_CHANGED.value,
            actor,
            {"from": current, "to": target},
        )
        return session

    def add_event(
        self,
        tenant_id: int,
        site_id: int,
        session_id: int | None,
        event_type: str,
        actor: str | None,
        metadata: dict | None = None,
    ) -> ParkingEvent:
        event = ParkingEvent(
            tenant_id=tenant_id,
            site_id=site_id,
            session_id=session_id,
            event_type=event_type,
            actor=actor,
            metadata_=metadata or {},
        )
        self.session.add(event)
        self.session.flush()
        return event

    def add_audit(
        self,
        *,
        tenant_id: int,
        actor: str,
        action: str,
        object_type: str,
        object_id: str | None = None,
        site_id: int | None = None,
        details: dict | None = None,
    ) -> ParkingAuditLog:
        entry = ParkingAuditLog(
            tenant_id=tenant_id,
            site_id=site_id,
            actor=actor,
            action=action,
            object_type=object_type,
            object_id=object_id,
            details=details or {},
        )
        self.session.add(entry)
        self.session.flush()
        return entry

    def list_events(self, session_id: int) -> list[ParkingEvent]:
        return list(
            self.session.scalars(
                select(ParkingEvent)
                .where(ParkingEvent.tenant_id == self.tenant_id, ParkingEvent.session_id == session_id)
                .order_by(ParkingEvent.occurred_at, ParkingEvent.id)
            )
        )
