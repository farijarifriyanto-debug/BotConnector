"""M7 acceptance: ANPR normalization, confidence policy, idempotency, gate
authority, payment bypass blocked, manual correction, Profile M mapping,
cross-tenant spoof blocking."""

from __future__ import annotations

import pytest

from parking.anpr.service import AnprService, ConfidencePolicy
from parking.anpr.simulator import OnvifProfileMAdapter, SimulatedAnprAdapter
from parking.domain.enums import AnprConfidenceClass, AnprEventState, EventType
from parking.domain.errors import ErrorCode, ParkingError
from parking.gate.runtime import GateRuntimeService
from parking.repositories.registry import SiteRepository
from parking.repositories.session_repo import SessionRepository
from parking.repositories.tariff_repo import TariffPlanRepository
from parking.services.entry import EntryService

from tests.helpers import (
    hours_ago,
    new_gate,
    new_lane,
    new_site,
    new_tenant,
    scope,
)


def _site(db):
    tenant = new_tenant(db, code="T1")
    site = new_site(db, tenant, code="S1")
    gate = new_gate(db, tenant, site, code="G-ENTRY", direction="ENTRY")
    lane = new_lane(db, tenant, site, gate, code="L-ENTRY", direction="ENTRY")
    exit_gate = new_gate(db, tenant, site, code="G-EXIT", direction="EXIT")
    exit_lane = new_lane(db, tenant, site, exit_gate, code="L-EXIT", direction="EXIT")
    db.commit()
    return tenant, site, gate, lane, exit_gate, exit_lane


def _event(tenant, site, gate, lane, *, plate="B 1234 ABC", confidence=0.95, event_id="evt-1", direction="ENTRY"):
    return {
        "event_id": event_id,
        "tenant_id": tenant.id,
        "site_id": site.id,
        "gate_id": gate.id,
        "lane_id": lane.id,
        "captured_at": hours_ago(1).isoformat(),
        "plate_raw": plate,
        "confidence": confidence,
        "vehicle_type_guess": "CAR",
        "direction": direction,
    }


def test_normalized_anpr_event(db):
    tenant, site, gate, lane, _, _ = _site(db)
    svc = AnprService(db, scope(tenant))
    result = svc.process(_event(tenant, site, gate, lane, plate=" B 1234 ABC "))
    assert result.event.plate_normalized == "B1234ABC"
    assert result.event.plate_raw == " B 1234 ABC "
    assert result.event.confidence == 0.95
    assert result.event.provider == "SIMULATOR"


def test_high_confidence_admission_path(db):
    tenant, site, gate, lane, _, _ = _site(db)
    svc = AnprService(db, scope(tenant))
    result = svc.process(_event(tenant, site, gate, lane, confidence=0.95))
    assert result.confidence_class == AnprConfidenceClass.AUTO_CANDIDATE.value
    assert result.admission is not None
    assert result.admission.decision == "ALLOW"
    assert result.admission.barrier_action == "OPEN_BARRIER"
    assert result.event.state == AnprEventState.PROCESSED.value


def test_medium_confidence_manual_review(db):
    tenant, site, gate, lane, _, _ = _site(db)
    svc = AnprService(db, scope(tenant))
    result = svc.process(_event(tenant, site, gate, lane, confidence=0.70))
    assert result.confidence_class == AnprConfidenceClass.MANUAL_REVIEW.value
    assert result.admission is None
    assert result.event.state == AnprEventState.MANUAL_REVIEW.value


def test_low_confidence_rejected(db):
    tenant, site, gate, lane, _, _ = _site(db)
    svc = AnprService(db, scope(tenant))
    result = svc.process(_event(tenant, site, gate, lane, confidence=0.30))
    assert result.confidence_class == AnprConfidenceClass.REJECT.value
    assert result.admission is None
    assert result.event.state == AnprEventState.REJECTED.value


def test_duplicate_anpr_event_idempotent(db):
    tenant, site, gate, lane, _, _ = _site(db)
    svc = AnprService(db, scope(tenant))
    first = svc.process(_event(tenant, site, gate, lane, event_id="evt-dup"))
    second = svc.process(_event(tenant, site, gate, lane, event_id="evt-dup"))
    assert second.duplicate is True
    assert first.event.id == second.event.id
    # Only one active session created.
    active = SessionRepository(db, tenant.id).list_active(site.id)
    assert len(active) == 1


