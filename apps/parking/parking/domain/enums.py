"""Stable domain enumerations.

All enums are stored as VARCHAR + CHECK constraints (no native PG enum types)
to keep migrations simple and reversible.
"""

from __future__ import annotations

import enum


class _StrEnum(str, enum.Enum):
    def __str__(self) -> str:  # pragma: no cover - convenience
        return self.value


class TenantStatus(_StrEnum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class SiteStatus(_StrEnum):
    ACTIVE = "ACTIVE"
    INACTIVE = "INACTIVE"


class GateDirection(_StrEnum):
    ENTRY = "ENTRY"
    EXIT = "EXIT"
    BIDIRECTIONAL = "BIDIRECTIONAL"


class GateStatus(_StrEnum):
    ACTIVE = "ACTIVE"
    INACTIVE = "INACTIVE"
    MAINTENANCE = "MAINTENANCE"


class LaneDirection(_StrEnum):
    ENTRY = "ENTRY"
    EXIT = "EXIT"
    BIDIRECTIONAL = "BIDIRECTIONAL"


class LaneStatus(_StrEnum):
    ACTIVE = "ACTIVE"
    INACTIVE = "INACTIVE"
    MAINTENANCE = "MAINTENANCE"


class VehicleType(_StrEnum):
    MOTORCYCLE = "MOTORCYCLE"
    CAR = "CAR"
    TRUCK = "TRUCK"
    BUS = "BUS"
    OTHER = "OTHER"


class SessionState(_StrEnum):
    CREATED = "CREATED"
    ENTERED = "ENTERED"
    PARKED = "PARKED"
    PAYMENT_PENDING = "PAYMENT_PENDING"
    PAID = "PAID"
    EXIT_AUTHORIZED = "EXIT_AUTHORIZED"
    EXITED = "EXITED"
    CLOSED = "CLOSED"
    CANCELLED = "CANCELLED"
    LOST_TICKET = "LOST_TICKET"
    MANUAL_REVIEW = "MANUAL_REVIEW"


# States that count as an open/active session for the duplicate guard.
ACTIVE_SESSION_STATES = (
    SessionState.CREATED.value,
    SessionState.ENTERED.value,
    SessionState.PARKED.value,
    SessionState.PAYMENT_PENDING.value,
    SessionState.LOST_TICKET.value,
    SessionState.MANUAL_REVIEW.value,
)

TERMINAL_SESSION_STATES = (SessionState.CLOSED.value, SessionState.CANCELLED.value)


class PaymentState(_StrEnum):
    NONE = "NONE"
    PENDING = "PENDING"
    PAID = "PAID"
    COMPLIMENTARY = "COMPLIMENTARY"


class TariffRuleType(_StrEnum):
    FLAT = "FLAT"
    HOURLY = "HOURLY"
    PROGRESSIVE = "PROGRESSIVE"
    LOST_TICKET_FEE = "LOST_TICKET_FEE"


BASE_TARIFF_TYPES = (TariffRuleType.FLAT.value, TariffRuleType.HOURLY.value, TariffRuleType.PROGRESSIVE.value)


class TariffPlanStatus(_StrEnum):
    ACTIVE = "ACTIVE"
    INACTIVE = "INACTIVE"


class OperatorRole(_StrEnum):
    OWNER = "OWNER"
    ADMIN = "ADMIN"
    MANAGER = "MANAGER"
    SUPERVISOR = "SUPERVISOR"
    OPERATOR = "OPERATOR"
    VIEWER = "VIEWER"


class OperatorStatus(_StrEnum):
    ACTIVE = "ACTIVE"
    DISABLED = "DISABLED"


class ShiftStatus(_StrEnum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"


class EventType(_StrEnum):
    SESSION_CREATED = "SESSION_CREATED"
    VEHICLE_ENTERED = "VEHICLE_ENTERED"
    STATE_CHANGED = "STATE_CHANGED"
    TARIFF_CALCULATED = "TARIFF_CALCULATED"
    LOST_TICKET_DECLARED = "LOST_TICKET_DECLARED"
    COMPLIMENTARY_APPLIED = "COMPLIMENTARY_APPLIED"
    PAYMENT_MARKED_PAID = "PAYMENT_MARKED_PAID"
    EXIT_AUTHORIZED = "EXIT_AUTHORIZED"
    VEHICLE_EXITED = "VEHICLE_EXITED"
    SESSION_CLOSED = "SESSION_CLOSED"
    SESSION_CANCELLED = "SESSION_CANCELLED"
    MANUAL_OVERRIDE = "MANUAL_OVERRIDE"
    # M4 gate runtime
    ENTRY_REQUESTED = "ENTRY_REQUESTED"
    ENTRY_ALLOWED = "ENTRY_ALLOWED"
    ENTRY_DENIED = "ENTRY_DENIED"
    GATE_STATE_CHANGED = "GATE_STATE_CHANGED"
    BARRIER_OPEN_INTENT_CREATED = "BARRIER_OPEN_INTENT_CREATED"
    # M5 exit runtime
    EXIT_QUOTE_CREATED = "EXIT_QUOTE_CREATED"
    EXIT_QUOTE_EXPIRED = "EXIT_QUOTE_EXPIRED"
    EXIT_QUOTE_PAID = "EXIT_QUOTE_PAID"
    # M6 payment runtime
    PAYMENT_CREATED = "PAYMENT_CREATED"
    PAYMENT_PENDING = "PAYMENT_PENDING"
    PAYMENT_VERIFIED = "PAYMENT_VERIFIED"
    PAYMENT_FAILED = "PAYMENT_FAILED"
    PAYMENT_EXPIRED = "PAYMENT_EXPIRED"
    PAYMENT_CALLBACK_RECEIVED = "PAYMENT_CALLBACK_RECEIVED"
    PAYMENT_CALLBACK_REPLAY_IGNORED = "PAYMENT_CALLBACK_REPLAY_IGNORED"
    PAYMENT_PAID = "PAYMENT_PAID"


class GateRuntimeState(_StrEnum):
    ONLINE = "ONLINE"
    OFFLINE = "OFFLINE"
    MAINTENANCE = "MAINTENANCE"
    BLOCKED = "BLOCKED"


class LaneRuntimeState(_StrEnum):
    ONLINE = "ONLINE"
    OFFLINE = "OFFLINE"
    MAINTENANCE = "MAINTENANCE"
    BLOCKED = "BLOCKED"


class AdmissionDecision(_StrEnum):
    ALLOW = "ALLOW"
    DENY = "DENY"
    MANUAL_REVIEW = "MANUAL_REVIEW"


class BarrierAction(_StrEnum):
    OPEN_BARRIER = "OPEN_BARRIER"
    KEEP_CLOSED = "KEEP_CLOSED"
    MANUAL_REVIEW = "MANUAL_REVIEW"


class ExitQuoteStatus(_StrEnum):
    ACTIVE = "ACTIVE"
    EXPIRED = "EXPIRED"
    SUPERSEDED = "SUPERSEDED"
    PAID = "PAID"
    CANCELLED = "CANCELLED"


class PaymentMethod(_StrEnum):
    CASH = "CASH"
    QRIS_MPM_DYNAMIC = "QRIS_MPM_DYNAMIC"
    QRIS_CPM = "QRIS_CPM"
    COMPLIMENTARY = "COMPLIMENTARY"
    MEMBERSHIP = "MEMBERSHIP"


class PaymentProvider(_StrEnum):
    CASH = "CASH"
    COMPLIMENTARY = "COMPLIMENTARY"
    SIMULATOR = "SIMULATOR"


class PaymentEntityState(_StrEnum):
    CREATED = "CREATED"
    PENDING = "PENDING"
    PAID = "PAID"
    FAILED = "FAILED"
    EXPIRED = "EXPIRED"
    CANCELLED = "CANCELLED"
    REFUNDED = "REFUNDED"


class PaymentAttemptState(_StrEnum):
    CREATED = "CREATED"
    PENDING = "PENDING"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    EXPIRED = "EXPIRED"


# ---- M7 ANPR ---------------------------------------------------------------
class AnprConfidenceClass(_StrEnum):
    AUTO_CANDIDATE = "AUTO_CANDIDATE"
    MANUAL_REVIEW = "MANUAL_REVIEW"
    REJECT = "REJECT"
    UNKNOWN = "UNKNOWN"


class AnprEventState(_StrEnum):
    RECEIVED = "RECEIVED"
    PROCESSED = "PROCESSED"
    DUPLICATE = "DUPLICATE"
    REJECTED = "REJECTED"
    MANUAL_REVIEW = "MANUAL_REVIEW"
    CORRECTED = "CORRECTED"


# ---- M8 device / barrier ---------------------------------------------------
class DeviceType(_StrEnum):
    ANPR_CAMERA = "ANPR_CAMERA"
    BARRIER_CONTROLLER = "BARRIER_CONTROLLER"
    LOOP_SENSOR = "LOOP_SENSOR"
    QR_SCANNER = "QR_SCANNER"
    DISPLAY = "DISPLAY"
    EDGE_GATEWAY = "EDGE_GATEWAY"
    OTHER = "OTHER"


class DeviceRuntimeState(_StrEnum):
    ONLINE = "ONLINE"
    OFFLINE = "OFFLINE"
    DEGRADED = "DEGRADED"
    MAINTENANCE = "MAINTENANCE"
    UNKNOWN = "UNKNOWN"


class BarrierState(_StrEnum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"
    OPENING = "OPENING"
    CLOSING = "CLOSING"
    FAULT = "FAULT"
    UNKNOWN = "UNKNOWN"


class SensorState(_StrEnum):
    VEHICLE_PRESENT = "VEHICLE_PRESENT"
    CLEAR = "CLEAR"
    UNKNOWN = "UNKNOWN"


class BarrierCommandType(_StrEnum):
    OPEN = "OPEN"
    CLOSE = "CLOSE"
    STATUS = "STATUS"


class BarrierCommandStatus(_StrEnum):
    CREATED = "CREATED"
    DISPATCHED = "DISPATCHED"
    ACKNOWLEDGED = "ACKNOWLEDGED"
    FAILED = "FAILED"
    EXPIRED = "EXPIRED"


class FailPolicy(_StrEnum):
    FAIL_CLOSED = "FAIL_CLOSED"
    FAIL_MANUAL = "FAIL_MANUAL"


# ---- M9 edge ---------------------------------------------------------------
class EdgeSyncState(_StrEnum):
    PENDING = "PENDING"
    SYNCED = "SYNCED"
    FAILED = "FAILED"
    CONFLICT = "CONFLICT"


class ConflictClass(_StrEnum):
    DUPLICATE_EVENT = "DUPLICATE_EVENT"
    STALE_CONFIG = "STALE_CONFIG"
    SESSION_ALREADY_CLOSED = "SESSION_ALREADY_CLOSED"
    PAYMENT_CONFLICT = "PAYMENT_CONFLICT"
    UNKNOWN_SESSION = "UNKNOWN_SESSION"
    SEQUENCE_GAP = "SEQUENCE_GAP"
