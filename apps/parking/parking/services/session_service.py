"""Controlled session lifecycle commands (M2).

There is no generic PATCH: every state change goes through a named command
that validates the transition server-side and writes event + audit records.
"""

from __future__ import annotations

from datetime import datetime, timezone

from parking.domain.enums import (
    EventType,
    GateDirection,
    LaneDirection,
    PaymentState,
    SessionState,
)
from parking.domain.errors import ErrorCode, ParkingError
from parking.domain.state_machine import assert_payment_transition
from parking.models import ParkingSession
from parking.repositories.registry import GateRepository, LaneRepository
from parking.repositories.session_repo import SessionRepository
from parking.services.auth import Scope
from parking.services.tariff_service import TariffService


class SessionService:
    def __init__(self, session, scope: Scope):
        self.session = session
        self.scope = scope
        self.repo = SessionRepository(session, scope.tenant_id)
        self.tariff = TariffService(session, scope)

    # ---- read / list -----------------------------------------------------
    def get(self, public_reference: str) -> ParkingSession:
        return self.repo.get_by_public_reference(public_reference)

    def list_active(self, site_id: int | None = None) -> list[ParkingSession]:
        return self.repo.list_active(site_id)

    def list_events(self, session: ParkingSession) -> list:
        return self.repo.list_events(session.id)

    # ---- tariff / payment flow ------------------------------------------
    def calculate(self, public_reference: str, calculation_at: datetime | None = None) -> dict:
        session = self.repo.get_by_public_reference(public_reference)
        if session.state in (SessionState.CLOSED.value, SessionState.CANCELLED.value) or session.payment_state in (
            PaymentState.PAID.value,
            PaymentState.COMPLIMENTARY.value,
        ):
            raise ParkingError(
                ErrorCode.INVALID_SESSION_STATE, f"cannot calculate a finalized session (state={session.state})", status=409
            )
        return self.tariff.calculate(session, calculation_at)

    def initiate_payment(self, public_reference: str) -> ParkingSession:
        session = self.repo.get_by_public_reference(public_reference)
        if session.state not in (
            SessionState.PARKED.value,
            SessionState.LOST_TICKET.value,
            SessionState.MANUAL_REVIEW.value,
        ):
            raise ParkingError(
                ErrorCode.INVALID_SESSION_STATE,
                f"cannot initiate payment from state {session.state}",
                status=409,
            )
        if session.calculated_amount == 0 or not session.tariff_snapshot:
            self.tariff.calculate(session)
        assert_payment_transition(session.payment_state, PaymentState.PENDING.value)
        session.payment_state = PaymentState.PENDING.value
        self.repo.update_state(session, SessionState.PAYMENT_PENDING.value, self.scope.actor)
        self.session.commit()
        self.session.refresh(session)
        return session

    def confirm_payment(self, public_reference: str) -> ParkingSession:
        session = self.repo.get_by_public_reference(public_reference)
        if session.state != SessionState.PAYMENT_PENDING.value:
            raise ParkingError(
                ErrorCode.INVALID_SESSION_STATE,
                f"cannot confirm payment from state {session.state}",
                status=409,
            )
        assert_payment_transition(session.payment_state, PaymentState.PAID.value)
        amount = session.calculated_amount or 0
        session.payment_state = PaymentState.PAID.value
        session.paid_amount = amount
        self.repo.update_state(session, SessionState.PAID.value, self.scope.actor)
        self.repo.add_event(
            session.tenant_id,
            session.site_id,
            session.id,
            EventType.PAYMENT_MARKED_PAID.value,
            self.scope.actor,
            {"amount": amount, "payment_state": session.payment_state},
        )
        self.session.commit()
        self.session.refresh(session)
        return session

    # ---- exit flow ---------------------------------------------------------
    def authorize_exit(self, public_reference: str) -> ParkingSession:
        session = self.repo.get_by_public_reference(public_reference)
        if session.state != SessionState.PAID.value:
            raise ParkingError(
                ErrorCode.INVALID_SESSION_STATE,
                f"cannot authorize exit from state {session.state} (must be PAID)",
                status=409,
            )
        self.repo.update_state(session, SessionState.EXIT_AUTHORIZED.value, self.scope.actor)
        self.repo.add_event(
            session.tenant_id,
            session.site_id,
            session.id,
            EventType.EXIT_AUTHORIZED.value,
            self.scope.actor,
            {},
        )
        self.session.commit()
        self.session.refresh(session)
        return session

    def process_exit(
        self,
        public_reference: str,
        *,
        exit_gate_id: int,
        exit_lane_id: int,
        exit_at: datetime | None = None,
    ) -> ParkingSession:
        session = self.repo.get_by_public_reference(public_reference)
        if session.state != SessionState.EXIT_AUTHORIZED.value:
            raise ParkingError(
                ErrorCode.INVALID_SESSION_STATE,
                f"cannot process exit from state {session.state} (must be EXIT_AUTHORIZED)",
                status=409,
            )
        tenant_id = self.scope.tenant_id
        gate = GateRepository(self.session, tenant_id).get(session.site_id, exit_gate_id)
        if gate.direction not in (GateDirection.EXIT.value, GateDirection.BIDIRECTIONAL.value):
            raise ParkingError(
                ErrorCode.INVALID_GATE_DIRECTION,
                f"gate {gate.code} is not an exit gate (direction={gate.direction})",
                status=422,
            )
        lane = LaneRepository(self.session, tenant_id).get(session.site_id, exit_gate_id, exit_lane_id)
        if lane.direction not in (LaneDirection.EXIT.value, LaneDirection.BIDIRECTIONAL.value):
            raise ParkingError(
                ErrorCode.INVALID_LANE,
                f"lane {lane.code} is not an exit lane (direction={lane.direction})",
                status=422,
            )
        at = exit_at or datetime.now(timezone.utc)
        session.exit_gate_id = exit_gate_id
        session.exit_lane_id = exit_lane_id
        session.exit_at = at
        self.repo.update_state(session, SessionState.EXITED.value, self.scope.actor)
        self.repo.add_event(
            session.tenant_id,
            session.site_id,
            session.id,
            EventType.VEHICLE_EXITED.value,
            self.scope.actor,
            {"exit_gate_id": exit_gate_id, "exit_lane_id": exit_lane_id, "exit_at": at.isoformat()},
        )
        self.repo.update_state(session, SessionState.CLOSED.value, self.scope.actor)
        self.repo.add_event(
            session.tenant_id,
            session.site_id,
            session.id,
            EventType.SESSION_CLOSED.value,
            self.scope.actor,
            {},
        )
        self.session.commit()
        self.session.refresh(session)
        return session

    # ---- exceptional flows --------------------------------------------------
    def cancel(self, public_reference: str, reason: str | None = None) -> ParkingSession:
        session = self.repo.get_by_public_reference(public_reference)
        if session.state in (SessionState.CLOSED.value, SessionState.CANCELLED.value):
            raise ParkingError(
                ErrorCode.INVALID_SESSION_STATE, f"cannot cancel a {session.state} session", status=409
            )
        self.repo.update_state(session, SessionState.CANCELLED.value, self.scope.actor)
        self.repo.add_event(
            session.tenant_id,
            session.site_id,
            session.id,
            EventType.SESSION_CANCELLED.value,
            self.scope.actor,
            {"reason": reason},
        )
        self.repo.add_audit(
            tenant_id=session.tenant_id,
            site_id=session.site_id,
            actor=self.scope.actor,
            action="session.cancelled",
            object_type="parking_session",
            object_id=session.public_reference,
            details={"reason": reason, "from_state": session.state},
        )
        self.session.commit()
        self.session.refresh(session)
        return session

    def declare_lost_ticket(self, public_reference: str, reason: str | None = None) -> ParkingSession:
        session = self.repo.get_by_public_reference(public_reference)
        if session.state not in (
            SessionState.PARKED.value,
            SessionState.PAYMENT_PENDING.value,
            SessionState.MANUAL_REVIEW.value,
        ):
            raise ParkingError(
                ErrorCode.INVALID_SESSION_STATE,
                f"cannot declare lost ticket from state {session.state}",
                status=409,
            )
        plan_repo = self._plan_repo()
        plan = plan_repo.get_active_for_site(session.site_id)
        fee_rule = next(
            (r for r in plan_repo.rules_for(plan.id, session.vehicle_type) if r.rule_type == "LOST_TICKET_FEE"),
            None,
        )
        if fee_rule is None:
            raise ParkingError(
                ErrorCode.LOST_TICKET_FEE_NOT_CONFIGURED,
                f"no lost-ticket fee configured for vehicle type {session.vehicle_type}",
                status=400,
            )
        fee = int(fee_rule.config["amount"])

        original_amount = session.calculated_amount
        if original_amount == 0 and not session.tariff_snapshot:
            self.tariff.calculate(session)
            original_amount = session.calculated_amount

        snapshot = dict(session.tariff_snapshot or {})
        snapshot["lost_ticket"] = {
            "declared_at": datetime.now(timezone.utc).isoformat(),
            "fee": fee,
            "original_amount": original_amount,
            "final_amount": fee,
            "reason": reason,
            "actor": self.scope.actor,
        }
        session.lost_ticket = True
        session.calculated_amount = fee
        session.tariff_snapshot = snapshot
        self.repo.update_state(session, SessionState.LOST_TICKET.value, self.scope.actor)
        self.repo.add_event(
            session.tenant_id,
            session.site_id,
            session.id,
            EventType.LOST_TICKET_DECLARED.value,
            self.scope.actor,
            {"fee": fee, "original_amount": original_amount, "reason": reason},
        )
        self.repo.add_audit(
            tenant_id=session.tenant_id,
            site_id=session.site_id,
            actor=self.scope.actor,
            action="session.lost_ticket",
            object_type="parking_session",
            object_id=session.public_reference,
            details={"fee": fee, "original_amount": original_amount, "reason": reason},
        )
        self.session.commit()
        self.session.refresh(session)
        return session

    def apply_complimentary(self, public_reference: str, reason: str) -> ParkingSession:
        session = self.repo.get_by_public_reference(public_reference)
        if session.payment_state in (PaymentState.PAID.value, PaymentState.COMPLIMENTARY.value):
            raise ParkingError(
                ErrorCode.COMPLIMENTARY_NOT_ALLOWED, "payment is already finalized for this session", status=409
            )
        if session.state not in (
            SessionState.PARKED.value,
            SessionState.PAYMENT_PENDING.value,
            SessionState.MANUAL_REVIEW.value,
            SessionState.LOST_TICKET.value,
        ):
            raise ParkingError(
                ErrorCode.INVALID_SESSION_STATE,
                f"cannot apply complimentary from state {session.state}",
                status=409,
            )
        original_amount = session.calculated_amount
        if original_amount == 0 and not session.tariff_snapshot:
            self.tariff.calculate(session)
            original_amount = session.calculated_amount

        snapshot = dict(session.tariff_snapshot or {})
        snapshot["complimentary"] = {
            "applied_at": datetime.now(timezone.utc).isoformat(),
            "original_amount": original_amount,
            "final_amount": 0,
            "reason": reason,
            "actor": self.scope.actor,
        }
        session.tariff_snapshot = snapshot
        assert_payment_transition(session.payment_state, PaymentState.COMPLIMENTARY.value)
        session.payment_state = PaymentState.COMPLIMENTARY.value

        # Move to PAID through validated transitions (PARKED/LOST_TICKET/MANUAL_REVIEW
        # -> PAYMENT_PENDING -> PAID).
        if session.state in (
            SessionState.PARKED.value,
            SessionState.LOST_TICKET.value,
            SessionState.MANUAL_REVIEW.value,
        ):
            self.repo.update_state(session, SessionState.PAYMENT_PENDING.value, self.scope.actor)
        if session.state == SessionState.PAYMENT_PENDING.value:
            self.repo.update_state(session, SessionState.PAID.value, self.scope.actor)

        self.repo.add_event(
            session.tenant_id,
            session.site_id,
            session.id,
            EventType.COMPLIMENTARY_APPLIED.value,
            self.scope.actor,
            {"original_amount": original_amount, "final_amount": 0, "reason": reason},
        )
        self.repo.add_audit(
            tenant_id=session.tenant_id,
            site_id=session.site_id,
            actor=self.scope.actor,
            action="session.complimentary",
            object_type="parking_session",
            object_id=session.public_reference,
            details={"original_amount": original_amount, "final_amount": 0, "reason": reason},
        )
        self.session.commit()
        self.session.refresh(session)
        return session

    def _plan_repo(self):
        from parking.repositories.tariff_repo import TariffPlanRepository

        return TariffPlanRepository(self.session, self.scope.tenant_id)
