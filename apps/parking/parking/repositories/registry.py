"""Registry repositories: tenants (platform-level), sites, gates, lanes,
operators, vehicles, shifts. All operational lookups are tenant-scoped."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from parking.domain.errors import ErrorCode, ParkingError
from parking.domain.enums import OperatorRole, TenantStatus
from parking.domain.plate import normalize_plate
from parking.models import (
    ParkingGate,
    ParkingLane,
    ParkingOperator,
    ParkingShift,
    ParkingSite,
    ParkingTenant,
    ParkingVehicle,
)
from parking.repositories.base import ScopedRepository


class TenantRepository:
    """Tenants are platform-level; no tenant scope exists to create one."""

    def __init__(self, session):
        self.session = session

    def create(self, *, code: str, name: str, status: str = TenantStatus.ACTIVE.value) -> ParkingTenant:
        tenant = ParkingTenant(code=code, name=name, status=status)
        self.session.add(tenant)
        try:
            self.session.flush()
        except IntegrityError as exc:
            if getattr(exc.orig, "sqlstate", None) == "23505":
                raise ParkingError(ErrorCode.RESOURCE_ALREADY_EXISTS, f"tenant code {code} already exists", status=409)
            raise
        return tenant

    def get_by_code(self, code: str) -> ParkingTenant | None:
        return self.session.scalar(select(ParkingTenant).where(ParkingTenant.code == code))

    def get(self, tenant_id: int) -> ParkingTenant:
        tenant = self.session.get(ParkingTenant, tenant_id)
        if tenant is None:
            raise ParkingError(ErrorCode.PARKING_TENANT_NOT_FOUND, "tenant not found", status=404)
        return tenant


class SiteRepository(ScopedRepository):
    def create(
        self,
        *,
        code: str,
        name: str,
        timezone: str = "Asia/Jakarta",
        address: str | None = None,
        description: str | None = None,
        currency: str = "IDR",
    ) -> ParkingSite:
        site = ParkingSite(
            tenant_id=self.tenant_id,
            code=code,
            name=name,
            timezone=timezone,
            address=address,
            description=description,
            currency=currency,
        )
        self.session.add(site)
        try:
            self.session.flush()
        except IntegrityError as exc:
            if getattr(exc.orig, "sqlstate", None) == "23505":
                raise ParkingError(
                    ErrorCode.RESOURCE_ALREADY_EXISTS, f"site code {code} already exists for this tenant", status=409
                )
            raise
        return site

    def list(self) -> list[ParkingSite]:
        return list(
            self.session.scalars(select(ParkingSite).where(ParkingSite.tenant_id == self.tenant_id).order_by(ParkingSite.id))
        )

    def get(self, site_id: int) -> ParkingSite:
        site = self.session.scalar(
            select(ParkingSite).where(ParkingSite.id == site_id, ParkingSite.tenant_id == self.tenant_id)
        )
        if site is None:
            raise self.not_found_tenant_scoped(ErrorCode.PARKING_SITE_NOT_FOUND, "parking site")
        return site


class GateRepository(ScopedRepository):
    def create(
        self, *, site_id: int, code: str, name: str, direction: str, status: str = "ACTIVE"
    ) -> ParkingGate:
        # Enforce site ownership first (404 semantics for foreign tenant).
        SiteRepository(self.session, self.tenant_id).get(site_id)
        gate = ParkingGate(
            tenant_id=self.tenant_id,
            site_id=site_id,
            code=code,
            name=name,
            direction=direction,
            status=status,
        )
        self.session.add(gate)
        try:
            self.session.flush()
        except IntegrityError as exc:
            if getattr(exc.orig, "sqlstate", None) == "23505":
                raise ParkingError(
                    ErrorCode.RESOURCE_ALREADY_EXISTS, f"gate code {code} already exists for this site", status=409
                )
            raise
        return gate

    def list(self, site_id: int) -> list[ParkingGate]:
        return list(
            self.session.scalars(
                select(ParkingGate)
                .where(ParkingGate.tenant_id == self.tenant_id, ParkingGate.site_id == site_id)
                .order_by(ParkingGate.id)
            )
        )

    def get(self, site_id: int, gate_id: int) -> ParkingGate:
        gate = self.session.scalar(
            select(ParkingGate).where(
                ParkingGate.id == gate_id,
                ParkingGate.tenant_id == self.tenant_id,
                ParkingGate.site_id == site_id,
            )
        )
        if gate is None:
            raise self.not_found_tenant_scoped(ErrorCode.GATE_NOT_FOUND, "gate")
        return gate


class LaneRepository(ScopedRepository):
    def create(
        self,
        *,
        site_id: int,
        gate_id: int,
        code: str,
        name: str,
        direction: str,
        vehicle_types: list[str],
        status: str = "ACTIVE",
    ) -> ParkingLane:
        GateRepository(self.session, self.tenant_id).get(site_id, gate_id)
        lane = ParkingLane(
            tenant_id=self.tenant_id,
            site_id=site_id,
            gate_id=gate_id,
            code=code,
            name=name,
            direction=direction,
            vehicle_types=vehicle_types,
            status=status,
        )
        self.session.add(lane)
        try:
            self.session.flush()
        except IntegrityError as exc:
            if getattr(exc.orig, "sqlstate", None) == "23505":
                raise ParkingError(
                    ErrorCode.RESOURCE_ALREADY_EXISTS, f"lane code {code} already exists for this gate", status=409
                )
            raise
        return lane

    def list(self, site_id: int, gate_id: int | None = None) -> list[ParkingLane]:
        stmt = select(ParkingLane).where(ParkingLane.tenant_id == self.tenant_id, ParkingLane.site_id == site_id)
        if gate_id is not None:
            stmt = stmt.where(ParkingLane.gate_id == gate_id)
        return list(self.session.scalars(stmt.order_by(ParkingLane.id)))

    def get(self, site_id: int, gate_id: int, lane_id: int) -> ParkingLane:
        lane = self.session.scalar(
            select(ParkingLane).where(
                ParkingLane.id == lane_id,
                ParkingLane.tenant_id == self.tenant_id,
                ParkingLane.site_id == site_id,
                ParkingLane.gate_id == gate_id,
            )
        )
        if lane is None:
            raise self.not_found_tenant_scoped(ErrorCode.LANE_NOT_FOUND, "lane")
        return lane


class OperatorRepository(ScopedRepository):
    def create(
        self,
        *,
        username: str,
        display_name: str,
        api_key_hash: str,
        role: str = OperatorRole.OPERATOR.value,
        site_id: int | None = None,
    ) -> ParkingOperator:
        operator = ParkingOperator(
            tenant_id=self.tenant_id,
            site_id=site_id,
            username=username,
            display_name=display_name,
            role=role,
            api_key_hash=api_key_hash,
        )
        self.session.add(operator)
        try:
            self.session.flush()
        except IntegrityError as exc:
            if getattr(exc.orig, "sqlstate", None) == "23505":
                raise ParkingError(
                    ErrorCode.RESOURCE_ALREADY_EXISTS, f"operator {username} already exists", status=409
                )
            raise
        return operator

    def get_by_api_key_hash(self, api_key_hash: str) -> ParkingOperator | None:
        return self.session.scalar(
            select(ParkingOperator).where(ParkingOperator.api_key_hash == api_key_hash)
        )


class VehicleRepository(ScopedRepository):
    """Vehicle registry. Same normalized plate is reused across visits."""

    def find_by_plate(self, plate_normalized: str) -> ParkingVehicle | None:
        return self.session.scalar(
            select(ParkingVehicle).where(
                ParkingVehicle.tenant_id == self.tenant_id,
                ParkingVehicle.plate_normalized == plate_normalized,
            )
        )

    def create_or_get(self, *, plate: str, vehicle_type: str, metadata: dict | None = None) -> ParkingVehicle:
        norm = normalize_plate(plate)
        existing = self.find_by_plate(norm)
        if existing is not None:
            return existing
        from sqlalchemy.dialects.postgresql import insert as pg_insert

        stmt = (
            pg_insert(ParkingVehicle)
            .values(
                tenant_id=self.tenant_id,
                plate_normalized=norm,
                plate_display=plate.strip().upper(),
                vehicle_type=vehicle_type,
                metadata_=metadata or {},
            )
            .on_conflict_do_nothing(index_elements=[ParkingVehicle.tenant_id, ParkingVehicle.plate_normalized])
        )
        self.session.execute(stmt)
        self.session.flush()
        vehicle = self.find_by_plate(norm)
        assert vehicle is not None
        return vehicle


class ShiftRepository(ScopedRepository):
    def open(self, *, site_id: int, operator_id: int) -> ParkingShift:
        shift = ParkingShift(tenant_id=self.tenant_id, site_id=site_id, operator_id=operator_id)
        self.session.add(shift)
        self.session.flush()
        return shift

    def close(self, shift: ParkingShift) -> ParkingShift:
        from datetime import datetime, timezone

        shift.status = "CLOSED"
        shift.ended_at = datetime.now(timezone.utc)
        self.session.flush()
        return shift
