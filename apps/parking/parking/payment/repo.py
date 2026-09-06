"""M6: payment repository (tenant-scoped)."""

from __future__ import annotations

import secrets
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from parking.domain.errors import ErrorCode, ParkingError
from parking.domain.enums import PaymentEntityState
from parking.models import (
    ParkingPayment,
    ParkingPaymentAttempt,
    ParkingPaymentEvent,
)
from parking.repositories.base import ScopedRepository


def make_payment_reference() -> str:
    return f"PAY-{secrets.token_hex(5).upper()}"


class PaymentRepository(ScopedRepository):
    def create(
        self,
        *,
        site_id: int,
        session_id: int,
        quote_id: int,
        method: str,
        provider: str,
        expected_amount: int,
        currency: str,
        idempotency_key: str,
        metadata: dict | None = None,
    ) -> ParkingPayment:
        payment = ParkingPayment(
            public_reference=make_payment_reference(),
            tenant_id=self.tenant_id,
            site_id=site_id,
            session_id=session_id,
            quote_id=quote_id,
            method=method,
            provider=provider,
            expected_amount=expected_amount,
            currency=currency,
            state=PaymentEntityState.CREATED.value,
            idempotency_key=idempotency_key,
            metadata_=metadata or {},
        )
        self.session.add(payment)
        try:
            self.session.flush()
        except IntegrityError as exc:
            if getattr(exc.orig, "sqlstate", None) == "23505":
                raise ParkingError(
                    ErrorCode.PAYMENT_ALREADY_SETTLED,
                    "payment idempotency key already used",
                    status=409,
                )
            raise
        return payment

    def get(self, payment_id: int) -> ParkingPayment:
        payment = self.session.scalar(
            select(ParkingPayment).where(
                ParkingPayment.id == payment_id, ParkingPayment.tenant_id == self.tenant_id
            )
        )
        if payment is None:
            raise ParkingError(ErrorCode.PAYMENT_NOT_FOUND, "payment not found", status=404)
        return payment

    def get_by_public_reference(self, public_reference: str) -> ParkingPayment:
        payment = self.session.scalar(
            select(ParkingPayment).where(
                ParkingPayment.public_reference == public_reference,
                ParkingPayment.tenant_id == self.tenant_id,
            )
        )
        if payment is None:
            raise ParkingError(ErrorCode.PAYMENT_NOT_FOUND, "payment not found", status=404)
        return payment

    def get_by_idempotency_key(self, idempotency_key: str) -> ParkingPayment | None:
        return self.session.scalar(
            select(ParkingPayment).where(
                ParkingPayment.tenant_id == self.tenant_id,
                ParkingPayment.idempotency_key == idempotency_key,
            )
        )

    def set_state(self, payment: ParkingPayment, state: str, *, paid_at: datetime | None = None) -> ParkingPayment:
        payment.state = state
        if paid_at is not None:
            payment.paid_at = paid_at
        self.session.flush()
        return payment

    def add_event(
        self,
        payment: ParkingPayment,
        event_type: str,
        actor: str | None,
        metadata: dict | None = None,
    ) -> ParkingPaymentEvent:
        event = ParkingPaymentEvent(
            tenant_id=payment.tenant_id,
            site_id=payment.site_id,
            payment_id=payment.id,
            event_type=event_type,
            actor=actor,
            metadata_=metadata or {},
        )
        self.session.add(event)
        self.session.flush()
        return event

    def add_attempt(
        self,
        *,
        payment: ParkingPayment,
        provider: str,
        provider_reference: str | None = None,
        state: str = "CREATED",
        metadata: dict | None = None,
    ) -> ParkingPaymentAttempt:
        attempt = ParkingPaymentAttempt(
            tenant_id=payment.tenant_id,
            site_id=payment.site_id,
            payment_id=payment.id,
            provider=provider,
            provider_reference=provider_reference,
            state=state,
            metadata_=metadata or {},
        )
        self.session.add(attempt)
        self.session.flush()
        return attempt
