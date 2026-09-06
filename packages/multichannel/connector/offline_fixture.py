"""Adaptor offline/pilot untuk menguji mekanisme sinkronisasi stok.

Bukan provider sungguhan dan TIDAK dihitung sebagai acceptance nyata
terhadap marketplace. Ia membuktikan runtime worker outbox, konvergensi
kuantitas terakhir, loop protection, dan drift. Status eksplisit 'offline'.

Stok remote disimulasikan di memori (dict), tanpa menyentuh DB/provider.
"""

from __future__ import annotations

from ..connector import (
    Capability, MarketplaceConnector, ProviderId, ProviderStatus, Readiness,
)


class OfflineStore:
    """Remote stok tiruan per (provider, shop, channel_sku)."""
    def __init__(self):
        self._qty: dict[tuple, int] = {}
        self._version: dict[tuple, str] = {}
        self.fail_writes = False

    def get(self, provider, shop_id, channel_sku) -> int:
        return self._qty.get((provider, shop_id, channel_sku), -1)

    def set(self, provider, shop_id, channel_sku, qty):
        self._qty[(provider, shop_id, channel_sku)] = qty
        v = int(self._version.get((provider, shop_id, channel_sku), "0")) + 1
        self._version[(provider, shop_id, channel_sku)] = str(v)

    def version(self, provider, shop_id, channel_sku) -> str:
        return self._version.get((provider, shop_id, channel_sku), "0")


class OfflineAdapter(MarketplaceConnector):
    provider = ProviderId.SHOPEE
    name = "OfflineFixture"

    def __init__(self, store: "OfflineStore" = None):
        self.store = store if store is not None else OfflineStore()
        self.status = ProviderStatus(
            "offline-fixture", Readiness.OFFLINE,
            blocker="Adaptor OFFLINE untuk pengujian mekanisme sync; bukan provider sungguhan.",
        )

    def capabilities(self):
        return [Capability.STOCK_READ, Capability.STOCK_WRITE]

    def status_report(self) -> dict:
        return {
            "provider": "offline-fixture",
            "name": self.name,
            "readiness": self.status.readiness.value,
            "blocker": self.status.blocker,
            "offline": True,
        }

    def write_stock(self, *, provider, shop_id, channel_sku, desired_qty,
                    last_written_qty=0) -> None:
        if self.store.fail_writes:
            raise RuntimeError("simulated provider failure")
        self.store.set(provider, shop_id, channel_sku, desired_qty)

    def read_stock(self, *, provider, shop_id, channel_sku) -> int:
        return self.store.get(provider, shop_id, channel_sku)
