"""M12: Hardware compatibility matrix + failure matrix.

Documents capability status honestly. No false ONVIF conformance claims.
"""

from __future__ import annotations

# Status values:
#   CONTRACT_VERIFIED      - interface contract implemented
#   SIMULATOR_VERIFIED     - deterministic simulator tested
#   PHYSICAL_TEST_PENDING  - real hardware not yet tested
#   PHYSICAL_VERIFIED      - real hardware tested (not yet in this project)

HARDWARE_COMPATIBILITY_MATRIX = [
    {
        "category": "ANPR Camera",
        "required_interface": "ANPRAdapter.parse() -> normalized event",
        "preferred_standard": "ONVIF Profile M",
        "tested_status": "SIMULATOR_VERIFIED",
        "simulator_status": "SimulatedAnprAdapter + OnvifProfileMAdapter",
        "physical_status": "PHYSICAL_TEST_PENDING",
        "notes": "Capability-based; not all ONVIF cameras support every optional feature.",
    },
    {
        "category": "Barrier Controller",
        "required_interface": "BarrierAdapter.open/close/status",
        "preferred_standard": "ONVIF Profile D",
        "tested_status": "SIMULATOR_VERIFIED",
        "simulator_status": "SimulatedBarrierAdapter + OnvifProfileDAdapter",
        "physical_status": "PHYSICAL_TEST_PENDING",
        "notes": "ACK distinct from physical state; FAIL_CLOSED default.",
    },
    {
        "category": "Loop Sensor",
        "required_interface": "sensor event contract (VEHICLE_PRESENT/CLEAR)",
        "preferred_standard": "generic sensor event",
        "tested_status": "CONTRACT_VERIFIED",
        "simulator_status": "SensorState enum",
        "physical_status": "PHYSICAL_TEST_PENDING",
        "notes": "No physical loop detector required for M8 acceptance.",
    },
    {
        "category": "QR Scanner",
        "required_interface": "PaymentAdapter (QRIS MPM/CPM)",
        "preferred_standard": "QRIS MPM dynamic / CPM",
        "tested_status": "SIMULATOR_VERIFIED",
        "simulator_status": "SimulatedPaymentAdapter",
        "physical_status": "PHYSICAL_TEST_PENDING",
        "notes": "No real QRIS transaction processed.",
    },
    {
        "category": "Edge Device",
        "required_interface": "EdgeRuntime + EdgeStore (SQLite)",
        "preferred_standard": "site-local runtime",
        "tested_status": "SIMULATOR_VERIFIED",
        "simulator_status": "EdgeRuntime + EdgeStore",
        "physical_status": "PHYSICAL_TEST_PENDING",
        "notes": "Durable queue, at-least-once sync, idempotent central apply.",
    },
]

# ONVIF conformance: we do NOT claim conformance without authoritative testing.
ONVIF_CONFORMANCE_CLAIMED = False
ONVIF_PROFILE_M_READINESS = "CONTRACT_VERIFIED"
ONVIF_PROFILE_D_READINESS = "CONTRACT_VERIFIED"


def get_hardware_matrix() -> list[dict]:
    return HARDWARE_COMPATIBILITY_MATRIX


FAILURE_MATRIX = [
    {"failure": "Central DB unavailable", "expected": "readiness 503; no silent open barrier"},
    {"failure": "Edge disconnected", "expected": "offline entry/exit via local policy; queue durable"},
    {"failure": "ANPR unavailable", "expected": "no admission; manual review path"},
    {"failure": "Barrier unavailable", "expected": "command FAILED; no uncontrolled open"},
    {"failure": "Payment provider unavailable", "expected": "PAYMENT_CONNECTIVITY_REQUIRED; no fabricated PAID"},
    {"failure": "Gate runtime offline", "expected": "GATE_NOT_AVAILABLE deny"},
    {"failure": "Stale Edge config", "expected": "config rejected (STALE_CONFIG)"},
    {"failure": "Clock skew", "expected": "CLOCK_SKEW_WARNING"},
    {"failure": "Duplicate device event", "expected": "idempotent; no duplicate session"},
    {"failure": "Duplicate payment callback", "expected": "replay ignored; no double settlement"},
    {"failure": "Disk/queue approaching threshold", "expected": "bounded batching; unsynced never purged"},
]


def get_failure_matrix() -> list[dict]:
    return FAILURE_MATRIX
