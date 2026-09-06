"""Shopee connector.

Bekerja DI ATAS foundation Shopee yang dibekukan (tidak mengubahnya).
Credential eksternal Shopee REAL tidak tersedia di lingkungan ini, sehingga
readiness stok-tulis = BLOCKED_EXTERNAL (tidak dipalsukan).
"""

from __future__ import annotations

from ..connector import (
    Capability, MarketplaceConnector, ProviderId, ProviderStatus, Readiness,
    NormalizedProduct, NormalizedOrder, RemoteStock, ShopIdentity,
)


class ShopeeConnector(MarketplaceConnector):
    provider = ProviderId.SHOPEE
    name = "Shopee"
    status = ProviderStatus(
        "shopee",
        Readiness.BLOCKED_EXTERNAL,
        blocker="EXTERNAL_BLOCKER: partner_id/partner_key Shopee belum disediakan; "
                "aktivasi produksi belum disetujui. Foundation offline beku tetap utuh.",
    )

    def capabilities(self):
        return []

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
            "foundation_frozen": True,
        }

    # Semua operasi nyata membutuhkan credential; dijaga menolak jelas.
    def start_auth(self) -> dict:
        raise PermissionError(self.status.blocker)

    def exchange_token(self, code: str) -> dict:
        raise PermissionError(self.status.blocker)

    def read_products(self, shop_id: str):
        raise PermissionError(self.status.blocker)

    def read_orders(self, shop_id: str, since=None):
        raise PermissionError(self.status.blocker)

    def read_stock(self, *, shop_id: str, channel_sku: str) -> int:
        raise PermissionError(self.status.blocker)

    def write_stock(self, *, shop_id: str, channel_sku: str,
                    desired_qty: int, last_written_qty: int = 0) -> None:
        raise PermissionError(self.status.blocker)


def factory() -> ShopeeConnector:
    return ShopeeConnector()
