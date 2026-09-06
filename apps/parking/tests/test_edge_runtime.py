"""M9 acceptance: edge config snapshot, site isolation, offline entry, durable
queue, restart durability, offline settlement, unverified QRIS blocked, reconnect
sync, idempotency, partial ACK, sequence tracking, conflicts, clock skew, bounded
batching, unsynced retention, foreign edge spoof."""

from __future__ import annotations

import os
import tempfile
from datetime import datetime, timedelta, timezone

import pytest

from parking.domain.enums import ConflictClass
from parking.domain.errors import ErrorCode, ParkingError
from parking.edge.central import CentralSyncService
from parking.edge.runtime import EdgeRuntime
from parking.edge.store import EdgeStore

from tests.helpers import new_site, new_tenant, scope


def _store(tmp_path, name="edge.db"):
    return EdgeStore(str(tmp_path / name))


def _config(site_id, version=1):
    return {
        "config_version": version,
        "site_id": site_id,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "gates": [{"id": 1, "code": "G1", "direction": "ENTRY"}],
        "lanes": [{"id": 1, "code": "L1"}],
        "tariffs": [{"vehicle_type": "CAR", "amount": 5000}],
        "offline_policy": "FAIL_CLOSED",
    }


def _edge(tmp_path, site_id=1, edge_id="EDGE-1"):
    store = _store(tmp_path)
    store.set_identity(edge_id=edge_id, tenant_id=1, site_id=site_id)
    store.accept_config(config_version=1, site_id=site_id,
                        generated_at=datetime.now(timezone.utc).isoformat(), payload=_config(site_id))
    return EdgeRuntime(store)


def test_edge_config_snapshot(tmp_path):
    store = _store(tmp_path)
    store.set_identity(edge_id="EDGE-1", tenant_id=1, site_id=1)
    assert store.accept_config(config_version=1, site_id=1,
                               generated_at=datetime.now(timezone.utc).isoformat(), payload=_config(1)) is True
    # Stale config rejected.
    assert store.accept_config(config_version=1, site_id=1,
                               generated_at=datetime.now(timezone.utc).isoformat(), payload=_config(1)) is False
    cfg = store.current_config()
    assert cfg["config_version"] == 1
    assert cfg["content_hash"]


def test_edge_site_isolation(tmp_path):
    store = _store(tmp_path)
    store.set_identity(edge_id="EDGE-1", tenant_id=1, site_id=1)
    store.accept_config(config_version=1, site_id=1,
                        generated_at=datetime.now(timezone.utc).isoformat(), payload=_config(1))
    edge = EdgeRuntime(store)
    # Entry for a different site must be rejected.
    result = edge.offline_entry(plate="B1234ABC", vehicle_type="CAR", site_id=99, gate_id=1, lane_id=1)
    assert result.accepted is False
    assert result.reason == "SITE_MISMATCH"


def test_offline_entry(tmp_path):
    edge = _edge(tmp_path)
    result = edge.offline_entry(plate="B 1234 ABC", vehicle_type="CAR", site_id=1, gate_id=1, lane_id=1)
    assert result.accepted is True
    assert result.reason == "OFFLINE_ENTRY_ACCEPTED"
    assert result.event_id is not None
    assert result.barrier_action == "OPEN_BARRIER"
    assert edge.store.queue_depth() == 1


def test_durable_event_queue(tmp_path):
    edge = _edge(tmp_path)
    edge.offline_entry(plate="B1234ABC", vehicle_type="CAR", site_id=1, gate_id=1, lane_id=1)
    edge.offline_entry(plate="B9999ZZ", vehicle_type="CAR", site_id=1, gate_id=1, lane_id=1)
    assert edge.store.queue_depth() == 2
    pending = edge.store.pending_events()
    assert len(pending) == 2


