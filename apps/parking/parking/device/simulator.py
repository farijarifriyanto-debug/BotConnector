"""M8: deterministic simulated barrier adapter + ONVIF Profile D fixture mapping.

No physical barrier is activated. The simulator records commands and reports
ACKs distinct from physical state.
"""

from __future__ import annotations

from parking.device.adapters import BarrierAdapter, BarrierStatus, CommandAck


class SimulatedBarrierAdapter(BarrierAdapter):
    """Deterministic simulator. Tracks physical state separately from ACKs."""

    adapter_name = "SIMULATOR"

    def __init__(self) -> None:
        self._physical_state = "CLOSED"
        self._commands: list[dict] = []

    def open(self, *, command_id: str, reason: str | None = None) -> CommandAck:
        self._commands.append({"command_id": command_id, "action": "OPEN", "reason": reason})
        # ACK accepted; physical state transitions asynchronously.
        self._physical_state = "OPENING"
        return CommandAck(accepted=True, physical_state=self._physical_state)

    def close(self, *, command_id: str, reason: str | None = None) -> CommandAck:
        self._commands.append({"command_id": command_id, "action": "CLOSE", "reason": reason})
        self._physical_state = "CLOSING"
        return CommandAck(accepted=True, physical_state=self._physical_state)

    def status(self) -> BarrierStatus:
        return BarrierStatus(state=self._physical_state)

    def set_physical_state(self, state: str) -> None:
        self._physical_state = state

    @property
    def commands(self) -> list[dict]:
        return list(self._commands)


class OnvifProfileDAdapter(BarrierAdapter):
    """ONVIF Profile D boundary for access-control peripherals (LPR camera,
    credential reader, sensor, output device). Capability-based; no conformance
    claim without verified device/client implementation."""

    adapter_name = "ONVIF_PROFILE_D"

    def __init__(self, delegate: BarrierAdapter | None = None) -> None:
        self._delegate = delegate or SimulatedBarrierAdapter()

    def open(self, *, command_id: str, reason: str | None = None) -> CommandAck:
        return self._delegate.open(command_id=command_id, reason=reason)

    def close(self, *, command_id: str, reason: str | None = None) -> CommandAck:
        return self._delegate.close(command_id=command_id, reason=reason)

    def status(self) -> BarrierStatus:
        return self._delegate.status()

    def capabilities(self) -> dict:
        return {"output_device": True, "sensor": True, "credential_reader": True, "lpr_camera": True}
