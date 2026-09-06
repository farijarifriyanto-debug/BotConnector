"""Pawoon POS adapter.

Pawoon publicly advertises Open API through its dashboard. Native adapter
only for capabilities verified against current official information. If actual
API credentials/account access are absent: PAWOON_REAL=BLOCKED_EXTERNAL.
Also supports Pawoon export files through Universal File Connector.
"""

from __future__ import annotations

from ..pos_connector import PosConnector


class PawoonConnector(PosConnector):
    provider = "PAWOON"
    real_status = "BLOCKED_EXTERNAL"

    def __init__(self):
        self.blocker = "Pawoon Open API credential belum tersedia (PAWOON_REAL=BLOCKED_EXTERNAL)"

    def status_report(self) -> dict:
        return {
            "provider": self.provider,
            "real_status": self.real_status,
            "readiness": "blocked_external",
            "blocker": self.blocker,
            "auth": "api_key",
            "capabilities": ["outlet", "item_sales", "gross_sales", "net_sales",
                             "refund", "discount", "item_sold", "cogs",
                             "gross_profit", "customers"],
            "file_export": True,  # Pawoon export files via Universal File Connector
        }

    def normalize_sales(self, raw: dict) -> dict:
        """Normalize a Pawoon transaction/report into canonical sale fields."""
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
            "source_provider": "PAWOON",
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
        """Normalize a Pawoon product/item into canonical product fields."""
        return {
            "sku": raw.get("sku", ""),
            "name": raw.get("name", ""),
            "category": raw.get("category", ""),
            "price": float(raw.get("price", 0)),
            "cost": float(raw.get("cost", 0)),
            "barcode": raw.get("barcode", ""),
        }
