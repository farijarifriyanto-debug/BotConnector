"""M6: deterministic simulated payment adapter.

Supports success / pending / failure / expired / duplicate callback / invalid
callback / amount mismatch. No real money, no real provider.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets

from parking.payment.adapters import (
    CallbackVerification,
    PaymentAdapter,
    PaymentInitiation,
)

_SIGNING_KEY = "simulator-test-key-not-for-production"


class SimulatedPaymentAdapter(PaymentAdapter):
    """Deterministic simulator for QRIS MPM / CPM and generic provider flows."""

    provider_name = "SIMULATOR"

    def __init__(self, signing_key: str = _SIGNING_KEY) -> None:
        self._signing_key = signing_key
        self._transactions: dict[str, dict] = {}

    def _sign(self, payload: dict) -> str:
        body = "&".join(f"{k}={v}" for k, v in sorted(payload.items()))
        return hmac.new(self._signing_key.encode(), body.encode(), hashlib.sha256).hexdigest()

    def initiate(self, *, amount: int, currency: str, reference: str, metadata: dict | None = None) -> PaymentInitiation:
        provider_reference = f"SIM-{secrets.token_hex(6).upper()}"
        self._transactions[provider_reference] = {
            "amount": amount,
            "currency": currency,
            "reference": reference,
            "status": "PENDING",
        }
        return PaymentInitiation(
            provider_reference=provider_reference,
            status="PENDING",
            payload={"qr_payload": f"000201010212SIMQR{provider_reference}",
                     "provider_reference": provider_reference},
        )

    def verify_callback_authenticity(self, raw: dict) -> bool:
        signature = raw.get("signature")
        if not signature:
            return False
        payload = {k: v for k, v in raw.items() if k != "signature"}
        return hmac.compare_digest(self._sign(payload), signature)

    def parse_callback(self, raw: dict) -> CallbackVerification:
        if not self.verify_callback_authenticity(raw):
            return CallbackVerification(valid=False, reason="INVALID_SIGNATURE")
        provider_reference = raw.get("provider_reference")
        if not provider_reference:
            return CallbackVerification(valid=False, reason="MISSING_REFERENCE")
        tx = self._transactions.get(provider_reference)
        if tx is None:
            return CallbackVerification(valid=False, reason="UNKNOWN_TRANSACTION")
        if raw.get("status") != "SUCCESS":
            return CallbackVerification(valid=False, reason="NOT_SUCCESS")
        return CallbackVerification(
            valid=True,
            provider_reference=provider_reference,
            amount=raw.get("amount"),
            currency=raw.get("currency"),
            status="SUCCESS",
        )

    def verify_transaction(self, provider_reference: str) -> CallbackVerification:
        tx = self._transactions.get(provider_reference)
        if tx is None:
            return CallbackVerification(valid=False, reason="UNKNOWN_TRANSACTION")
        return CallbackVerification(
            valid=True,
            provider_reference=provider_reference,
            amount=tx["amount"],
            currency=tx["currency"],
            status=tx["status"],
        )

    def mark_paid(self, provider_reference: str) -> None:
        if provider_reference in self._transactions:
            self._transactions[provider_reference]["status"] = "SUCCESS"

    def make_callback(self, *, provider_reference: str, amount: int, currency: str = "IDR",
                      status: str = "SUCCESS", tamper: bool = False) -> dict:
        payload = {
            "provider_reference": provider_reference,
            "amount": amount,
            "currency": currency,
            "status": status,
        }
        signature = self._sign(payload)
        if tamper:
            # Sign the original payload, then alter it so the signature no longer
            # matches -> invalid callback (bad signature).
            payload["amount"] = amount + 1
        payload["signature"] = signature
        return payload
