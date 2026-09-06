"""M6: Payment Runtime — provider-neutral payment orchestration.

Amount authority always comes from the authoritative exit quote. Payment
fulfillment is based on trusted backend verification, never on a client-supplied
amount or a bare callback JSON.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone

from parking.domain.enums import (
    EventType,
    ExitQuoteStatus,
    PaymentEntityState,
    PaymentMethod,
    PaymentProvider,
    PaymentState,
    SessionState,
)
from parking.domain.errors import ErrorCode, ParkingError
from parking.exit.quote_repo import ExitQuoteRepository
from parking.models import ParkingPayment, ParkingSession
from parking.payment.adapters import PaymentAdapter
from parking.payment.repo import PaymentRepository
from parking.payment.simulator import SimulatedPaymentAdapter
from parking.repositories.session_repo import SessionRepository
from parking.services.auth import Scope


@dataclass(frozen=True)
class PaymentResult:
    payment: ParkingPayment
    state: str
    provider_reference: str | None = None
    payload: dict = field(default_factory=dict)


class PaymentService:
    def __init__(self, session, scope: Scope, adapter: PaymentAdapter | None = None):
        self.session = session
        self.scope = scope
        self.tenant_id = scope.tenant_id
        self.repo = PaymentRepository(session, scope.tenant_id)
        self.quotes = ExitQuoteRepository(session, scope.tenant_id)
        self.sessions = SessionRepository(session, scope.tenant_id)
        self.adapter = adapter or SimulatedPaymentAdapter()

    def _session(self, public_reference: str) -> ParkingSession:
        return self.sessions.get_by_public_reference(public_reference)

    def _active_quote(self, session: ParkingSession, *, now: datetime | None = None) -> object:
        at = now or datetime.now(timezone.utc)
        quote = self.quotes.get_active_for_session(session.id)
        if quote is None:
            raise ParkingError(ErrorCode.PAYMENT_REQUIRED, "no active exit quote; create one first", status=409)
        if quote.expires_at <= at:
            self.quotes.set_status(quote, ExitQuoteStatus.EXPIRED.value)
            self.session.commit()
            raise ParkingError(ErrorCode.QUOTE_EXPIRED, "exit quote expired; recalculate", status=409)
        return quote

    def create_payment(
        self,
        *,
        session_reference: str,
        method: str,
        idempotency_key: str,
        now: datetime | None = None,
    ) -> PaymentResult:
        """Create a payment against the authoritative active quote. Idempotent by key."""
        session = self._session(session_reference)
        if session.payment_state in (PaymentState.PAID.value, PaymentState.COMPLIMENTARY.value):
            raise ParkingError(ErrorCode.PAYMENT_ALREADY_SETTLED, "session already settled", status=409)
        quote = self._active_quote(session, now=now)

        # Idempotency: same key returns the same logical payment.
        existing = self.repo.get_by_idempotency_key(idempotency_key)
        if existing is not None:
            return PaymentResult(payment=existing, state=existing.state,
                                 provider_reference=existing.provider_reference)

        provider = self._provider_for(method)
        payment = self.repo.create(
            site_id=session.site_id,
            session_id=session.id,
            quote_id=quote.id,
            method=method,
            provider=provider,
            expected_amount=quote.amount,
            currency=quote.currency,
            idempotency_key=idempotency_key,
        )
        self.repo.add_event(payment, "PAYMENT_CREATED", self.scope.actor, {"method": method, "amount": quote.amount})

        # Initiate with provider (QRIS generates dynamic QR; cash/complimentary skip).
        if method in (PaymentMethod.QRIS_MPM_DYNAMIC.value, PaymentMethod.QRIS_CPM.value):
            init = self.adapter.initiate(
                amount=quote.amount, currency=quote.currency, reference=payment.public_reference
            )
            payment.provider_reference = init.provider_reference
            self.repo.add_attempt(payment=payment, provider=provider,
                                  provider_reference=init.provider_reference, state="PENDING")
            self.repo.set_state(payment, PaymentEntityState.PENDING.value)
            self.repo.add_event(payment, "PAYMENT_PENDING", self.scope.actor,
                                {"provider_reference": init.provider_reference})
            self.session.commit()
            self.session.refresh(payment)
            return PaymentResult(payment=payment, state=payment.state,
                                 provider_reference=init.provider_reference, payload=init.payload)

        # CASH / COMPLIMENTARY stay CREATED until confirmed.
        self.session.commit()
        self.session.refresh(payment)
        return PaymentResult(payment=payment, state=payment.state)

    def _provider_for(self, method: str) -> str:
        if method == PaymentMethod.CASH.value:
            return PaymentProvider.CASH.value
        if method == PaymentMethod.COMPLIMENTARY.value:
            return PaymentProvider.COMPLIMENTARY.value
        return PaymentProvider.SIMULATOR.value

    def confirm_cash(self, payment_reference: str, *, actor: str | None = None) -> PaymentResult:
        """Operator-confirmed cash receipt. Only authorized operator context may
        confirm; the actor is server-derived, never client-supplied."""
        payment = self.repo.get_by_public_reference(payment_reference)
        if payment.state == PaymentEntityState.PAID.value:
            return PaymentResult(payment=payment, state=payment.state)  # idempotent
        if payment.method != PaymentMethod.CASH.value:
            raise ParkingError(ErrorCode.PAYMENT_NOT_VERIFIED, "payment is not a cash payment", status=409)
        if payment.state not in (PaymentEntityState.CREATED.value, PaymentEntityState.PENDING.value):
            raise ParkingError(ErrorCode.PAYMENT_ALREADY_SETTLED, f"payment state {payment.state}", status=409)
        self._settle(payment, actor=actor or self.scope.actor)
        return PaymentResult(payment=payment, state=payment.state)

    def apply_complimentary(self, payment_reference: str, *, reason: str, actor: str | None = None) -> PaymentResult:
        """Explicit audited complimentary settlement (not a fake zero cash payment)."""
        payment = self.repo.get_by_public_reference(payment_reference)
        if payment.state == PaymentEntityState.PAID.value:
            return PaymentResult(payment=payment, state=payment.state)
        if payment.method != PaymentMethod.COMPLIMENTARY.value:
            raise ParkingError(ErrorCode.PAYMENT_NOT_VERIFIED, "payment is not complimentary", status=409)
        if payment.state not in (PaymentEntityState.CREATED.value, PaymentEntityState.PENDING.value):
            raise ParkingError(ErrorCode.PAYMENT_ALREADY_SETTLED, f"payment state {payment.state}", status=409)
        self._settle(payment, actor=actor or self.scope.actor, complimentary=True, reason=reason)
        return PaymentResult(payment=payment, state=payment.state)

    def handle_callback(self, provider: str, raw: dict) -> PaymentResult:
        """Process a provider callback with full verification. Idempotent and
        replay-safe. Never marks PAID solely because the callback JSON says so."""
        # Authenticity first.
        if not self.adapter.verify_callback_authenticity(raw):
            raise ParkingError(ErrorCode.PAYMENT_CALLBACK_INVALID, "callback signature invalid", status=401)
        parsed = self.adapter.parse_callback(raw)
        if not parsed.valid:
            raise ParkingError(ErrorCode.PAYMENT_CALLBACK_INVALID, f"callback invalid: {parsed.reason}", status=400)
        provider_reference = parsed.provider_reference
        assert provider_reference is not None

        # Locate the internal payment by provider reference.
        payment = self._find_by_provider_reference(provider_reference)
        if payment is None:
            raise ParkingError(ErrorCode.PAYMENT_NOT_FOUND, "no payment for provider reference", status=404)

        # Replay protection: already PAID -> safe no-op.
        if payment.state == PaymentEntityState.PAID.value:
            self.repo.add_event(payment, "PAYMENT_CALLBACK_REPLAY_IGNORED", self.scope.actor,
                                {"provider_reference": provider_reference})
            self.session.commit()
            return PaymentResult(payment=payment, state=payment.state)

        # Server-to-server verification.
        verified = self.adapter.verify_transaction(provider_reference)
        if not verified.valid:
            raise ParkingError(ErrorCode.PAYMENT_NOT_VERIFIED, "server-side verification failed", status=400)

        # Amount + currency matching against the authoritative quote. Check both
        # the parsed callback amount and the server-verified amount.
        for label, amount in (("callback", parsed.amount), ("verified", verified.amount)):
            if amount != payment.expected_amount:
                raise ParkingError(
                    ErrorCode.PAYMENT_AMOUNT_MISMATCH,
                    f"amount mismatch ({label}): expected {payment.expected_amount}, got {amount}",
                    status=409,
                )
        for label, currency in (("callback", parsed.currency), ("verified", verified.currency)):
            if currency != payment.currency:
                raise ParkingError(ErrorCode.PAYMENT_AMOUNT_MISMATCH, f"currency mismatch ({label})", status=409)

        self.repo.add_event(payment, "PAYMENT_CALLBACK_RECEIVED", self.scope.actor,
                            {"provider_reference": provider_reference})
        self._settle(payment, actor=self.scope.actor)
        return PaymentResult(payment=payment, state=payment.state)

    def _find_by_provider_reference(self, provider_reference: str) -> ParkingPayment | None:
        from sqlalchemy import select
        from parking.models import ParkingPayment
        return self.session.scalar(
            select(ParkingPayment).where(
                ParkingPayment.tenant_id == self.tenant_id,
                ParkingPayment.provider_reference == provider_reference,
            )
        )

    def _settle(self, payment: ParkingPayment, *, actor: str, complimentary: bool = False, reason: str | None = None) -> None:
        """Transactional settlement: payment PAID -> quote PAID -> session
        payment_state PAID/COMPLIMENTARY. All in one transaction."""
        session = self.sessions.get_by_id(payment.session_id)
        quote = self.quotes.get(payment.quote_id)

        # Mark payment PAID.
        self.repo.set_state(payment, PaymentEntityState.PAID.value, paid_at=datetime.now(timezone.utc))
        self.repo.add_event(payment, "PAYMENT_VERIFIED", actor, {"amount": payment.expected_amount})
        self.repo.add_event(payment, "PAYMENT_PAID", actor, {"amount": payment.expected_amount})

        # Mark quote PAID.
        self.quotes.set_status(quote, ExitQuoteStatus.PAID.value)
        self.sessions.add_event(
            session.tenant_id, session.site_id, session.id, EventType.EXIT_QUOTE_PAID.value,
            actor, {"quote_reference": quote.public_reference},
        )

        # Settle the session payment state.
        if complimentary:
            session.payment_state = PaymentState.COMPLIMENTARY.value
            session.paid_amount = 0
            self.sessions.add_event(
                session.tenant_id, session.site_id, session.id, EventType.COMPLIMENTARY_APPLIED.value,
                actor, {"original_amount": payment.expected_amount, "final_amount": 0, "reason": reason},
            )
        else:
            session.payment_state = PaymentState.PAID.value
            session.paid_amount = payment.expected_amount
            self.sessions.add_event(
                session.tenant_id, session.site_id, session.id, EventType.PAYMENT_MARKED_PAID.value,
                actor, {"amount": payment.expected_amount},
            )
        # Advance the session state machine to PAID (PARKED -> PAYMENT_PENDING -> PAID).
        if session.state in (SessionState.PARKED.value, SessionState.LOST_TICKET.value, SessionState.MANUAL_REVIEW.value):
            self.sessions.update_state(session, SessionState.PAYMENT_PENDING.value, actor)
        if session.state == SessionState.PAYMENT_PENDING.value:
            self.sessions.update_state(session, SessionState.PAID.value, actor)
        # Audit the settlement (operator, amount, time, site, session, payment).
        self.sessions.add_audit(
            tenant_id=session.tenant_id, site_id=session.site_id, actor=actor,
            action="payment.settled", object_type="parking_payment",
            object_id=payment.public_reference,
            details={"method": payment.method, "amount": payment.expected_amount,
                     "session": session.public_reference, "complimentary": complimentary, "reason": reason},
        )
        self.session.flush()
        self.session.commit()
        self.session.refresh(payment)