def test_anpr_cannot_bypass_gate_runtime(db):
    """ANPR alone never opens a barrier; it must go through GateRuntime."""
    tenant, site, gate, lane, _, _ = _site(db)
    # An EXIT-only gate: ANPR high-confidence entry must be DENIED by GateRuntime.
    exit_only_gate = new_gate(db, tenant, site, code="G-EXIT-ONLY", direction="EXIT")
    exit_only_lane = new_lane(db, tenant, site, exit_only_gate, code="L-EXIT-ONLY", direction="EXIT")
    db.commit()
    svc = AnprService(db, scope(tenant))
    result = svc.process(_event(tenant, site, exit_only_gate, exit_only_lane, event_id="evt-exit-gate"))
    assert result.admission.decision == "DENY"
    assert result.admission.reason == "INVALID_DIRECTION"
    assert result.admission.barrier_action == "KEEP_CLOSED"


def test_entry_repeated_event_no_duplicate_session(db):
    tenant, site, gate, lane, _, _ = _site(db)
    svc = AnprService(db, scope(tenant))
    svc.process(_event(tenant, site, gate, lane, event_id="evt-r1"))
    svc.process(_event(tenant, site, gate, lane, event_id="evt-r2", plate="b1234abc"))
    active = SessionRepository(db, tenant.id).list_active(site.id)
    assert len(active) == 1


def test_exit_anpr_cannot_bypass_payment(db):
    tenant, site, gate, lane, exit_gate, exit_lane = _site(db)
    # Create an active session via entry.
    EntryService(db, scope(tenant)).create_entry(
        site_id=site.id, gate_id=gate.id, lane_id=lane.id, plate="B1234ABC", vehicle_type="CAR", entry_at=hours_ago(2)
    )
    db.commit()
    svc = AnprService(db, scope(tenant))
    result = svc.process(_event(tenant, site, exit_gate, exit_lane, plate="B1234ABC",
                               event_id="evt-exit", direction="EXIT"))
    # Unpaid -> not allowed to exit.
    assert result.admission.decision == "DENY"
    assert result.admission.reason == "PAYMENT_REQUIRED"
    assert result.admission.barrier_action == "KEEP_CLOSED"


def test_manual_plate_correction_audited(db):
    tenant, site, gate, lane, _, _ = _site(db)
    svc = AnprService(db, scope(tenant))
    result = svc.process(_event(tenant, site, gate, lane, plate="B1234ABC", confidence=0.95, event_id="evt-corr"))
    corrected = svc.correct_plate("evt-corr", corrected_plate="B1234ABD", actor="operator:admin", reason="misread")
    assert corrected.plate_normalized == "B1234ABD"
    assert corrected.state == AnprEventState.CORRECTED.value
    from sqlalchemy import select
    from parking.models import ParkingAnprCorrection
    corrections = list(db.scalars(select(ParkingAnprCorrection).where(ParkingAnprCorrection.tenant_id == tenant.id)))
    assert len(corrections) == 1
    assert corrections[0].original_plate == "B1234ABC"
    assert corrections[0].corrected_plate == "B1234ABD"
    assert corrections[0].actor == "operator:admin"


def test_foreign_device_tenant_spoof_blocked(db):
    tenant_a, site_a, gate_a, lane_a, _, _ = _site(db)
    tenant_b = new_tenant(db, code="TB")
    # Device claims tenant B but event is submitted under tenant A scope.
    svc = AnprService(db, scope(tenant_a))
    payload = _event(tenant_b, site_a, gate_a, lane_a, event_id="evt-spoof")
    with pytest.raises(ParkingError) as exc:
        svc.process(payload)
    assert exc.value.code == ErrorCode.ANPR_DEVICE_NOT_AUTHORIZED
    assert exc.value.status == 403


def test_profile_m_fixture_mapping(db):
    tenant, site, gate, lane, _, _ = _site(db)
    adapter = OnvifProfileMAdapter()
    fixture = {
        "event_id": "onvif-1",
        "tenant_id": tenant.id,
        "site_id": site.id,
        "gate_id": gate.id,
        "lane_id": lane.id,
        "captured_at": hours_ago(1).isoformat(),
        "vehicle": {"type": "CAR", "plate": "B 1234 ABC"},
        "license_plate": {"text": "B 1234 ABC", "confidence": 0.92},
        "direction": "ENTRY",
        "image_reference": "ref://img/onvif-1",
        "crop_reference": "ref://crop/onvif-1",
        "provider_event_id": "onvif-prov-1",
    }
    raw = adapter.parse(fixture)
    assert raw.provider == "ONVIF_PROFILE_M"
    assert raw.plate_raw == "B 1234 ABC"
    assert raw.confidence == 0.92
    assert raw.vehicle_type_guess == "CAR"
    assert raw.image_reference == "ref://img/onvif-1"
    assert adapter.capabilities()["plate_crop"] is True
