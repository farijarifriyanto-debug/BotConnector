"""GrabFood adapter (Grab-owned SDK / developer.grab.com).

Based on CURRENT authoritative GrabFood API (github.com/grab/grabfood-api-sdk-go):
  - OAuth2: POST /grabid/v1/oauth2/token (client_credentials, scope food.partner_api)
  - Base: https://partner-api.grab.com/grabfood
  - Accept/reject: POST /partner/v1/order/prepare
  - Cancel: PUT /partner/v1/order/cancel
  - List orders: GET /partner/v1/orders
  - Mark ready: POST /partner/v1/orders/mark
  - Update ready time: PUT /partner/v1/order/readytime
  - Update delivery state: POST /partner/v1/order/delivery
  - Refund: POST /partner/v1/orders/refund
  - Menu update: PUT /partner/v1/menu, batch: PUT /partner/v1/batch/menu
  - Menu sync trace: GET /partner/v1/merchant/menu/trace
  - Store status: GET /partner/v1/merchants/{id}/store/status
  - Store hours: GET /partner/v2/merchants/{id}/store/hours
  - Campaigns: POST/GET/PUT/DELETE /partner/v1/campaigns
  - POS order sync: POST /partner/v1/pos/order

Preserves merchant-funded campaign/promotion fields separately.
REAL=BLOCKED_EXTERNAL until Grab credential exists.
"""

from __future__ import annotations

import hashlib
import hmac

from ..delivery_connector import DeliveryConnector

GRAB_OAUTH_URL = "https://api.grab.com/grabid/v1/oauth2/token"
GRAB_BASE = "https://partner-api.grab.com/grabfood"
GRAB_SCOPE = "food.partner_api"


class GrabFoodConnector(DeliveryConnector):
    provider = "GRABFOOD"
    real_status = "BLOCKED_EXTERNAL"

    def __init__(self, base_url: str = GRAB_BASE):
        self.base_url = base_url
        self.blocker = "Grab credential belum tersedia (REAL=BLOCKED_EXTERNAL)"

    def status_report(self) -> dict:
        return {
            "provider": self.provider,
            "real_status": self.real_status,
            "readiness": "blocked_external",
            "blocker": self.blocker,
            "auth": "oauth2_client_credentials",
            "scope": GRAB_SCOPE,
            "endpoints": {
                "oauth": GRAB_OAUTH_URL,
                "list_orders": f"{self.base_url}/partner/v1/orders",
                "accept_reject": f"{self.base_url}/partner/v1/order/prepare",
                "cancel": f"{self.base_url}/partner/v1/order/cancel",
                "mark_ready": f"{self.base_url}/partner/v1/orders/mark",
                "ready_time": f"{self.base_url}/partner/v1/order/readytime",
                "delivery_state": f"{self.base_url}/partner/v1/order/delivery",
                "refund": f"{self.base_url}/partner/v1/orders/refund",
                "menu": f"{self.base_url}/partner/v1/menu",
                "batch_menu": f"{self.base_url}/partner/v1/batch/menu",
                "menu_trace": f"{self.base_url}/partner/v1/merchant/menu/trace",
                "store_status": f"{self.base_url}/partner/v1/merchants/{{id}}/store/status",
                "store_hours": f"{self.base_url}/partner/v2/merchants/{{id}}/store/hours",
                "campaigns": f"{self.base_url}/partner/v1/campaigns",
                "pos_order": f"{self.base_url}/partner/v1/pos/order",
            },
        }

    def normalize_order(self, raw: dict) -> dict:
        """Normalize a GrabFood order into canonical fields."""
        order = raw.get("order", raw)
        items = order.get("items", [])
        lines = []
        for it in items:
            lines.append({
                "channel_item_id": str(it.get("id", "")),
                "name": it.get("name", ""),
                "quantity": int(it.get("quantity", 0)),
                "unit_price": float(it.get("price", 0)),
                "modifiers": it.get("modifiers", []),
            })
        # preserve promotion fields separately (merchant vs platform)
        promos = order.get("promos", [])
        merchant_promo = sum(float(p.get("merchant_funded", 0)) for p in promos)
        platform_promo = sum(float(p.get("platform_funded", 0)) for p in promos)
        return {
            "source_provider": "GRABFOOD",
            "external_order_id": str(order.get("orderID", "")),
            "outlet_id": str(order.get("merchantID", "")),
            "order_type": "DELIVERY",
            "lines": lines,
            "gross_value": float(order.get("totalAmount", 0)),
            "discount": float(order.get("discountAmount", 0)),
            "merchant_promo_cost": merchant_promo,
            "platform_promo": platform_promo,
            "payment_state": "UNPAID",
            "provider_status": str(order.get("state", "")),
            "raw_payload": raw,
        }

    def normalize_menu(self, raw: dict) -> dict:
        """Normalize GrabFood menu into canonical channel_menu_mapping fields."""
        items = []
        for section in raw.get("sections", []):
            for cat in section.get("categories", []):
                for it in cat.get("items", []):
                    items.append({
                        "channel_item_id": str(it.get("id", "")),
                        "name": it.get("name", ""),
                        "channel_price": float(it.get("price", 0)),
                        "available": it.get("is_available", True),
                    })
        return {"channel": "GRABFOOD", "items": items}

    def verify_signature(self, payload: bytes, signature: str, secret: str) -> bool:
        """GrabFood webhook signature verification (HMAC-SHA256)."""
        if not secret:
            return False
        expected = hmac.new(secret.encode(), payload, hashlib.sha256).hexdigest()
        return hmac.compare_digest(expected, signature or "")