def test_local_operation_survives_restart(tmp_path):
    edge = _edge(tmp_path)
    edge.offline_entry(plate="B1234ABC", vehicle_type="CAR", site_id=1, gate_id=1, lane_id=1)
    edge.store.close()
    # Reopen the same SQLite file (simulates Edge process restart).
    store2 = EdgeStore(str(tmp_path / "edge.db"))
    edge2 = EdgeRuntime(store2)
    assert edge2.store.queue_depth() == 1
    assert edge2.store.find_session_by_plate("B1234ABC") is not None


def test_offline_cash_settlement(tmp_path):
    edge = _edge(tmp_path)
    entry = edge.offline_entry(plate="B1234ABC", vehicle_type="CAR", site_id=1, gate_id=1, lane_id=1)
    ref = entry.details["public_reference"]
    result = edge.offline_exit(public_reference=ref, method="CASH", amount=5000)
    assert result.accepted is True
    assert result.reason == "OFFLINE_CASH_EXIT_ACCEPTED"
    assert edge.store.get_session(ref) is None  # closed locally


def test_offline_unverified_qris_not_paid(tmp_path):
    edge = _edge(tmp_path)
    entry = edge.offline_entry(plate="B1234ABC", vehicle_type="CAR", site_id=1, gate_id=1, lane_id=1)
    ref = entry.details["public_reference"]
    result = edge.offline_exit(public_reference=ref, method="QRIS_MPM_DYNAMIC", amount=5000)
    assert result.accepted is False
    assert result.reason == "PAYMENT_CONNECTIVITY_REQUIRED"
    # Session NOT closed, no PAID fabricated.
    assert edge.store.get_session(ref) is not None


def test_reconnect_sync(tmp_path, db):
    tenant = new_tenant(db, code="T1")
    site = new_site(db, tenant, code="S1")
    from parking.models import ParkingEdge
    from parking.repositories.registry import TenantRepository
    edge = ParkingEdge(edge_id="EDGE-1", tenant_id=tenant.id, site_id=site.id, name="Edge 1")
    db.add(edge)
    db.commit()

    edge_rt = _edge(tmp_path, site_id=site.id, edge_id="EDGE-1")
    edge_rt.offline_entry(plate="B1234ABC", vehicle_type="CAR", site_id=site.id, gate_id=1, lane_id=1)
    batch = edge_rt.sync_batch()
    assert len(batch) == 1

    central = CentralSyncService(db, scope(tenant))
    rec = central.receive_batch(edge_id="EDGE-1", site_id=site.id, events=batch)
    assert len(rec.acknowledged) == 1
    assert rec.conflicts == []

    # Edge marks synced after ACK.
    edge_rt.process_ack({"acknowledged": rec.acknowledged, "conflicts": []})
    assert edge_rt.store.queue_depth() == 0


def test_duplicate_sync_idempotent(tmp_path, db):
    tenant = new_tenant(db, code="T1")
    site = new_site(db, tenant, code="S1")
    from parking.models import ParkingEdge
    db.add(ParkingEdge(edge_id="EDGE-1", tenant_id=tenant.id, site_id=site.id, name="Edge 1"))
    db.commit()

    edge_rt = _edge(tmp_path, site_id=site.id, edge_id="EDGE-1")
    edge_rt.offline_entry(plate="B1234ABC", vehicle_type="CAR", site_id=site.id, gate_id=1, lane_id=1)
    batch = edge_rt.sync_batch()

    central = CentralSyncService(db, scope(tenant))
    rec1 = central.receive_batch(edge_id="EDGE-1", site_id=site.id, events=batch)
    rec2 = central.receive_batch(edge_id="EDGE-1", site_id=site.id, events=batch)
    assert len(rec1.acknowledged) == 1
    assert len(rec2.acknowledged) == 1  # duplicate acknowledged, no double apply
    assert rec2.conflicts == []


def test_partial_ack_preserves_unacknowledged(tmp_path):
    edge = _edge(tmp_path)
    edge.offline_entry(plate="B1234ABC", vehicle_type="CAR", site_id=1, gate_id=1, lane_id=1)
    edge.offline_entry(plate="B9999ZZ", vehicle_type="CAR", site_id=1, gate_id=1, lane_id=1)
    batch = edge.sync_batch()
    # Central acknowledges only the first event.
    edge.process_ack({"acknowledged": [batch[0]["event_id"]], "conflicts": []})
    assert edge.store.queue_depth() == 1
    remaining = edge.store.pending_events()
    assert remaining[0]["event_id"] == batch[1]["event_id"]


