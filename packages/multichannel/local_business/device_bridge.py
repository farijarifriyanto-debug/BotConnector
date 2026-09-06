"""Digital scale / local device bridge.

Extensible local-device boundary for digital scale, printer, customer display,
future cash drawer. Web Serial where appropriate (behind capability check);
local bridge protocol as fallback. Scale flow: device weight -> POS quantity
-> priced-by-weight SKU -> sale line. Validates device input (no raw trust).
"""

from __future__ import annotations

from ..persistence.db import koneksi as _pg


class ScaleReading:
    """Validated scale reading."""

    def __init__(self, weight_grams: float, stable: bool, unit: str = "g", tare: float = 0):
        self.weight_grams = weight_grams
        self.stable = stable
        self.unit = unit
        self.tare = tare

    @property
    def net_grams(self) -> float:
        return max(self.weight_grams - self.tare, 0)

    def to_quantity(self, unit_grams: float) -> float:
        """Convert weight to quantity for a priced-by-weight SKU."""
        if unit_grams <= 0:
            raise ValueError("unit_grams harus > 0")
        return round(self.net_grams / unit_grams, 3)


def validate_scale_reading(raw: str) -> ScaleReading:
    """Parse + validate a scale reading string. Rejects invalid/unstable."""
    raw = raw.strip()
    # expected format: "1234.5 g" or "1.234 kg" possibly with "ST" for stable
    parts = raw.split()
    if not parts:
        raise ValueError("reading kosong")
    try:
        value = float(parts[0])
    except ValueError:
        raise ValueError(f"nilai tidak valid: {raw}")
    unit = parts[1] if len(parts) > 1 else "g"
    stable = "ST" in raw.upper() or "STABLE" in raw.upper()
    if value < 0:
        raise ValueError("berat negatif")
    if unit.lower() in ("kg", "kilogram"):
        value *= 1000
    return ScaleReading(value, stable)


def register_device(*, business_id: int, branch_id: int, device_type: str,
                    device_id: str, protocol: str = "WEB_SERIAL",
                    config: dict | None = None) -> dict:
    with _pg() as c:
        cur = c.cursor()
        cur.execute(
            """INSERT INTO local_business.device_bridge
               (business_id, branch_id, device_type, device_id, protocol, status, config)
               VALUES (%s,%s,%s,%s,%s,'DISCONNECTED',%s)
               ON CONFLICT (business_id, branch_id, device_type, device_id) DO UPDATE SET
                 protocol=EXCLUDED.protocol, config=EXCLUDED.config
               RETURNING id, device_type, device_id, protocol, status""",
            (business_id, branch_id, device_type, device_id, protocol,
             __import__("json").dumps(config or {})))
        r = cur.fetchone()
        c.commit()
        return r


def set_device_status(*, device_id: int, status: str) -> dict:
    with _pg() as c:
        cur = c.cursor()
        cur.execute(
            "UPDATE local_business.device_bridge SET status=%s, last_seen_at=now() WHERE id=%s RETURNING id, status",
            (status, device_id))
        r = cur.fetchone()
        c.commit()
        return r
