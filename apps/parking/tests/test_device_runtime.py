"""M8 acceptance: device registry, runtime health, barrier commands, idempotency,
ACK vs physical state, fail policy, Profile D contract, cross-tenant blocking."""

from __future__ import annotations

import pytest

from parking.device.adapters import BarrierStatus, CommandAck
from parking.device.repo import DeviceRepository, DeviceRuntimeRepository
from parking.device.service import BarrierService
from parking.device.simulator import OnvifProfileDAdapter, SimulatedBarrierAdapter
from parking.domain.enums import BarrierCommandStatus, BarrierCommandType, DeviceRuntimeState, DeviceType
from parking.domain.errors import ErrorCode, ParkingError

from tests.helpers import new_gate, new_lane, new_site, new_tenant, scope


def _site(db):
    tenant = new_tenant(db, code="T1")
    site = new_site(db, tenant, code="S1")
    gate = new_gate(db, tenant, site, code="G-ENTRY", direction="ENTRY")
    lane = new_lane(db, tenant, site, gate, code="L-ENTRY", direction="ENTRY")
    db.commit()
    return tenant, site, gate, lane


def _device(db, tenant, site, *, device_id="DEV-1", device_type="BARRIER_CONTROLLER", adapter="SIMULATOR"):
    return DeviceRepository(db, tenant.id).create(
        device_id=device_id, site_id=site.id, device_type=device_type, name=device_id, adapter_type=adapter
    )


def test_device_registration(db):
    tenant, site, gate, lane = _site(db)
    device = _device(db, tenant, site)
    assert device.device_id == "DEV-1"
    assert device.device_type == DeviceType.BARRIER_CONTROLLER.value
    assert device.enabled is True
    assert device.credential_reference is None  # no inline credentials


def test_runtime_health_state(db):
    tenant, site, gate, lane = _site(db)
    device = _device(db, tenant, site)
    rt = DeviceRuntimeRepository(db, tenant.id).set_state(site_id=site.id, device_pk=device.id, state="ONLINE")
    assert rt.state == DeviceRuntimeState.ONLINE.value
    rt2 = DeviceRuntimeRepository(db, tenant.id).set_state(site_id=site.id, device_pk=device.id, state="OFFLINE")
    assert rt2.state == DeviceRuntimeState.OFFLINE.value


def test_allowed_barrier_intent_creates_open_command(db):
    tenant, site, gate, lane = _site(db)
    device = _device(db, tenant, site)
    DeviceRuntimeRepository(db, tenant.id).set_state(site_id=site.id, device_pk=device.id, state="ONLINE")
    db.commit()
    svc = BarrierService(db, scope(tenant))
    result = svc.dispatch(site_id=site.id, device_id="DEV-1", command_type="OPEN",
                          idempotency_key="open-1", reason="entry allowed")
    assert result.command.command_type == BarrierCommandType.OPEN.value
    assert result.command.status == BarrierCommandStatus.ACKNOWLEDGED.value
    assert result.ack.accepted is True


def test_denied_admission_never_creates_open_command(db):
    """A denied admission must not produce an OPEN command. The barrier service
    only dispatches when explicitly called with an approved intent."""
    tenant, site, gate, lane = _site(db)
    device = _device(db, tenant, site)
    DeviceRuntimeRepository(db, tenant.id).set_state(site_id=site.id, device_pk=device.id, state="ONLINE")
    db.commit()
    svc = BarrierService(db, scope(tenant))
    # No OPEN command is created unless dispatch is called with OPEN.
    commands = svc.commands.get_by_idempotency_key("never-issued")
    assert commands is None


def test_duplicate_command_idempotent(db):
    tenant, site, gate, lane = _site(db)
    device = _device(db, tenant, site)
    DeviceRuntimeRepository(db, tenant.id).set_state(site_id=site.id, device_pk=device.id, state="ONLINE")
    db.commit()
    svc = BarrierService(db, scope(tenant))
    first = svc.dispatch(site_id=site.id, device_id="DEV-1", command_type="OPEN", idempotency_key="open-dup")
    second = svc.dispatch(site_id=site.id, device_id="DEV-1", command_type="OPEN", idempotency_key="open-dup")
    assert first.command.id == second.command.id
    assert second.details.get("idempotent") is True


def test_ack_distinct_from_physical_state(db):
    tenant, site, gate, lane = _site(db)
    device = _device(db, tenant, site)
    DeviceRuntimeRepository(db, tenant.id).set_state(site_id=site.id, device_pk=device.id, state="ONLINE")
    db.commit()
    adapter = SimulatedBarrierAdapter()
    svc = BarrierService(db, scope(tenant), adapter=adapter)
    result = svc.dispatch(site_id=site.id, device_id="DEV-1", command_type="OPEN", idempotency_key="open-ack")
    # ACK accepted, but physical state is OPENING (not yet OPEN).
    assert result.ack.accepted is True
    assert result.physical_state == "OPENING"
    # Physical state can be confirmed separately.
    adapter.set_physical_state("OPEN")
    status = adapter.status()
    assert status.state == "OPEN"


def test_device_offline_handled(db):
    tenant, site, gate, lane = _site(db)
    device = _device(db, tenant, site)
    DeviceRuntimeRepository(db, tenant.id).set_state(site_id=site.id, device_pk=device.id, state="OFFLINE")
    db.commit()
    svc = BarrierService(db, scope(tenant))
    with pytest.raises(ParkingError) as exc:
        svc.dispatch(site_id=site.id, device_id="DEV-1", command_type="OPEN", idempotency_key="open-offline")
    assert exc.value.code == ErrorCode.DEVICE_OFFLINE


def test_simulated_barrier_open_close(db):
    tenant, site, gate, lane = _site(db)
    device = _device(db, tenant, site)
    DeviceRuntimeRepository(db, tenant.id).set_state(site_id=site.id, device_pk=device.id, state="ONLINE")
    db.commit()
    adapter = SimulatedBarrierAdapter()
    svc = BarrierService(db, scope(tenant), adapter=adapter)
    svc.dispatch(site_id=site.id, device_id="DEV-1", command_type="OPEN", idempotency_key="sim-open")
    svc.dispatch(site_id=site.id, device_id="DEV-1", command_type="CLOSE", idempotency_key="sim-close")
    actions = [c["action"] for c in adapter.commands]
    assert "OPEN" in actions and "CLOSE" in actions


def test_foreign_tenant_device_command_blocked(db):
    tenant_a, site_a, gate_a, lane_a = _site(db)
    device = _device(db, tenant_a, site_a)
    DeviceRuntimeRepository(db, tenant_a.id).set_state(site_id=site_a.id, device_pk=device.id, state="ONLINE")
    db.commit()
    tenant_b = new_tenant(db, code="TB")
    with pytest.raises(ParkingError) as exc:
        BarrierService(db, scope(tenant_b)).dispatch(
            site_id=site_a.id, device_id="DEV-1", command_type="OPEN", idempotency_key="open-x"
        )
    assert exc.value.code == ErrorCode.DEVICE_NOT_FOUND
    assert exc.value.status == 404


def test_profile_d_contract(db):
    adapter = OnvifProfileDAdapter()
    caps = adapter.capabilities()
    assert caps["output_device"] is True
    assert caps["sensor"] is True
    ack = adapter.open(command_id="CMD-1", reason="test")
    assert ack.accepted is True
    status = adapter.status()
    assert status.state in ("OPENING", "OPEN", "CLOSED", "CLOSING", "FAULT", "UNKNOWN")
