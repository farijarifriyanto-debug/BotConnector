"""Blibli Seller API connector.

API Blibli mendukung penyetelan stok ABSOLUTE via product update summary
(`stock` = nilai akhir). Karena itu adapter menulis exact desired_qty, bukan
delta — konvergen lebih aman. Kredensial seller belum tersedia -> BLOCKED.
"""

from __future__ import annotations

from ..connector import (
    Capability, MarketplaceConnector, ProviderId, ProviderStatus, Readiness,
    NormalizedProduct, NormalizedOrder, ShopIdentity,
)


class BlibliConnector(MarketplaceConnector):
    provider = ProviderId.BLIBLI
    name = "Blibli"
    status = ProviderStatus(
        "blibli",
        Readiness.BLOCKED_EXTERNAL,
        blocker="EXTERNAL_BLOCKER: API key Blibli (clientId/clientSecret/sellerKey) "
                "hanya diterbitkan lewat onboarding seller; belum disediakan.",
    )
    _capabilities = []

    def capabilities(self):
        return self._capabilities

    def status_report(self) -> dict:
        return {
            "provider": self.provider.value,
            "name": self.name,
            "readiness": self.status.readiness.value,
            "blocker": self.status.blocker,
            "auth": "BLOCKED_EXTERNAL",
            "shop_identity": "BLOCKED_EXTERNAL",
            "sku_discovery": "BLOCKED_EXTERNAL",
            "order_read": "BLOCKED_EXTERNAL",
            "stock_read": "BLOCKED_EXTERNAL",
            "stock_write_canary": "BLOCKED_EXTERNAL",
            "stock_write_semantics": "ABSOLUTE (exact set via product update summary)",
            "sandbox": "UAT api-uata.gdn-app.com tersedia bila credential disediakan",
            "note": "Absolute set-to-value: tidak menerapkan delta pada desired.",
        }

    def read_stock(self, *, shop_id, channel_sku) -> int:
        raise PermissionError(self.status.blocker)

    def write_stock(self, *, shop_id, channel_sku, desired_qty, last_written_qty=0) -> None:
        raise PermissionError(self.status.blocker)


def factory() -> BlibliConnector:
    return BlibliConnector()
