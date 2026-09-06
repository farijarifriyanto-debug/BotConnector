"""Software-only vehicle entry (M2).

The whole flow runs in one transaction. The DB partial unique index
`uq_parking_session_active_vehicle` is the concurrency-safe duplicate guard;
the pre-check only gives a fast, friendly error for the sequential case.
"""

from __future__ import annotations

import secrets
from datetime import datetime, timezone

from parking.domain.enums import EventType, GateDirection, LaneDirection, SessionState, VehicleType
from parking.domain.errors import ErrorCode, ParkingError
from parking.domain.plate import display_plate, normalize_plate
from parking.models import ParkingSession
from parking.repositories.registry import GateRepository, LaneRepository, SiteRepository, VehicleRepository
from parking.repositories.session_repo import SessionRepository
from parking.services.auth import Scope


def make_public_reference(site_code: str) -> str:
    # Unpredictable, non-sequential ticket reference.
    return f"PK-{site_code}-{secrets.token_hex(5).upper()}"


class EntryService:
    def __init__(self, session, scope: Scope):
        self.session = session
        self.scope = scope

    def create_entry(
        self,
        *,
        site_id: int,
        gate_id: int,
        lane_id: int,
        plate: str,
        vehicle_type: str,
        entry_at: datetime | None = None,
        source: str | None = "SIMULATED_ANPR",
        metadata: dict | None = None,
    ) -> ParkingSession:
        tenant_id = self.scope.tenant_id
        actor = self.scope.actor

        site = SiteRepository(self.session, tenant_id).get(site_id)
        gate = GateRepository(self.session, tenant_id).get(site_id, gate_id)
        if gate.direction not in (GateDirection.ENTRY.value, GateDirection.BIDIRECTIONAL.value):
            raise ParkingError(
                ErrorCode.INVALID_GATE_DIRECTION,
                f"gate {gate.code} is not an entry gate (direction={gate.direction})",
                status=422,
            )

        lane = LaneRepository(self.session, tenant_id).get(site_id, gate_id, lane_id)
        if lane.direction not in (LaneDirection.ENTRY.value, LaneDirection.BIDIRECTIONAL.value):
            raise ParkingError(
                ErrorCode.INVALID_LANE,
                f"lane {lane.code} is not an entry lane (direction={lane.direction})",
                status=422,
            )
        if lane.vehicle_types and vehicle_type not in lane.vehicle_types:
            raise ParkingError(
                ErrorCode.INVALID_LANE,
                f"lane {lane.code} does not accept vehicle type {vehicle_type}",
                status=422,
            )

        norm = normalize_plate(plate)
        if not norm:
            raise ParkingError(ErrorCode.INVALID_PLATE, "license plate is empty or invalid", status=422)
        if vehicle_type not in VehicleType.__members__:
            raise ParkingError(
                ErrorCode.INVALID_VEHICLE_TYPE,
                f"unknown vehicle type {vehicle_type}",
                status=422,
            )

        at = entry_at if entry_at is not None else datetime.now(timezone.utc)

        vehicle = VehicleRepository(self.session, tenant_id).create_or_get(
            plate=plate, vehicle_type=vehicle_type, metadata=metadata or {}
        )

        repo = SessionRepository(self.session, tenant_id)
        repo.check_active_duplicate(site_id, vehicle.id)

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
            tenant_id,
            site_id,
            session.id,
            EventType.VEHICLE_ENTERED.value,
            actor,
            {"plate_normalized": norm, "source": source, **(metadata or {})},
        )

        self.session.commit()
        self.session.refresh(session)
        return session
