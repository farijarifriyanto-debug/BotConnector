# BotConnector Parking — M1–M12 (candidate release)

Isolated, generic multi-tenant/multi-site parking platform. **M1–M12**:
no ANPR hardware, no barriers, no real payment, no public exposure.

- M1: tenant/site/gate/lane/operator/shift foundation + plate normalization.
- M2: session lifecycle state machine, duplicate-entry guard (DB partial unique index
  `uq_parking_session_active_vehicle`), event ledger, audit log, cross-tenant isolation.
- M3: pure tariff engine (FLAT / HOURLY / PROGRESSIVE), grace period, daily maximum,
  lost-ticket fee, complimentary, integer IDR, frozen tariff snapshots.
- M4: gate runtime — admission decisions (ALLOW/DENY/MANUAL_REVIEW), gate/lane runtime
  state, request-level idempotency, barrier ACTION INTENT (no physical barrier).
- M5: exit runtime — authoritative exit quote, quote expiry/recalculation,
  payment-required flow, server-side exit authorization, idempotent exit completion.
- M6: payment runtime — provider-neutral adapters (CASH / QRIS_MPM_DYNAMIC /
  QRIS_CPM / COMPLIMENTARY), simulated provider, secure callback verification,
  payment idempotency, double-payment guard, payment→exit transactionality.
- M7: ANPR runtime — vendor-neutral adapters (Simulated / ONVIF Profile M), confidence
  policy, event idempotency, audited manual plate correction. ANPR never authorizes a gate.
- M8: device/barrier runtime — device registry, runtime health, explicit auditable
  barrier commands (OPEN/CLOSE/STATUS), idempotency, ACK vs physical state, fail policy,
  ONVIF Profile D contract.
- M9: offline Edge Gateway — durable SQLite store, offline entry/exit, at-least-once sync,
  central idempotency, partial ACK, sequence tracking, conflict handling, clock skew.
- M10: dashboard & operator console — occupancy (derived from active sessions), live
  parking, gate/device health, ANPR review, role-aware authorization, responsive UI.
- M11: reports/operations/audit — daily ops, revenue, payment, gate, ANPR, edge reports,
  searchable audit, CSV export (formula-injection safe), UTC-canonical timezone.
- M12: production & hardware readiness — deployment packages, liveness/readiness, backup,
  hardware compatibility matrix, failure matrix, security self-audit, performance smoke.

## Layout

```
parking/
  api/        FastAPI routes (all under /parking/api) + auth scope
  domain/     enums, errors, state machine, money, plate normalization
  models/     SQLAlchemy entities (12 tables + M4-M6 runtime/payment tables)
  repositories/  tenant-scoped data access
  services/   entry, session lifecycle, tariff calculation
  tariff/     config validation, pure engine, snapshot freeze/reproduce
  gate/       M4 gate runtime: admission, idempotency, barrier intent
  exit/       M5 exit runtime: quote, authorization, completion
  payment/    M6 payment runtime: adapters, simulator, service
  anpr/       M7 ANPR runtime: adapters, confidence, idempotency, correction
  device/     M8 device/barrier runtime: registry, commands, adapters
  edge/       M9 offline edge gateway: SQLite store, sync, reconciliation
  ops/        M10-M11 dashboard + reports + M12 readiness matrix
  static/     M10 operator console (HTML/CSS/JS)
tests/        M1-M12 acceptance suite (runs against botconnector_parking_test)
alembic/      schema migrations (0001-0004)
deploy/       systemd unit templates (artifacts, not auto-installed)
scripts/      bootstrap.py, migrate.sh, test.sh, backup.sh
```

## Operations (VPS)

```bash
# migrate the dedicated Parking DB
scripts/migrate.sh

# acceptance suite against the TEST database (never prod)
scripts/test.sh

# first tenant + admin operator (writes token to ~/.botconnector/parking.dev.operator.token)
.venv/bin/python scripts/bootstrap.py DEMO "Demo Tenant" admin
```

Test bootstrap drops/recreates the test schema via `alembic upgrade head`,
so the migration itself is exercised by CI.

## Security posture

- Credentials only in root-only `/etc/botconnector/parking.env` (or `~/.botconnector/parking.env`).
- Bearer token → sha256 hash → operator → server-derived tenant scope. Client-supplied
  tenant_id is never trusted; every lookup is tenant-scoped with 404 semantics.
- No generic PATCH on sessions; every mutation is a named, state-machine-validated command.
- SQLAlchemyError handler returns a fixed 500 payload — no SQL leakage.
