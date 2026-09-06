"""ShopeeFood adapter (ShopeeFood Indonesia Vendor/OpenAPI).

Current official docs (developer.shopeefood.co.id/vendor/api-docs) are behind
vendor login; access limitation recorded. Modeled on documented concepts:
  - auth/token/signature boundary
  - staging/production config
  - vendor/store identity
  - menu synchronization + result/status
  - dish/menu availability, modifier/options, price/promotion
  - store open/pause
  - order ingest/get/list, order status, mark ready, cancel
  - retry/replay behavior

Webhook/order delivery is idempotent: provider + store + external_order_id.
Repeated delivery (1x/5x/10x) produces ONE restaurant order, ONE KOT, ONE
ingredient effect, ONE Finance effect.

REAL=BLOCKED_EXTERNAL until ShopeeFood vendor credential exists.
"""

from __future__ import annotations

import hashlib
import hmac

from ..delivery_connector import DeliveryConnector

SHOPEEFOOD_STAGING = "https://stg-merchant.shopee.co.id"
SHOPEEFOOD_PROD = "https://merchant.shopee.co.id"


class ShopeeFoodConnector(DeliveryConnector):
    provider = "SHOPEEFOOD"
    real_status = "BLOCKED_EXTERNAL"

    def __init__(self, base_url: str = SHOPEEFOOD_PROD):
        self.base_url = base_url
        self.blocker = "ShopeeFood vendor credential belum tersedia (REAL=BLOCKED_EXTERNAL)"

    def status_report(self) -> dict:
        return {
            "provider": self.provider,
            "real_status": self.real_status,
            "readiness": "blocked_external",
            "blocker": self.blocker,
            "auth": "token_signature",
            "docs_access": "documentation behind vendor login (access limitation recorded)",
            "endpoints": {
                "menu_sync": f"{self.base_url}/api/v2/menu/sync",
                "menu_status": f"{self.base_url}/api/v2/menu/status",
                "order_ingest": f"{self.base_url}/api/v2/order/ingest",
                "order_list": f"{self.base_url}/api/v2/order/list",
                "order_status": f"{self.base_url}/api/v2/order/status",
                "mark_ready": f"{self.base_url}/api/v2/order/ready",
                "cancel": f"{self.base_url}/api/v2/order/cancel",
                "store_status": f"{self.base_url}/api/v2/store/status",
            },
        }

    def normalize_order(self, raw: dict) -> dict:
        """Normalize a ShopeeFood order into canonical fields."""
        order = raw.get("order", raw)
        items = order.get("items", [])
        lines = []
        for it in items:
            lines.append({
                "channel_item_id": str(it.get("item_id", "")),
                "name": it.get("name", ""),
                "quantity": int(it.get("quantity", 0)),
                "unit_price": float(it.get("price", 0)),
                "modifiers": it.get("options", []),
            })
        return {
            "source_provider": "SHOPEEFOOD",
            "external_order_id": str(order.get("order_id", "")),
            "outlet_id": str(order.get("store_id", "")),
            "order_type": "DELIVERY",
            "lines": lines,
            "gross_value": float(order.get("total", 0)),
            "discount": float(order.get("discount", 0)),
            "payment_state": "UNPAID",
            "provider_status": str(order.get("status", "")),
            "raw_payload": raw,
        }

    def normalize_menu(self, raw: dict) -> dict:
        """Normalize ShopeeFood menu into canonical channel_menu_mapping fields."""
        items = []
        for cat in raw.get("categories", []):
            for it in cat.get("dishes", []):
                items.append({
                    "channel_item_id": str(it.get("dish_id", "")),
                    "name": it.get("name", ""),
                    "channel_price": float(it.get("price", 0)),
                    "available": it.get("is_available", True),
                })
        return {"channel": "SHOPEEFOOD", "items": items}

    def verify_signature(self, payload: bytes, signature: str, secret: str) -> bool:
        """ShopeeFood webhook signature verification (HMAC-SHA256)."""
        if not secret:
            return False
        expected = hmac.new(secret.encode(), payload, hashlib.sha256).hexdigest()
        return hmac.compare_digest(expected, signature or "")
