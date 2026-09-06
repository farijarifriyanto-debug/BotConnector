"""TikTok Shop / Shop-Tokopedia connector.

Platform API TIKTOK SHOP kini juga menaungi Tokopedia (Tokopedia Open API
legacy TERMINATED). Model provider-family dibedakan tetap sebagai dua
channel/storefront: TOKOPEDIA dan TIKTOK_SHOP, tetapi keduanya memakai
satu platform partner center (open-api.tiktokglobalshop.com).
"""

from __future__ import annotations

from ..connector import (
    Capability, MarketplaceConnector, ProviderId, ProviderStatus, Readiness,
    NormalizedProduct, NormalizedOrder, ShopIdentity,
)


class TikTokShopConnector(MarketplaceConnector):
    provider = ProviderId.TIKTOK_SHOP
    name = "TikTok Shop"
    status = ProviderStatus(
        "tiktok_shop",
        Readiness.BLOCKED_EXTERNAL,
        blocker="EXTERNAL_BLOCKER: app_key/app_secret TikTok Shop Partner Center "
                "belum disediakan; perlu approval app (in-house/public) di Partner Center.",
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
            "api_platform": "open-api.tiktokglobalshop.com (unified Shop/Tokopedia)",
            "note": "Tokopedia kini migrasi ke TikTok Shop Partner Center; "
                    "channel TOKOPEDIA tetap dibedakan secara konseptual.",
        }

    def read_stock(self, *, shop_id, channel_sku) -> int:
        raise PermissionError(self.status.blocker)


class TokopediaConnector(MarketplaceConnector):
    provider = ProviderId.TOKOPEDIA
    name = "Tokopedia"
    status = ProviderStatus(
        "tokopedia",
        Readiness.BLOCKED_EXTERNAL,
        blocker="EXTERNAL_BLOCKER: legacy Tokopedia Open API dihentikan; "
                "token/kredensial TikTok Shop Partner Center (channel Tokopedia) belum disediakan.",
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
            "api_platform": "open-api.tiktokglobalshop.com (channel Tokopedia)",
            "note": "Memakai unified TikTok Shop/Partner Center, bukan legacy Open API.",
        }

    def read_stock(self, *, shop_id, channel_sku) -> int:
        raise PermissionError(self.status.blocker)


def factory_tiktok() -> TikTokShopConnector:
    return TikTokShopConnector()


def factory_tokopedia() -> TokopediaConnector:
    return TokopediaConnector()
