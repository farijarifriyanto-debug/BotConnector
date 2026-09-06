"""Moka POS adapter (GoBiz/MokaPOS).

Based on current official GoBiz/MokaPOS reporting concepts: outlet, item/
category sales, gross sales, net sales, refund, discount, item sold, COGS,
gross profit, customers (when permission exists).

Real API status depends on actual credential/scopes. If absent:
MOKA_REAL=BLOCKED_EXTERNAL. Provider-shaped fixture/contract tests may PASS
as adapter implementation, but never reported as REAL API PASS.
"""

from __future__ import annotations

from ..pos_connector import PosConnector


class MokaConnector(PosConnector):
    provider = "MOKA"
    real_status = "BLOCKED_EXTERNAL"

    def __init__(self):
        self.blocker = "Moka/GoBiz credential belum tersedia (MOKA_REAL=BLOCKED_EXTERNAL)"

    def status_report(self) -> dict:
        return {
            "provider": self.provider,
            "real_status": self.real_status,
            "readiness": "blocked_external",
            "blocker": self.blocker,
            "auth": "oauth2",
            "capabilities": ["outlet", "item_sales", "gross_sales", "net_sales",
                             "refund", "discount", "item_sold", "cogs",
                             "gross_profit", "customers"],
        }

    def normalize_sales(self, raw: dict) -> dict:
        """Normalize a Moka transaction/report into canonical sale fields."""
        txn = raw.get("transaction", raw)
        items = txn.get("items", [])
        lines = []
        for it in items:
            lines.append({
                "master_sku_id": it.get("master_sku_id"),
                "sku": it.get("sku", ""),
                "name": it.get("name", ""),
                "quantity": int(it.get("quantity", 0)),
                "unit_price": float(it.get("unit_price", 0)),
                "discount": float(it.get("discount", 0)),
                "cost": float(it.get("cost", 0)),
            })
        return {
            "source_provider": "MOKA",
            "external_order_id": str(txn.get("id", "")),
            "external_transaction_id": str(txn.get("transaction_id", "")),
            "outlet_id": str(txn.get("outlet_id", "")),
            "lines": lines,
            "gross_value": float(txn.get("gross_total", 0)),
            "net_value": float(txn.get("net_total", 0)),
            "discount": float(txn.get("discount", 0)),
            "refund": float(txn.get("refund", 0)),
            "payment_method": txn.get("payment_method", ""),
            "raw_payload": raw,
        }

    def normalize_product(self, raw: dict) -> dict:
        """Normalize a Moka product/item into canonical product fields."""
        return {
            "sku": raw.get("sku", ""),
            "name": raw.get("name", ""),
            "category": raw.get("category", ""),
            "price": float(raw.get("price", 0)),
            "cost": float(raw.get("cost", 0)),
            "barcode": raw.get("barcode", ""),
        }
