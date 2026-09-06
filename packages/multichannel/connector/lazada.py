"""Lazada Open Platform connector.

Auth: seller OAuth code-for-token, request ditandatangani (signMethod=sha256).
Inventory:
  - UPDATE (product/stock/sellable/update) = ABSOLUTE set (yang dipakai adapter ini)
  - ADJUST (product/stock/sellable/adjust) = DELTA
Adapter memakai UPDATE (absolute) agar konvergen aman.
Penting: sellable/locked (withhold) marketplace BUKAN ON_HAND gudang pusat.
Kredensial app/seller belum tersedia -> BLOCKED.
"""

from __future__ import annotations

from ..connector import (
    Capability, MarketplaceConnector, ProviderId, ProviderStatus, Readiness,
    NormalizedProduct, NormalizedOrder, ShopIdentity,
)


class LazadaConnector(MarketplaceConnector):
    provider = ProviderId.LAZADA
    name = "Lazada"
    status = ProviderStatus(
        "lazada",
        Readiness.BLOCKED_EXTERNAL,
        blocker="EXTERNAL_BLOCKER: app_key/app_secret (Open Platform console) dan "
                "access_token seller Lazada belum disediakan.",
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
            "stock_write_semantics": "ABSOLUTE via product/stock/sellable/update",
            "adjust_semantics": "DELTA via product/stock/sellable/adjust (tidak dipakai utk absolute)",
            "note": "sellable/withhold/occupy marketplace BUKAN ON_HAND gudang; "
                    "hanya AVAILABLE_TO_PROMISE didorong sebagai sellable.",
        }

    def read_stock(self, *, shop_id, channel_sku) -> int:
        raise PermissionError(self.status.blocker)

    def write_stock(self, *, shop_id, channel_sku, desired_qty, last_written_qty=0) -> None:
        raise PermissionError(self.status.blocker)


def factory() -> LazadaConnector:
    return LazadaConnector()
