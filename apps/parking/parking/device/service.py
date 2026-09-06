"""M8: Barrier Runtime — explicit, auditable, idempotent device commands.

Only the Parking domain creates OPEN intents; the BarrierAdapter never decides
authorization. Commands are explicit (OPEN/CLOSE/STATUS) and idempotent by key.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone

from parking.device.adapters import BarrierAdapter
from parking.device.repo import BarrierCommandRepository, DeviceRepository, DeviceRuntimeRepository
from parking.device.simulator import SimulatedBarrierAdapter
from parking.domain.enums import (
    BarrierCommandStatus,
    BarrierCommandType,
    DeviceRuntimeState,
    FailPolicy,
)
from parking.domain.errors import ErrorCode, ParkingError
from parking.models import ParkingBarrierCommand
from parking.repositories.registry import SiteRepository
from parking.services.auth import Scope


@dataclass(frozen=True)
class BarrierCommandResult:
    command: ParkingBarrierCommand
    ack: object | None = None
    physical_state: str | None = None
    details: dict = field(default_factory=dict)


class BarrierService:
    def __init__(self, session, scope: Scope, adapter: BarrierAdapter | None = None,
                 fail_policy: str = FailPolicy.FAIL_CLOSED.value):
        self.session = session
        self.scope = scope
        self.tenant_id = scope.tenant_id
        self.adapter = adapter or SimulatedBarrierAdapter()
        self.fail_policy = fail_policy
        self.devices = DeviceRepository(session, scope.tenant_id)
        self.runtimes = DeviceRuntimeRepository(session, scope.tenant_id)
        self.commands = BarrierCommandRepository(session, scope.tenant_id)

    def _authorize_device(self, device_pk: int, site_id: int) -> object:
        device = self.devices.get(device_pk)
        if device.site_id != site_id:
            raise ParkingError(ErrorCode.DEVICE_NOT_AUTHORIZED, "device not assigned to this site", status=403)
        return device

    def dispatch(self, *, site_id: int, device_id: str, command_type: str,
                 idempotency_key: str, reason: str | None = None) -> BarrierCommandResult:
        """Dispatch an approved barrier command. Idempotent by key."""
        device = self.devices.get_by_device_id(device_id)
        self._authorize_device(device.id, site_id)
        SiteRepository(self.session, self.tenant_id).get(site_id)

        if command_type not in (BarrierCommandType.OPEN.value, BarrierCommandType.CLOSE.value,
                                BarrierCommandType.STATUS.value):
            raise ParkingError(ErrorCode.DEVICE_COMMAND_INVALID, f"unsupported command {command_type}", status=422)

        # Idempotency: same key returns the same logical command.
        existing = self.commands.get_by_idempotency_key(idempotency_key)
        if existing is not None:
            return BarrierCommandResult(command=existing, details={"idempotent": True})

        # Device runtime must be ONLINE to dispatch (unless STATUS).
        rt = self.runtimes.get_or_create(site_id=site_id, device_pk=device.id)
        if command_type != BarrierCommandType.STATUS.value and rt.state != DeviceRuntimeState.ONLINE.value:
            raise ParkingError(ErrorCode.DEVICE_OFFLINE, f"device {device_id} is {rt.state}", status=409)

        command = self.commands.create(
            site_id=site_id, lane_id=device.lane_id, device_pk=device.id,
            command_type=command_type, requested_by=self.scope.actor, reason=reason,
            idempotency_key=idempotency_key,
        )
        self.commands.set_status(command, BarrierCommandStatus.DISPATCHED.value)

        # Dispatch to adapter.
        try:
            if command_type == BarrierCommandType.OPEN.value:
                ack = self.adapter.open(command_id=command.command_id, reason=reason)
            elif command_type == BarrierCommandType.CLOSE.value:
                ack = self.adapter.close(command_id=command.command_id, reason=reason)
            else:
                status = self.adapter.status()
                self.commands.set_status(command, BarrierCommandStatus.ACKNOWLEDGED.value,
                                         ack_at=datetime.now(timezone.utc))
                self.session.commit()
                self.session.refresh(command)
                return BarrierCommandResult(command=command, physical_state=status.state,
                                            details={"status": status.state})
        except Exception as exc:  # pragma: no cover - adapter failure path
            self.commands.set_status(command, BarrierCommandStatus.FAILED.value)
            self.session.commit()
            raise ParkingError(ErrorCode.DEVICE_OFFLINE, f"adapter dispatch failed: {type(exc).__name__}", status=502)

        if ack.accepted:
            self.commands.set_status(command, BarrierCommandStatus.ACKNOWLEDGED.value,
                                     ack_at=datetime.now(timezone.utc))
        else:
            self.commands.set_status(command, BarrierCommandStatus.FAILED.value)

        self.session.commit()
        self.session.refresh(command)
        return BarrierCommandResult(command=command, ack=ack, physical_state=ack.physical_state,
                                    details={"ack_accepted": ack.accepted})

    def acknowledge(self, command_id: str) -> BarrierCommandResult:
        """Mark a command acknowledged (accepted by device). Distinct from
        physical state confirmation."""
        command = self.commands.get_by_command_id(command_id)
        self.commands.set_status(command, BarrierCommandStatus.ACKNOWLEDGED.value,
                                 ack_at=datetime.now(timezone.utc))
        self.session.commit()
        self.session.refresh(command)
        return BarrierCommandResult(command=command, details={"acknowledged": True})

    def report_physical_state(self, *, site_id: int, device_id: str, state: str) -> BarrierCommandResult:
        """Report observed physical barrier state (separate from command ACK)."""
        device = self.devices.get_by_device_id(device_id)
        self._authorize_device(device.id, site_id)
        # Physical state is observed, not a command; record via runtime metadata.
        return BarrierCommandResult(command=None, physical_state=state,
                                    details={"observed_state": state})
