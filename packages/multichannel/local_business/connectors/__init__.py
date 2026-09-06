"""Food delivery + third-party POS connector registry."""

from __future__ import annotations

from ..delivery_connector import DeliveryConnectorRegistry
from .gofood import GoFoodConnector
from .grabfood import GrabFoodConnector
from .shopeefood import ShopeeFoodConnector


def build_delivery_registry() -> DeliveryConnectorRegistry:
    reg = DeliveryConnectorRegistry()
    reg.register(GoFoodConnector())
    reg.register(GrabFoodConnector())
    reg.register(ShopeeFoodConnector())
    return reg
