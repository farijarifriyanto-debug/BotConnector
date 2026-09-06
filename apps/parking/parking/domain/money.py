"""Money representation.

Currency amounts are stored and computed as INTEGER minor units.
For IDR the minor unit is 1 rupiah (scale 0), i.e. plain integer rupiah.
Binary floating point is never used for money in this codebase.
"""

from __future__ import annotations

# IDR: 1 minor unit == 1 rupiah (no decimals).
IDR_SCALE = 0
DEFAULT_CURRENCY = "IDR"


def validate_amount(amount: int) -> int:
    """Coerce and validate an amount. Must be a non-negative integer."""
    if isinstance(amount, bool) or not isinstance(amount, int):
        raise TypeError(f"money must be an integer, got {type(amount).__name__}")
    if amount < 0:
        raise ValueError("money amount must be non-negative")
    return amount
