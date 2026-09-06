"""M4: gate/lane runtime state + request-level idempotency repositories."""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from parking.domain.errors import ErrorCode, ParkingError
from parking.models import (
    ParkingGateRuntime,
    ParkingIdempotencyRecord,
    ParkingLaneRuntime,
)
from parking.repositories.base import ScopedRepository


class GateRuntimeRepository(ScopedRepository):
    def get_or_create(self, *, site_id: int, gate_id: int) -> ParkingGateRuntime:
        rt = self.session.scalar(
            select(ParkingGateRuntime).where(
                ParkingGateRuntime.tenant_id == self.tenant_id,
                ParkingGateRuntime.site_id == site_id,
                ParkingGateRuntime.gate_id == gate_id,
            )
        )
        if rt is not None:
            return rt
        rt = ParkingGateRuntime(tenant_id=self.tenant_id, site_id=site_id, gate_id=gate_id, state="ONLINE")
        self.session.add(rt)
        try:
            self.session.flush()
        except IntegrityError:
            self.session.rollback()
            rt = self.session.scalar(
                select(ParkingGateRuntime).where(
                    ParkingGateRuntime.tenant_id == self.tenant_id,
                    ParkingGateRuntime.site_id == site_id,
                    ParkingGateRuntime.gate_id == gate_id,
                )
            )
            assert rt is not None
        return rt

    def get(self, *, site_id: int, gate_id: int) -> ParkingGateRuntime:
        rt = self.session.scalar(
            select(ParkingGateRuntime).where(
                ParkingGateRuntime.tenant_id == self.tenant_id,
                ParkingGateRuntime.site_id == site_id,
                ParkingGateRuntime.gate_id == gate_id,
            )
        )
        if rt is None:
            raise ParkingError(ErrorCode.GATE_NOT_AVAILABLE, "gate runtime state not found", status=404)
        return rt

    def set_state(self, *, site_id: int, gate_id: int, state: str, actor: str) -> ParkingGateRuntime:
        rt = self.get_or_create(site_id=site_id, gate_id=gate_id)
        if rt.state != state:
            rt.state = state
            rt.state_changed_at = datetime.now(timezone.utc)
        rt.last_seen_at = datetime.now(timezone.utc)
        self.session.flush()
        return rt


class LaneRuntimeRepository(ScopedRepository):
    def get_or_create(self, *, site_id: int, lane_id: int) -> ParkingLaneRuntime:
        rt = self.session.scalar(
            select(ParkingLaneRuntime).where(
                ParkingLaneRuntime.tenant_id == self.tenant_id,
                ParkingLaneRuntime.site_id == site_id,
                ParkingLaneRuntime.lane_id == lane_id,
            )
        )
        if rt is not None:
            return rt
        rt = ParkingLaneRuntime(tenant_id=self.tenant_id, site_id=site_id, lane_id=lane_id, state="ONLINE")
        self.session.add(rt)
        try:
            self.session.flush()
        except IntegrityError:
            self.session.rollback()
            rt = self.session.scalar(
                select(ParkingLaneRuntime).where(
                    ParkingLaneRuntime.tenant_id == self.tenant_id,
                    ParkingLaneRuntime.site_id == site_id,
                    ParkingLaneRuntime.lane_id == lane_id,
                )
            )
            assert rt is not None
        return rt

    def get(self, *, site_id: int, lane_id: int) -> ParkingLaneRuntime:
        rt = self.session.scalar(
            select(ParkingLaneRuntime).where(
                ParkingLaneRuntime.tenant_id == self.tenant_id,
                ParkingLaneRuntime.site_id == site_id,
                ParkingLaneRuntime.lane_id == lane_id,
            )
        )
        if rt is None:
            raise ParkingError(ErrorCode.LANE_NOT_AVAILABLE, "lane runtime state not found", status=404)
        return rt

    def set_state(self, *, site_id: int, lane_id: int, state: str, actor: str) -> ParkingLaneRuntime:
        rt = self.get_or_create(site_id=site_id, lane_id=lane_id)
        if rt.state != state:
            rt.state = state
            rt.state_changed_at = datetime.now(timezone.utc)
        rt.last_seen_at = datetime.now(timezone.utc)
        self.session.flush()
        return rt


class IdempotencyRepository(ScopedRepository):
    """Request-level idempotency. Same key + same request hash returns the stored
    result; same key + different request hash is rejected as a conflict."""

    def get(self, idempotency_key: str) -> ParkingIdempotencyRecord | None:
        return self.session.scalar(
            select(ParkingIdempotencyRecord).where(
                ParkingIdempotencyRecord.tenant_id == self.tenant_id,
                ParkingIdempotencyRecord.idempotency_key == idempotency_key,
            )
        )

    def record(
        self,
        *,
        idempotency_key: str,
        operation: str,
        request_hash: str,
        result: dict,
    ) -> ParkingIdempotencyRecord:
        rec = ParkingIdempotencyRecord(
            tenant_id=self.tenant_id,
            idempotency_key=idempotency_key,
            operation=operation,
            request_hash=request_hash,
            result=result,
        )
        self.session.add(rec)
        try:
            self.session.flush()
        except IntegrityError as exc:
            if getattr(exc.orig, "sqlstate", None) == "23505":
                raise ParkingError(
                    ErrorCode.IDEMPOTENCY_CONFLICT,
                    "idempotency key already used with a conflicting request",
                    status=409,
                )
            raise
        return rec