def test_sequence_tracking(tmp_path):
    edge = _edge(tmp_path)
    e1 = edge.offline_entry(plate="B1234ABC", vehicle_type="CAR", site_id=1, gate_id=1, lane_id=1)
    e2 = edge.offline_entry(plate="B9999ZZ", vehicle_type="CAR", site_id=1, gate_id=1, lane_id=1)
    assert e1.sequence_number == 1
    assert e2.sequence_number == 2


def test_conflicting_event_machine_readable(tmp_path, db):
    tenant = new_tenant(db, code="T1")
    site = new_site(db, tenant, code="S1")
    from parking.models import ParkingEdge
    db.add(ParkingEdge(edge_id="EDGE-1", tenant_id=tenant.id, site_id=site.id, name="Edge 1"))
    db.commit()

    central = CentralSyncService(db, scope(tenant))
    # Unknown session exit -> UNKNOWN_SESSION conflict.
    rec = central.receive_batch(edge_id="EDGE-1", site_id=site.id, events=[{
        "event_id": "EVT-1", "sequence_number": 1, "event_type": "EXIT",
        "occurred_at": datetime.now(timezone.utc).isoformat(),
        "payload": {"public_reference": "PK-NOPE"},
    }])
    assert len(rec.conflicts) == 1
    assert rec.conflicts[0]["class"] == ConflictClass.UNKNOWN_SESSION.value


def test_stale_config_rejected(tmp_path):
    store = _store(tmp_path)
    store.set_identity(edge_id="EDGE-1", tenant_id=1, site_id=1)
    store.accept_config(config_version=2, site_id=1,
                        generated_at=datetime.now(timezone.utc).isoformat(), payload=_config(1, version=2))
    # Older version rejected.
    assert store.accept_config(config_version=1, site_id=1,
                              generated_at=datetime.now(timezone.utc).isoformat(), payload=_config(1, version=1)) is False


def test_clock_skew_detected(tmp_path):
    edge = _edge(tmp_path)
    # Server time 1 hour ahead -> skew.
    skewed = datetime.now(timezone.utc) + timedelta(hours=1)
    assert edge.detect_clock_skew(skewed) is True
    # Normal server time -> no skew.
    normal = datetime.now(timezone.utc)
    assert edge.detect_clock_skew(normal) is False


def test_foreign_edge_site_spoof_blocked(tmp_path, db):
    tenant = new_tenant(db, code="T1")
    site = new_site(db, tenant, code="S1")
    from parking.models import ParkingEdge
    db.add(ParkingEdge(edge_id="EDGE-1", tenant_id=tenant.id, site_id=site.id, name="Edge 1"))
    db.commit()
    central = CentralSyncService(db, scope(tenant))
    # Edge claims a different site than it is assigned to.
    with pytest.raises(ParkingError) as exc:
        central.receive_batch(edge_id="EDGE-1", site_id=999, events=[])
    assert exc.value.code == ErrorCode.EDGE_NOT_AUTHORIZED
    assert exc.value.status == 403


def test_bounded_batching(tmp_path):
    edge = _edge(tmp_path)
    for i in range(10):
        edge.offline_entry(plate=f"B{i:04d}ZZ", vehicle_type="CAR", site_id=1, gate_id=1, lane_id=1)
    batch = edge.sync_batch(max_events=3)
    assert len(batch) == 3


def test_unsynced_event_never_removed_by_cleanup(tmp_path):
    edge = _edge(tmp_path)
    edge.offline_entry(plate="B1234ABC", vehicle_type="CAR", site_id=1, gate_id=1, lane_id=1)
    # Compact synced events; unsynced must remain.
    edge.store.compact_synced(keep=0)
    assert edge.store.queue_depth() == 1
