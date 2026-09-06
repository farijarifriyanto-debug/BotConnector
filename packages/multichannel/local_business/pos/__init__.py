"""Third-party POS connector registry."""

from __future__ import annotations

from ..pos_connector import PosConnectorRegistry
from .moka import MokaConnector
from .pawoon import PawoonConnector


def build_pos_registry() -> PosConnectorRegistry:
    reg = PosConnectorRegistry()
    reg.register(MokaConnector())
    reg.register(PawoonConnector())
    return reg
