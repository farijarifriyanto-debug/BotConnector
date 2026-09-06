"""M4: Simulated barrier intent consumer.

Deterministic, hardware-free consumer of barrier ACTION INTENTS. A real
BarrierAdapter (M8) will replace this. It never touches GPIO/relays.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class BarrierIntent:
    decision: str
    barrier_action: str
    reason: str
    details: dict = field(default_factory=dict)


class SimulatedBarrierIntentConsumer:
    """Records barrier intents in-memory. Deterministic and testable."""

    def __init__(self) -> None:
        self._intents: list[BarrierIntent] = []

    def consume(self, intent: BarrierIntent) -> None:
        self._intents.append(intent)

    @property
    def intents(self) -> list[BarrierIntent]:
        return list(self._intents)

    def last(self) -> BarrierIntent | None:
        return self._intents[-1] if self._intents else None

    def reset(self) -> None:
        self._intents.clear()
