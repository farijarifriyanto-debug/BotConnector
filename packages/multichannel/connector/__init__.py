"""Kerangka konektor marketplace lintas kanal (normalized contract).

Setiap provider mengimplementasi `MarketplaceConnector` abstrak di belakang
adapter. Inti BotConnector TIDAK pernah bergantung pada bentuk payload
provider; ia hanya mengenal tipe data ternormalisasi di modul `models`.

Setiap provider juga melaporkan status NYATA (kesiapan auth, read,
stock-write) tanpa membohongi: kalau credential eksternal/approval belum
ada, tercatat EXTERNAL_BLOCKER dan kesiapan = BLOCKED_EXTERNAL, bukan PASS.
"""

from __future__ import annotations

import abc
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class ProviderId(str, Enum):
    SHOPEE = "shopee"
    TOKOPEDIA = "tokopedia"
    TIKTOK_SHOP = "tiktok_shop"
    BLIBLI = "blibli"
    LAZADA = "lazada"


class Capability(str, Enum):
    AUTH = "auth"
    SHOP_IDENTITY = "shop_identity"
    SKU_DISCOVERY = "sku_discovery"
    ORDER_READ = "order_read"
    STOCK_READ = "stock_read"
    STOCK_WRITE = "stock_write"


class Readiness(str, Enum):
    NOT_IMPLEMENTED = "not_implemented"
    OFFLINE = "offline"               # diuji terhadap sandbox/fixture lokal
    READY = "ready"                  # api siap dipanggil (ada credential nyata)
    BLOCKED_EXTERNAL = "blocked_external"  # butuh approval/credential eksternal


@dataclass(frozen=True)
class ProviderStatus:
    provider: str
    readiness: Readiness
    blocker: str = ""
    detail: dict = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return self.readiness is Readiness.READY


@dataclass(frozen=True)
class ShopIdentity:
    provider: str
    shop_id: str
    name: str
    region: str = ""


@dataclass(frozen=True)
class NormalizedProduct:
    provider: str
    shop_id: str
    product_id: str
    name: str
    sku: str
    extra: dict = field(default_factory=dict)


@dataclass(frozen=True)
class NormalizedOrder:
    provider: str
    shop_id: str
    order_sn: str
    line_id: str
    status: str            # normalized: new/paid/cancelled/shipped/returned/refunded
    channel_sku: str
    qty: int
    event_seq: str         # idempotensi
    raw: dict = field(default_factory=dict)


@dataclass(frozen=True)
class RemoteStock:
    provider: str
    shop_id: str
    channel_sku: str
    qty: int
    version: str = ""


class MarketplaceConnector(abc.ABC):
    provider: ProviderId = ...
    name: str = ""
    status: ProviderStatus = ProviderStatus("", Readiness.NOT_IMPLEMENTED)

    # ---- deskriptor ----
    @abc.abstractmethod
    def capabilities(self) -> list[Capability]:
        ...

    @abc.abstractmethod
    def status_report(self) -> dict:
        """Keadaan NYATA (readiness + blocker), tanpa credential."""

    # ---- auth ----
    def start_auth(self) -> dict:
        raise NotImplementedError

    def exchange_token(self, code: str) -> dict:
        raise NotImplementedError

    # ---- read ----
    def read_shop(self, shop_id: str) -> ShopIdentity | None:
        raise NotImplementedError

    def read_products(self, shop_id: str) -> list[NormalizedProduct]:
        raise NotImplementedError

    def read_orders(self, shop_id: str, since) -> list[NormalizedOrder]:
        raise NotImplementedError

    def read_stock(self, *, shop_id: str, channel_sku: str) -> int:
        raise NotImplementedError

    # ---- write (dipakai outbox; gerbang GLOBAL_STOCK_WRITE ditegakkan di sync) ----
    def write_stock(self, *, shop_id: str, channel_sku: str,
                    desired_qty: int, last_written_qty: int = 0) -> None:
        raise NotImplementedError
