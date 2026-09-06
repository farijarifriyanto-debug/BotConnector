"""M7: provider/vendor-neutral ANPR adapter contract.

The Parking domain consumes NORMALIZED ANPR events and never depends directly on
camera-specific payload structures. Real vendors (Hikvision, Dahua, ZKTeco, ...)
plug in later without touching domain logic.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime


@dataclass(frozen=True)
class RawAnprEvent:
    """Vendor-agnostic normalized ANPR recognition event."""

    event_id: str
    tenant_id: int
    site_id: int
    gate_id: int | None
    lane_id: int | None
    device_id: int | None
    captured_at: datetime
    plate_raw: str
    confidence: float
    vehicle_type_guess: str | None = None
    direction: str | None = None
    image_reference: str | None = None
    crop_reference: str | None = None
    provider: str = "UNKNOWN"
    provider_event_id: str | None = None
    metadata: dict = field(default_factory=dict)


class AnprAdapter(ABC):
    """Contract every ANPR adapter must implement."""

    provider_name: str = "abstract"

    @abstractmethod
    def parse(self, raw: dict) -> RawAnprEvent:
        """Map a vendor-specific payload into a normalized RawAnprEvent."""

    @abstractmethod
    def capabilities(self) -> dict:
        """Return capability flags (e.g. whether plate crop / vehicle metadata
        are available). Profile M support is capability-based."""
