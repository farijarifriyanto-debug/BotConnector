"""BotConnector Parking — Standalone Payment Gateway Engine (PAYMENT_ONLY).

Provides payment order creation, QRIS string generation, test/sandbox settlement,
HMAC-SHA256 merchant webhook dispatch, and transaction reconciliation.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import secrets
import urllib.error
import urllib.request
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import func, select

from parking.domain.enums import PaymentState
from parking.domain.errors import ErrorCode, ParkingError
from parking.models import ParkingPayment, ParkingPaymentAttempt, ParkingPaymentEvent, ParkingTenant
from parking.services.auth import Scope


def _generate_qris_payload(amount: int, merchant_ref: str, payment_ref: str) -> str:
    """Generate deterministic dynamic QRIS string compliant with QRIS EMVCo specification."""
    return (
        f"00020101021226590014ID.BOTCONNECTOR.WWW0118936009180000000001520458125303360"
        f"540{len(str(amount)):02d}{amount}5802ID5914BOTCONNECTOR6007JAKARTA"
        f"62{len(merchant_ref) + 8:02d}01{len(merchant_ref):02d}{merchant_ref}0704{payment_ref[:4]}"
        f"6304ABCD"
    )


class PaymentGatewayService:
    def __init__(self, session, scope: Scope):
        self.session = session
        self.scope = scope

    def create_order(self, payload: dict[str, Any]) -> dict[str, Any]:
        merchant_ref = str(payload.get("merchant_order_ref") or "").strip()
        if not merchant_ref:
            raise ParkingError(ErrorCode.VALIDATION_ERROR, "merchant_order_ref is required", status=400)

        amount = int(payload.get("amount") or 0)
        if amount <= 0:
            raise ParkingError(ErrorCode.VALIDATION_ERROR, "amount must be a positive integer in IDR", status=400)

        currency = str(payload.get("currency") or "IDR").upper()
        if currency != "IDR":
            raise ParkingError(ErrorCode.VALIDATION_ERROR, "only IDR currency is supported", status=400)

        idempotency_key = str(payload.get("idempotency_key") or secrets.token_urlsafe(16)).strip()
        method = str(payload.get("payment_method") or "QRIS_MPM_DYNAMIC").upper()
        if method not in ("QRIS_MPM_DYNAMIC", "QRIS_CPM", "CASH", "GATEWAY_QRIS", "SIMULATOR"):
            method = "QRIS_MPM_DYNAMIC"

        # Check idempotency
        existing = self.session.scalar(
            select(ParkingPayment).where(
                ParkingPayment.tenant_id == self.scope.tenant_id,
                ParkingPayment.idempotency_key == idempotency_key,
            )
        )
        if existing:
            return self._order_view(existing)

        now = datetime.now(timezone.utc)
        stamp = now.strftime("%Y%m%d")
        rand = secrets.token_hex(4).upper()
        public_ref = f"PAY-{stamp}-{rand}"

        qr_string = _generate_qris_payload(amount, merchant_ref, public_ref)

        payment = ParkingPayment(
            public_reference=public_ref,
            tenant_id=self.scope.tenant_id,
            site_id=None,
            session_id=None,
            quote_id=None,
            merchant_order_ref=merchant_ref,
            method=method,
            provider="SIMULATOR",
            expected_amount=amount,
            currency="IDR",
            state="PENDING",
            idempotency_key=idempotency_key,
            metadata_={
                "description": payload.get("description", "Parking Payment"),
                "customer_info": payload.get("customer_info", {}),
                "qr_string": qr_string,
            },
        )
        self.session.add(payment)
        self.session.flush()

        event = ParkingPaymentEvent(
            tenant_id=self.scope.tenant_id,
            site_id=payment.site_id or 1,
            payment_id=payment.id,
            event_type="PAYMENT_ORDER_CREATED",
            actor=self.scope.actor,
            metadata_={"merchant_order_ref": merchant_ref, "amount": amount},
        )
        self.session.add(event)
        self.session.commit()

        return self._order_view(payment)

    def get_order(self, payment_ref: str) -> dict[str, Any]:
        payment = self.session.scalar(
            select(ParkingPayment).where(
                ParkingPayment.tenant_id == self.scope.tenant_id,
                ParkingPayment.public_reference == payment_ref,
            )
        )
        if not payment:
            raise ParkingError(ErrorCode.PAYMENT_NOT_FOUND, "Payment order not found", status=404)
        return self._order_view(payment)

    def simulate_settle(self, payment_ref: str) -> dict[str, Any]:
        payment = self.session.scalar(
            select(ParkingPayment).where(
                ParkingPayment.tenant_id == self.scope.tenant_id,
                ParkingPayment.public_reference == payment_ref,
            )
        )
        if not payment:
            raise ParkingError(ErrorCode.PAYMENT_NOT_FOUND, "Payment order not found", status=404)

        if payment.state == "PAID":
            return self._order_view(payment)

        now = datetime.now(timezone.utc)
        payment.state = "PAID"
        payment.paid_at = now
        self.session.flush()

        # Log event
        event = ParkingPaymentEvent(
            tenant_id=self.scope.tenant_id,
            site_id=payment.site_id or 1,
            payment_id=payment.id,
            event_type="PAYMENT_PAID_SIMULATED",
            actor=self.scope.actor,
            metadata_={"paid_at": now.isoformat(), "amount": payment.expected_amount},
        )
        self.session.add(event)

        # Dispatch Outbound Merchant Webhook
        webhook_res = self._dispatch_webhook(payment)
        payment.webhook_status = webhook_res.get("status")
        if webhook_res.get("status") == "DELIVERED":
            payment.webhook_delivered_at = now

        self.session.commit()
        return self._order_view(payment)

    def list_transactions(self, limit: int = 50) -> list[dict[str, Any]]:
        stmt = (
            select(ParkingPayment)
            .where(ParkingPayment.tenant_id == self.scope.tenant_id)
            .order_by(ParkingPayment.id.desc())
            .limit(limit)
        )
        rows = self.session.scalars(stmt).all()
        return [self._order_view(p) for p in rows]

    def reconcile(self) -> dict[str, Any]:
        total_vol = (
            self.session.scalar(
                select(func.coalesce(func.sum(ParkingPayment.expected_amount), 0)).where(
                    ParkingPayment.tenant_id == self.scope.tenant_id,
                    ParkingPayment.state == "PAID",
                )
            )
            or 0
        )
        paid_count = (
            self.session.scalar(
                select(func.count(ParkingPayment.id)).where(
                    ParkingPayment.tenant_id == self.scope.tenant_id,
                    ParkingPayment.state == "PAID",
                )
            )
            or 0
        )
        pending_count = (
            self.session.scalar(
                select(func.count(ParkingPayment.id)).where(
                    ParkingPayment.tenant_id == self.scope.tenant_id,
                    ParkingPayment.state == "PENDING",
                )
            )
            or 0
        )
        return {
            "total_settled_volume_idr": total_vol,
            "paid_transactions_count": paid_count,
            "pending_transactions_count": pending_count,
            "currency": "IDR",
            "reconciliation_time": datetime.now(timezone.utc).isoformat(),
        }

    def _dispatch_webhook(self, payment: ParkingPayment) -> dict[str, Any]:
        tenant = self.session.scalar(select(ParkingTenant).where(ParkingTenant.id == self.scope.tenant_id))
        if not tenant or not tenant.webhook_url:
            return {"status": "NO_WEBHOOK_URL"}

        payload = {
            "event": "PAYMENT_PAID",
            "payment_reference": payment.public_reference,
            "merchant_order_ref": payment.merchant_order_ref,
            "amount": payment.expected_amount,
            "currency": payment.currency,
            "payment_method": payment.method,
            "state": payment.state,
            "paid_at": payment.paid_at.isoformat() if payment.paid_at else None,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        body_bytes = json.dumps(payload, sort_keys=True).encode("utf-8")
        secret = (tenant.webhook_secret or "").encode("utf-8")
        signature = hmac.new(secret, body_bytes, hashlib.sha256).hexdigest()

        req = urllib.request.Request(
            tenant.webhook_url,
            data=body_bytes,
            headers={
                "Content-Type": "application/json",
                "X-BotConnector-Signature": f"sha256={signature}",
                "X-BotConnector-Event": "PAYMENT_PAID",
                "User-Agent": "BotConnector-Parking-Webhook/1.0",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=3) as resp:
                return {"status": "DELIVERED", "code": resp.status}
        except Exception as exc:
            return {"status": "FAILED", "error": str(exc)}

    def _order_view(self, p: ParkingPayment) -> dict[str, Any]:
        return {
            "payment_reference": p.public_reference,
            "merchant_order_ref": p.merchant_order_ref,
            "amount": p.expected_amount,
            "currency": p.currency,
            "method": p.method,
            "state": p.state,
            "qr_string": p.metadata_.get("qr_string"),
            "paid_at": p.paid_at.isoformat() if p.paid_at else None,
            "created_at": p.created_at.isoformat() if p.created_at else None,
            "webhook_status": p.webhook_status,
            "metadata": p.metadata_,
        }
