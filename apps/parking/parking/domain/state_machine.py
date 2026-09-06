"""Server-side session state machine.

No arbitrary state jumps: every transition is validated against the map below
in the domain/service layer (never trusted to the client).
"""

from __future__ import annotations

from parking.domain.enums import PaymentState, SessionState
from parking.domain.errors import ErrorCode, ParkingError

ALLOWED_TRANSITIONS: dict[str, set[str]] = {
    SessionState.CREATED.value: {SessionState.ENTERED.value},
    SessionState.ENTERED.value: {SessionState.PARKED.value},
    SessionState.PARKED.value: {
        SessionState.PAYMENT_PENDING.value,
        SessionState.LOST_TICKET.value,
        SessionState.MANUAL_REVIEW.value,
        SessionState.CANCELLED.value,
    },
    SessionState.PAYMENT_PENDING.value: {
        SessionState.PAID.value,
        SessionState.MANUAL_REVIEW.value,
        SessionState.LOST_TICKET.value,
        SessionState.CANCELLED.value,
    },
    SessionState.LOST_TICKET.value: {
        SessionState.PAYMENT_PENDING.value,
        SessionState.MANUAL_REVIEW.value,
        SessionState.CANCELLED.value,
    },
    SessionState.MANUAL_REVIEW.value: {
        SessionState.PARKED.value,
        SessionState.PAYMENT_PENDING.value,
        SessionState.CANCELLED.value,
    },
    SessionState.PAID.value: {SessionState.EXIT_AUTHORIZED.value},
    SessionState.EXIT_AUTHORIZED.value: {SessionState.EXITED.value},
    SessionState.EXITED.value: {SessionState.CLOSED.value},
    SessionState.CLOSED.value: set(),
    SessionState.CANCELLED.value: set(),
}

ALLOWED_PAYMENT_TRANSITIONS: dict[str, set[str]] = {
    PaymentState.NONE.value: {PaymentState.PENDING.value, PaymentState.COMPLIMENTARY.value},
    PaymentState.PENDING.value: {PaymentState.PAID.value, PaymentState.COMPLIMENTARY.value},
    PaymentState.PAID.value: set(),
    PaymentState.COMPLIMENTARY.value: set(),
}


def can_transition(current: str, target: str) -> bool:
    return target in ALLOWED_TRANSITIONS.get(current, set())


def assert_transition(current: str, target: str) -> None:
    if not can_transition(current, target):
        raise ParkingError(
            ErrorCode.INVALID_SESSION_STATE,
            f"invalid session state transition {current} -> {target}",
            status=409,
        )


def assert_payment_transition(current: str, target: str) -> None:
    if target not in ALLOWED_PAYMENT_TRANSITIONS.get(current, set()):
        raise ParkingError(
            ErrorCode.INVALID_SESSION_STATE,
            f"invalid payment state transition {current} -> {target}",
            status=409,
        )
