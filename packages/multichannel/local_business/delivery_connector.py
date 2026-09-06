"""Food delivery connector framework.

Base contract for GoFood, GrabFood, ShopeeFood adapters. Each adapter
implements the same normalized interface. Real provider writes stay OFF
until credentials/authorization exist (REAL=BLOCKED_EXTERNAL).

Provider-shaped fixtures/contract tests may PASS as adapter implementation,
but are never reported as REAL API PASS.
"""

from __future__ import annotations

from abc import ABC, abstractmethod


class DeliveryConnector(ABC):
    """Base contract for a food delivery provider adapter."""

    provider: str = ""
    real_status: str = "BLOCKED_EXTERNAL"  # BLOCKED_EXTERNAL|CONNECTED

    @abstractmethod
    def status_report(self) -> dict:
        """Honest status: readiness + blocker."""

    @abstractmethod
    def normalize_order(self, raw: dict) -> dict:
        """Normalize a provider order payload into canonical delivery order fields."""

    @abstractmethod
    def normalize_menu(self, raw: dict) -> dict:
        """Normalize provider menu into canonical channel_menu_mapping fields."""

    @abstractmethod
    def verify_signature(self, payload: bytes, signature: str, secret: str) -> bool:
        """Verify inbound webhook signature per provider rules."""


class DeliveryConnectorRegistry:
    """Registry of delivery connectors."""

    def __init__(self):
        self._connectors: dict[str, DeliveryConnector] = {}

    def register(self, connector: DeliveryConnector) -> None:
        self._connectors[connector.provider] = connector

    def get(self, provider: str) -> DeliveryConnector | None:
        return self._connectors.get(provider)

    def all(self) -> list[DeliveryConnector]:
        return list(self._connectors.values())

    def status_report_all(self) -> list[dict]:
        return [c.status_report() for c in self._connectors.values()]
