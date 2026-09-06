"""M5: Exit Runtime — authoritative exit quote, payment requirement, exit
authorization and completion. No physical barrier is driven; exit produces a
barrier OPEN INTENT that a future BarrierAdapter consumes.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from parking.domain.enums import (
    BarrierAction,
    EventType,
    ExitQuoteStatus,
    GateDirection,
    LaneDirection,
    PaymentState,
    SessionState,
)
from parking.domain.errors import ErrorCode, ParkingError
from parking.exit.quote_repo import ExitQuoteRepository
from parking.models import ParkingExitQuote, ParkingSession
from parking.repositories.registry import GateRepository, LaneRepository
from parking.repositories.session_repo import SessionRepository
from parking.services.auth import Scope
from parking.services.tariff_service import TariffService

QUOTE_TTL_MINUTES = 5


@dataclass(frozen=True)
class ExitQuoteResult:
    quote: ParkingExitQuote
    amount: int
    currency: str
    expires_at: datetime
    status: str


@dataclass(frozen=True)
class ExitDecision:
    allowed: bool
    reason: str
    barrier_action: str
    quote: ParkingExitQuote | None = None
    details: dict = field(default_factory=dict)


class ExitRuntimeService:
    def __init__(self, session, scope: Scope):
        self.session = session
        self.scope = scope
        self.tenant_id = scope.tenant_id
        self.repo = SessionRepository(session, scope.tenant_id)
        self.quotes = ExitQuoteRepository(session, scope.tenant_id)
        self.tariff = TariffService(session, scope)

    def _session(self, public_reference: str) -> ParkingSession:
        return self.repo.get_by_public_reference(public_reference)

    def create_exit_quote(self, public_reference: str, *, now: datetime | None = None) -> ExitQuoteResult:
        """Authoritative server-side tariff quote. Amount always from the engine."""
        session = self._session(public_reference)
        if session.state in (SessionState.CLOSED.value, SessionState.CANCELLED.value):
            raise ParkingError(
                ErrorCode.EXIT_NOT_ALLOWED, f"session is {session.state}, cannot quote exit", status=409
            )
        at = now or datetime.now(timezone.utc)

        # Supersede any prior active quote for this session.
        prior = self.quotes.get_active_for_session(session.id)
        if prior is not None:
            self.quotes.set_status(prior, ExitQuoteStatus.SUPERSEDED.value)

        calc = self.tariff.calculate(session, at)
        expires_at = at + timedelta(minutes=QUOTE_TTL_MINUTES)
        quote = self.quotes.create(
            site_id=session.site_id,
            session_id=session.id,
            tariff_version=calc["plan"]["version"],
            tariff_snapshot=calc["snapshot"],
            entry_at=session.entry_at,
            calculated_at=at,
            amount=calc["amount"],
            currency=calc["currency"],
            expires_at=expires_at,
        )
        self.repo.add_event(
            session.tenant_id, session.site_id, session.id, EventType.EXIT_QUOTE_CREATED.value,
            self.scope.actor, {"quote_reference": quote.public_reference, "amount": calc["amount"]},
        )
        self.session.commit()
        self.session.refresh(quote)
        return ExitQuoteResult(quote=quote, amount=calc["amount"], currency=calc["currency"],
                               expires_at=expires_at, status=quote.status)

    def _active_quote(self, session: ParkingSession, *, now: datetime | None = None) -> ParkingExitQuote:
        at = now or datetime.now(timezone.utc)
        quote = self.quotes.get_active_for_session(session.id)
        if quote is None:
            raise ParkingError(ErrorCode.PAYMENT_REQUIRED, "no active exit quote; create one first", status=409)
        if quote.expires_at <= at:
            self.quotes.set_status(quote, ExitQuoteStatus.EXPIRED.value)
            self.repo.add_event(
                session.tenant_id, session.site_id, session.id, EventType.EXIT_QUOTE_EXPIRED.value,
                self.scope.actor, {"quote_reference": quote.public_reference},
            )
            self.session.commit()
            raise ParkingError(ErrorCode.QUOTE_EXPIRED, "exit quote expired; recalculate", status=409)
        return quote

    def exit_decision(self, public_reference: str, *, now: datetime | None = None) -> ExitDecision:
        """Determine whether exit is authorized. If payment is not satisfied,
        returns PAYMENT_REQUIRED (not an error) so the caller can route to payment."""
        session = self._session(public_reference)
        if session.state == SessionState.EXIT_AUTHORIZED.value:
            return ExitDecision(allowed=True, reason="EXIT_AUTHORIZED",
                                barrier_action=BarrierAction.OPEN_BARRIER.value, details={"state": session.state})
        if session.state == SessionState.CLOSED.value:
            return ExitDecision(allowed=False, reason="SESSION_CLOSED",
                                barrier_action=BarrierAction.KEEP_CLOSED.value, details={"state": session.state})
        if session.payment_state in (PaymentState.PAID.value, PaymentState.COMPLIMENTARY.value):
            return ExitDecision(allowed=True, reason="PAYMENT_SATISFIED",
                                barrier_action=BarrierAction.OPEN_BARRIER.value, details={"state": session.state})
        # Payment required.
        quote = self._active_quote(session, now=now)
        return ExitDecision(allowed=False, reason="PAYMENT_REQUIRED",
                            barrier_action=BarrierAction.KEEP_CLOSED.value,
                            details={"state": session.state, "quote_reference": quote.public_reference})

    def authorize_exit(self, public_reference: str, *, now: datetime | None = None) -> ParkingSession:
        """Server-side exit authorization. Only valid after payment is satisfied."""
        session = self._session(public_reference)
        if session.state == SessionState.EXIT_AUTHORIZED.value:
            return session  # idempotent
        if session.state in (SessionState.CLOSED.value, SessionState.CANCELLED.value):
            raise ParkingError(ErrorCode.EXIT_NOT_ALLOWED, f"session is {session.state}", status=409)
        if session.payment_state not in (PaymentState.PAID.value, PaymentState.COMPLIMENTARY.value):
            raise ParkingError(ErrorCode.PAYMENT_REQUIRED, "payment not satisfied; cannot authorize exit", status=409)
        self.repo.update_state(session, SessionState.EXIT_AUTHORIZED.value, self.scope.actor)
        self.repo.add_event(
            session.tenant_id, session.site_id, session.id, EventType.EXIT_AUTHORIZED.value,
            self.scope.actor, {"barrier_action": BarrierAction.OPEN_BARRIER.value},
        )
        self.session.commit()
        self.session.refresh(session)
        return session

    def record_vehicle_exited(
        self,
        public_reference: str,
        *,
        exit_gate_id: int,
        exit_lane_id: int,
        exit_at: datetime | None = None,
    ) -> ParkingSession:
        """Record the vehicle physically exiting and close the session. Idempotent."""
        session = self._session(public_reference)
        if session.state == SessionState.CLOSED.value:
            return session  # already closed
        if session.state != SessionState.EXIT_AUTHORIZED.value:
            raise ParkingError(
                ErrorCode.EXIT_NOT_ALLOWED, f"cannot record exit from state {session.state}", status=409
            )
        tenant_id = self.tenant_id
        gate = GateRepository(self.session, tenant_id).get(session.site_id, exit_gate_id)
        if gate.direction not in (GateDirection.EXIT.value, GateDirection.BIDIRECTIONAL.value):
            raise ParkingError(ErrorCode.INVALID_GATE_DIRECTION, f"gate {gate.code} is not an exit gate", status=422)
        lane = LaneRepository(self.session, tenant_id).get(session.site_id, exit_gate_id, exit_lane_id)
        if lane.direction not in (LaneDirection.EXIT.value, LaneDirection.BIDIRECTIONAL.value):
            raise ParkingError(ErrorCode.INVALID_LANE, f"lane {lane.code} is not an exit lane", status=422)
        at = exit_at or datetime.now(timezone.utc)
        session.exit_gate_id = exit_gate_id
        session.exit_lane_id = exit_lane_id
        session.exit_at = at
        self.repo.update_state(session, SessionState.EXITED.value, self.scope.actor)
        self.repo.add_event(
            session.tenant_id, session.site_id, session.id, EventType.VEHICLE_EXITED.value,
            self.scope.actor, {"exit_gate_id": exit_gate_id, "exit_lane_id": exit_lane_id, "exit_at": at.isoformat()},
        )
        self.repo.update_state(session, SessionState.CLOSED.value, self.scope.actor)
        self.repo.add_event(
            session.tenant_id, session.site_id, session.id, EventType.SESSION_CLOSED.value,
            self.scope.actor, {},
        )
        self.session.commit()
        self.session.refresh(session)
        return session
