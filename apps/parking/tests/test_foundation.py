"""M1 acceptance: foundation, multi-site, tenant isolation, normalization."""

from __future__ import annotations

from parking.domain.enums import GateDirection, OperatorRole
from parking.domain.errors import ErrorCode, ParkingError
from parking.domain.plate import display_plate, normalize_plate
from parking.repositories.registry import ShiftRepository, SiteRepository

from tests.helpers import new_gate, new_lane, new_operator, new_site, new_tenant


def test_tenant_site_gate_lane_creation(db):
    tenant = new_tenant(db, code="T1")
    site = new_site(db, tenant, code="S1")
    entry_gate = new_gate(db, tenant, site, code="G-ENTRY", direction="ENTRY")
    lane = new_lane(db, tenant, site, entry_gate, code="L-ENTRY-1")

    assert tenant.id and tenant.code == "T1"
    assert site.id and site.tenant_id == tenant.id
    assert entry_gate.site_id == site.id and entry_gate.direction == "ENTRY"
    assert lane.gate_id == entry_gate.id and lane.vehicle_types == ["MOTORCYCLE", "CAR"]
    assert SiteRepository(db, tenant.id).get(site.id).id == site.id


def test_multi_site_architecture(db):
    tenant = new_tenant(db, code="T1")
    s1 = new_site(db, tenant, code="S1")
    s2 = new_site(db, tenant, code="S2")
    s3 = new_site(db, tenant, code="S3")
    sites = SiteRepository(db, tenant.id).list()
    assert {s.code for s in sites} == {"S1", "S2", "S3"}
    assert len({s.id for s in sites}) == 3


def test_exit_and_bidirectional_gates(db):
    tenant = new_tenant(db)
    site = new_site(db, tenant)
    exit_gate = new_gate(db, tenant, site, code="G-EXIT", direction="EXIT")
    bi_gate = new_gate(db, tenant, site, code="G-BI", direction="BIDIRECTIONAL")
    assert exit_gate.direction == GateDirection.EXIT.value
    assert bi_gate.direction == GateDirection.BIDIRECTIONAL.value


def test_operator_and_shift_foundation(db):
    tenant = new_tenant(db)
    site = new_site(db, tenant)
    operator = new_operator(db, tenant, username="cashier1")
    shift = ShiftRepository(db, tenant.id).open(site_id=site.id, operator_id=operator.id)
    assert operator.role == OperatorRole.OPERATOR.value
    assert shift.status == "OPEN"
    closed = ShiftRepository(db, tenant.id).close(shift)
    assert closed.status == "CLOSED" and closed.ended_at is not None


def test_plate_normalization(db):
    assert normalize_plate(" B 1234 ABC ") == "B1234ABC"
    assert normalize_plate("b-1234-ab-c") == "B1234ABC"
    assert normalize_plate("  d 5678  xy  ") == "D5678XY"
    assert display_plate("  B 1234   ABC ") == "B 1234 ABC"
    assert normalize_plate("") == ""


def test_tenant_isolation_site_lookup(db):
    tenant_a = new_tenant(db, code="TA")
    tenant_b = new_tenant(db, code="TB")
    site_a = new_site(db, tenant_a, code="SITE-A")

    try:
        SiteRepository(db, tenant_b.id).get(site_a.id)
        raise AssertionError("expected PARKING_SITE_NOT_FOUND for foreign tenant")
    except ParkingError as exc:
        assert exc.code == ErrorCode.PARKING_SITE_NOT_FOUND and exc.status == 404
