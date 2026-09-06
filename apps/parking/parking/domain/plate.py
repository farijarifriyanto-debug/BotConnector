"""Indonesian license-plate normalization.

Normalized form is used for stable lookups / deduplication; the display form
preserves readable spacing. Normalization: uppercase, strip everything that is
not A-Z or 0-9, collapse.  " B 1234 ABC " -> normalized "B1234ABC",
display "B 1234 ABC".
"""

from __future__ import annotations

import re

_NON_ALNUM = re.compile(r"[^A-Z0-9]+")
_WS = re.compile(r"\s+")


def normalize_plate(raw: str) -> str:
    if raw is None:
        return ""
    return _NON_ALNUM.sub("", raw.upper())


def display_plate(raw: str) -> str:
    if raw is None:
        return ""
    return _WS.sub(" ", raw.strip().upper())
