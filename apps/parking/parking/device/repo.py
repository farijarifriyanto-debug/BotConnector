"""M8: device registry + runtime + barrier command repositories (tenant-scoped)."""

from __future__ import annotations

import secrets
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from parking.domain.errors import ErrorCode, ParkingError
from parking.models import (
    ParkingBarrierCommand,
    ParkingDevice,
    ParkingDeviceRuntime,
)
from parking.repositories.base import ScopedRepository


def make_command_id() -> str:
    return f"CMD-{secrets.token_hex(5).upper()}"


class DeviceRepository(ScopedRepository):
    def create(
        self,
        *,
        device_id: str,
        site_id: int,
        device_type: str,
        name: str,
        adapter_type: str,
        gate_id: int | None = None,
        lane_id: int | None = None,
        configuration_reference: str | None = None,
        credential_reference: str | None = None,
    ) -> ParkingDevice:
        device = ParkingDevice(
            device_id=device_id,
            tenant_id=self.tenant_id,
            site_id=site_id,
            gate_id=gate_id,
            lane_id=lane_id,
            device_type=device_type,
            name=name,
            adapter_type=adapter_type,
            status="ACTIVE",
            enabled=True,
            configuration_reference=configuration_reference,
            credential_reference=credential_reference,
        )
        self.session.add(device)
        try:
            self.session.flush()
        except IntegrityError as exc:
            if getattr(exc.orig, "sqlstate", None) == "23505":
                raise ParkingError(ErrorCode.RESOURCE_ALREADY_EXISTS, f"device {device_id} already exists", status=409)
            raise
        return device

    def get_by_device_id(self, device_id: str) -> ParkingDevice:
        device = self.session.scalar(
            select(ParkingDevice).where(
                ParkingDevice.tenant_id == self.tenant_id, ParkingDevice.device_id == device_id
            )
        )
        if device is None:
            raise ParkingError(ErrorCode.DEVICE_NOT_FOUND, "device not found", status=404)
        return device

    def get(self, device_pk: int) -> ParkingDevice:
        device = self.session.scalar(
            select(ParkingDevice).where(ParkingDevice.id == device_pk, ParkingDevice.tenant_id == self.tenant_id)
        )
        if device is None:
            raise ParkingError(ErrorCode.DEVICE_NOT_FOUND, "device not found", status=404)
        return device

    def list_for_site(self, site_id: int) -> list[ParkingDevice]:
        return list(
            self.session.scalars(
                select(ParkingDevice).where(
                    ParkingDevice.tenant_id == self.tenant_id, ParkingDevice.site_id == site_id
                )
            )
        )


class DeviceRuntimeRepository(ScopedRepository):
    def get_or_create(self, *, site_id: int, device_pk: int) -> ParkingDeviceRuntime:
        rt = self.session.scalar(
            select(ParkingDeviceRuntime).where(
                ParkingDeviceRuntime.tenant_id == self.tenant_id,
                ParkingDeviceRuntime.site_id == site_id,
                ParkingDeviceRuntime.device_id == device_pk,
            )
        )
        if rt is not None:
            return rt
        rt = ParkingDeviceRuntime(tenant_id=self.tenant_id, site_id=site_id, device_id=device_pk, state="UNKNOWN")
        self.session.add(rt)
        try:
            self.session.flush()
        except IntegrityError:
            self.session.rollback()
            rt = self.session.scalar(
                select(ParkingDeviceRuntime).where(
                    ParkingDeviceRuntime.tenant_id == self.tenant_id,
                    ParkingDeviceRuntime.site_id == site_id,
                    ParkingDeviceRuntime.device_id == device_pk,
                )
            )
            assert rt is not None
        return rt

    def set_state(self, *, site_id: int, device_pk: int, state: str) -> ParkingDeviceRuntime:
        rt = self.get_or_create(site_id=site_id, device_pk=device_pk)
        if rt.state != state:
            rt.state = state
            rt.state_changed_at = datetime.now(timezone.utc)
        rt.last_seen_at = datetime.now(timezone.utc)
        self.session.flush()
        return rt


class BarrierCommandRepository(ScopedRepository):
    def create(
        self,
        *,
        site_id: int,
        lane_id: int | None,
        device_pk: int,
        command_type: str,
        requested_by: str,
        reason: str | None,
        idempotency_key: str,
    ) -> ParkingBarrierCommand:
        command = ParkingBarrierCommand(
            command_id=make_command_id(),
            tenant_id=self.tenant_id,
            site_id=site_id,
            lane_id=lane_id,
            device_id=device_pk,
            command_type=command_type,
            status="CREATED",
            requested_by=requested_by,
            reason=reason,
            idempotency_key=idempotency_key,
            attempt_count=0,
            metadata_={},
        )
        self.session.add(command)
        try:
            self.session.flush()
        except IntegrityError as exc:
            if getattr(exc.orig, "sqlstate", None) == "23505":
                raise ParkingError(ErrorCode.DEVICE_COMMAND_CONFLICT, "command idempotency key already used", status=409)
            raise
        return command

    def get_by_idempotency_key(self, idempotency_key: str) -> ParkingBarrierCommand | None:
        return self.session.scalar(
            select(ParkingBarrierCommand).where(
                ParkingBarrierCommand.tenant_id == self.tenant_id,
                ParkingBarrierCommand.idempotency_key == idempotency_key,
            )
        )

    def get_by_command_id(self, command_id: str) -> ParkingBarrierCommand:
        command = self.session.scalar(
            select(ParkingBarrierCommand).where(
                ParkingBarrierCommand.tenant_id == self.tenant_id,
                ParkingBarrierCommand.command_id == command_id,
            )
        )
        if command is None:
            raise ParkingError(ErrorCode.DEVICE_COMMAND_INVALID, "barrier command not found", status=404)
        return command

    def set_status(self, command: ParkingBarrierCommand, status: str, *, ack_at: datetime | None = None) -> ParkingBarrierCommand:
        command.status = status
        if ack_at is not None:
            command.ack_at = ack_at
        self.session.flush()
        return command
