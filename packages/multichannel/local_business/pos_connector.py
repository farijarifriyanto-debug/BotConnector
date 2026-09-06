"""Third-party POS connector framework.

Generic contract for Moka, Pawoon, Olsera, Majoo, Qasir, Kasir Pintar, and
Universal File Connector. Capabilities: provider identity, auth/access mode,
outlet mapping, product/item mapping, sales import, refunds, discounts,
customers, COGS, payment/tender, inventory snapshot, report import,
pagination/cursor, incremental sync, idempotency, lineage, health, last sync,
error state.

Only native adapters where CURRENT official API/partner/export access is
verifiable. Vendors without accessible API use Universal File Connector.
"""

from __future__ import annotations

from abc import ABC, abstractmethod


class PosConnector(ABC):
    """Base contract for a third-party POS connector."""

    provider: str = ""
    real_status: str = "BLOCKED_EXTERNAL"

    @abstractmethod
    def status_report(self) -> dict:
        """Honest status: readiness + blocker."""

    @abstractmethod
    def normalize_sales(self, raw: dict) -> dict:
        """Normalize a POS transaction/report into canonical sale fields."""

    @abstractmethod
    def normalize_product(self, raw: dict) -> dict:
        """Normalize a POS product/item into canonical product fields."""


class PosConnectorRegistry:
    def __init__(self):
        self._connectors: dict[str, PosConnector] = {}

    def register(self, connector: PosConnector) -> None:
        self._connectors[connector.provider] = connector

    def get(self, provider: str) -> PosConnector | None:
        return self._connectors.get(provider)

    def all(self) -> list[PosConnector]:
        return list(self._connectors.values())

    def status_report_all(self) -> list[dict]:
        return [c.status_report() for c in self._connectors.values()]
