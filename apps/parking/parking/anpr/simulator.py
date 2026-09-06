"""M7: deterministic simulated ANPR adapter + ONVIF Profile M fixture mapping.

No real camera is required. The simulator produces normalized events; the
Profile M adapter maps ONVIF-style fixture payloads into normalized events.
"""

from __future__ import annotations

from datetime import datetime, timezone

from parking.anpr.adapters import AnprAdapter, RawAnprEvent
from parking.domain.plate import normalize_plate


class SimulatedAnprAdapter(AnprAdapter):
    """Deterministic simulator. Confidence and plate are caller-controlled."""

    provider_name = "SIMULATOR"

    def parse(self, raw: dict) -> RawAnprEvent:
        captured_at = raw.get("captured_at")
        if isinstance(captured_at, str):
            captured_at = datetime.fromisoformat(captured_at)
        elif captured_at is None:
            captured_at = datetime.now(timezone.utc)
        return RawAnprEvent(
            event_id=raw["event_id"],
            tenant_id=raw["tenant_id"],
            site_id=raw["site_id"],
            gate_id=raw.get("gate_id"),
            lane_id=raw.get("lane_id"),
            device_id=raw.get("device_id"),
            captured_at=captured_at,
            plate_raw=raw["plate_raw"],
            confidence=float(raw.get("confidence", 0.0)),
            vehicle_type_guess=raw.get("vehicle_type_guess"),
            direction=raw.get("direction"),
            image_reference=raw.get("image_reference"),
            crop_reference=raw.get("crop_reference"),
            provider=self.provider_name,
            provider_event_id=raw.get("provider_event_id"),
            metadata=raw.get("metadata", {}),
        )

    def capabilities(self) -> dict:
        return {"plate_crop": True, "vehicle_metadata": True, "direction": True}


class OnvifProfileMAdapter(AnprAdapter):
    """Maps ONVIF Profile M-style fixture payloads into normalized events.

    Capability-based: not every ONVIF camera supports every optional feature.
    """

    provider_name = "ONVIF_PROFILE_M"

    def parse(self, raw: dict) -> RawAnprEvent:
        # ONVIF Profile M fixture: vehicle metadata + license plate recognition.
        vehicle = raw.get("vehicle", {})
        plate = raw.get("license_plate", {})
        captured_at = raw.get("captured_at")
        if isinstance(captured_at, str):
            captured_at = datetime.fromisoformat(captured_at)
        elif captured_at is None:
            captured_at = datetime.now(timezone.utc)
        plate_text = plate.get("text") or vehicle.get("plate") or ""
        return RawAnprEvent(
            event_id=raw["event_id"],
            tenant_id=raw["tenant_id"],
            site_id=raw["site_id"],
            gate_id=raw.get("gate_id"),
            lane_id=raw.get("lane_id"),
            device_id=raw.get("device_id"),
            captured_at=captured_at,
            plate_raw=plate_text,
            confidence=float(plate.get("confidence", 0.0)),
            vehicle_type_guess=vehicle.get("type"),
            direction=raw.get("direction"),
            image_reference=raw.get("image_reference"),
            crop_reference=raw.get("crop_reference"),
            provider=self.provider_name,
            provider_event_id=raw.get("provider_event_id"),
            metadata=raw.get("metadata", {}),
        )

    def capabilities(self) -> dict:
        return {"plate_crop": True, "vehicle_metadata": True, "direction": True}
