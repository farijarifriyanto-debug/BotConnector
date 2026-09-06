"""M7: ANPR event repository (tenant-scoped)."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from parking.domain.errors import ErrorCode, ParkingError
from parking.models import ParkingAnprCorrection, ParkingAnprEvent
from parking.repositories.base import ScopedRepository


class AnprEventRepository(ScopedRepository):
    def create(self, event: ParkingAnprEvent) -> ParkingAnprEvent:
        self.session.add(event)
        try:
            self.session.flush()
        except IntegrityError as exc:
            if getattr(exc.orig, "sqlstate", None) == "23505":
                raise ParkingError(
                    ErrorCode.ANPR_EVENT_DUPLICATE, "ANPR event already processed", status=409
                )
            raise
        return event

    def get_by_event_id(self, event_id: str) -> ParkingAnprEvent | None:
        return self.session.scalar(
            select(ParkingAnprEvent).where(
                ParkingAnprEvent.tenant_id == self.tenant_id,
                ParkingAnprEvent.event_id == event_id,
            )
        )

    def get_by_provider_event(self, provider: str, provider_event_id: str) -> ParkingAnprEvent | None:
        return self.session.scalar(
            select(ParkingAnprEvent).where(
                ParkingAnprEvent.tenant_id == self.tenant_id,
                ParkingAnprEvent.provider == provider,
                ParkingAnprEvent.provider_event_id == provider_event_id,
            )
        )

    def set_state(self, event: ParkingAnprEvent, state: str) -> ParkingAnprEvent:
        event.state = state
        self.session.flush()
        return event

    def add_correction(
        self,
        *,
        event: ParkingAnprEvent,
        original_plate: str,
        corrected_plate: str,
        actor: str,
        reason: str | None,
        confidence: float,
    ) -> ParkingAnprCorrection:
        correction = ParkingAnprCorrection(
            tenant_id=self.tenant_id,
            site_id=event.site_id,
            anpr_event_id=event.id,
            original_plate=original_plate,
            corrected_plate=corrected_plate,
            actor=actor,
            reason=reason,
            confidence=confidence,
        )
        self.session.add(correction)
        self.session.flush()
        return correction
