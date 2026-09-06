"""GoFood adapter (GoBiz Food Integration — Facilitator Model).

Based on CURRENT authoritative GoBiz docs (developer.gobiz.com):
  - OAuth2.0 auth (accounts.go-jek.com/oauth2/token)
  - scopes: openid, offline, partner:outlet:read/write, gofood:catalog:read/write,
    gofood:order:read/write, gofood:outlet:write
  - Link outlet: PUT /integrations/partner/outlets/{outlet_id}/v1/link/gofood
  - Get menu: GET /integrations/gofood/outlets/{outlet_id}/v2/catalog
  - Update menu: PUT /integrations/gofood/outlets/{outlet_id}/v1/catalog
  - Webhook notifications (order relayed to POS)
  - Webhook error event (mapping_not_found)

BotConnector models as a facilitator/POS integration, not a fake merchant.

REAL=BLOCKED_EXTERNAL until GoBiz partner credential/scope exists.
"""

from __future__ import annotations

import hashlib
import hmac
import json

from ..delivery_connector import DeliveryConnector

# Authoritative GoBiz endpoints (from developer.gobiz.com)
GOBIZ_OAUTH_URL = "https://accounts.go-jek.com/oauth2/token"
GOBIZ_SANDBOX_BASE = "https://api.partner-sandbox.gobiz.co.id"
GOBIZ_PROD_BASE = "https://api.partner.gobiz.co.id"

REQUIRED_SCOPES = [
    "openid", "offline",
    "partner:outlet:read", "partner:outlet:write",
    "gofood:catalog:read", "gofood:catalog:write",
    "gofood:order:read", "gofood:order:write",
    "gofood:outlet:write",
]


class GoFoodConnector(DeliveryConnector):
    provider = "GOFOOD"
    real_status = "BLOCKED_EXTERNAL"

    def __init__(self, base_url: str = GOBIZ_SANDBOX_BASE):
        self.base_url = base_url
        self.blocker = "GoBiz partner credential/scope belum tersedia (REAL=BLOCKED_EXTERNAL)"

    def status_report(self) -> dict:
        return {
            "provider": self.provider,
            "real_status": self.real_status,
            "readiness": "blocked_external",
            "blocker": self.blocker,
            "auth": "oauth2",
            "required_scopes": REQUIRED_SCOPES,
            "endpoints": {
                "oauth": GOBIZ_OAUTH_URL,
                "link_outlet": f"{self.base_url}/integrations/partner/outlets/{{outlet_id}}/v1/link/gofood",
                "get_menu": f"{self.base_url}/integrations/gofood/outlets/{{outlet_id}}/v2/catalog",
                "update_menu": f"{self.base_url}/integrations/gofood/outlets/{{outlet_id}}/v1/catalog",
            },
        }

    def normalize_order(self, raw: dict) -> dict:
        """Normalize a GoFood order webhook payload into canonical fields."""
        body = raw.get("body", raw)
        order = body.get("order", {})
        outlet = body.get("outlet", {})
        items = order.get("items", [])
        lines = []
        for it in items:
            lines.append({
                "channel_item_id": str(it.get("id", "")),
                "name": it.get("name", ""),
                "quantity": int(it.get("quantity", 0)),
                "unit_price": float(it.get("price", 0)),
                "modifiers": it.get("variants", []),
            })
        return {
            "source_provider": "GOFOOD",
            "external_order_id": str(order.get("number", "")),
            "outlet_id": str(outlet.get("id", "")),
            "order_type": "DELIVERY",
            "lines": lines,
            "gross_value": float(order.get("total", 0)),
            "discount": float(order.get("discount", 0)),
            "payment_state": "UNPAID",
            "provider_status": str(order.get("status", "")),
            "raw_payload": raw,
        }

    def normalize_menu(self, raw: dict) -> dict:
        """Normalize GoFood catalog into canonical channel_menu_mapping fields."""
        items = []
        for cat in raw.get("categories", []):
            for it in cat.get("items", []):
                items.append({
                    "channel_item_id": str(it.get("id", "")),
                    "name": it.get("name", ""),
                    "channel_price": float(it.get("price", 0)),
                    "available": it.get("is_available", True),
                })
        return {"channel": "GOFOOD", "items": items}

    def verify_signature(self, payload: bytes, signature: str, secret: str) -> bool:
        """GoBiz webhook signature verification (HMAC-SHA256)."""
        if not secret:
            return False
        expected = hmac.new(secret.encode(), payload, hashlib.sha256).hexdigest()
        return hmac.compare_digest(expected, signature or "")
