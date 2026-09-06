"""M8: provider-neutral barrier adapter contract.

The BarrierAdapter cannot decide access authorization — only the Parking domain
creates OPEN intents. Adapters translate approved commands to device actions.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field


@dataclass(frozen=True)
class CommandAck:
    """Distinct from physical state: an ACK means the command was accepted by
    the device, NOT that the barrier is physically OPEN/CLOSED."""

    accepted: bool
    reason: str = ""
    physical_state: str | None = None  # observed state, if reported


@dataclass(frozen=True)
class BarrierStatus:
    state: str  # OPEN / CLOSED / OPENING / CLOSING / FAULT / UNKNOWN
    detail: dict = field(default_factory=dict)


class BarrierAdapter(ABC):
    """Contract every barrier adapter must implement."""

    adapter_name: str = "abstract"

    @abstractmethod
    def open(self, *, command_id: str, reason: str | None = None) -> CommandAck:
        """Issue an OPEN command. Returns an ACK (accepted), not physical state."""

    @abstractmethod
    def close(self, *, command_id: str, reason: str | None = None) -> CommandAck:
        """Issue a CLOSE command."""

    @abstractmethod
    def status(self) -> BarrierStatus:
        """Query observed barrier state."""
