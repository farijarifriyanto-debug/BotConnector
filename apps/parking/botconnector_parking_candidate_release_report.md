# BotConnector Parking V1 — Candidate Release Report

**Status:** CANDIDATE RELEASE (software/harness/readiness acceptance passed)
**Next step:** Gemini finalization / release audit
**Date:** 2026-08-29

---

## 1. Architecture Summary

Isolated, generic multi-tenant/multi-site parking platform. Backend is FastAPI +
SQLAlchemy + PostgreSQL (dedicated `botconnector_parking`). Edge Gateway is a
separate site-local runtime with a durable SQLite store. All domain logic is
tenant-scoped; cross-tenant access is blocked with 404 semantics.

```
parking/
  api/        FastAPI routes (all under /parking/api) + auth scope + static console
  domain/     enums, errors, state machine, money, plate normalization
  models/     SQLAlchemy entities (M1-M12)
  repositories/  tenant-scoped data access
  services/   entry, session lifecycle, tariff, auth (role-aware)
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
alembic/      schema migrations 0001-0004
deploy/       systemd unit templates (artifacts, not auto-installed)
scripts/      bootstrap.py, migrate.sh, test.sh, backup.sh
```

## 2. M1–M12 Implementation Status

| Milestone | Status |
|---|---|
| M1 Foundation | PASS |
| M2 Session Engine | PASS |
| M3 Tariff Engine | PASS |
| M4 Gate Runtime | PASS |
| M5 Exit Runtime | PASS |
| M6 Payment Runtime | PASS |
| M7 ANPR Runtime | PASS |
| M8 Device/Barrier Runtime | PASS |
| M9 Offline Edge Gateway | PASS |
| M10 Dashboard & Operator Console | PASS |
| M11 Reports / Operations / Audit | PASS |
| M12 Production & Hardware Readiness | PASS |

## 3. Database Migrations

| Migration | Scope |
|---|---|
| 0001 | M1-M3 foundation (12 tables) |
| 0002 | M4-M6 gate/exit/payment runtime |
| 0003 | M7-M9 device/ANPR/barrier/edge |
| 0004 | M10-M12 site capacity + role expansion |

All migrations upgrade and downgrade cleanly. Dedicated DB: `botconnector_parking`.

## 4. UI Screenshots

Saved in `.playwright-mcp/` (small, bounded set):
- `parking-desktop-final.png` (1440px)
- `parking-mobile.png` (390px)

Verified: zero console errors, no horizontal overflow at 1440/1024/768/390,
44px touch targets, visible keyboard focus.

## 5. Reports List

- Daily Operations
- Revenue (by method, integer IDR)
- Payment reconciliation (by state)
- Gate Performance (SIMULATED source labeled)
- ANPR (real_world_accuracy=NOT_MEASURED)
- Edge (synced events, last seen)
- Audit (searchable, tenant-scoped)
- CSV export (formula-injection safe)

## 6. API / Runtime Components

- `/parking/api/health`, `/liveness`, `/readiness`
- `/parking/api/sites/{id}/dashboard`, `/live`, `/devices`, `/edges`
- `/parking/api/sites/{id}/reports/*`
- `/parking/api/audit`
- `/parking/api/anpr/review`, `/anpr/{id}/correct`
- `/parking/console/` (static operator console)
- Edge: `parking.edge.run` entrypoint + `EdgeStore` (SQLite WAL)

## 7. ANPR / Barrier / Edge Status

- **ANPR:** vendor-neutral adapters (Simulated + ONVIF Profile M). Confidence
  policy (AUTO_CANDIDATE / MANUAL_REVIEW / REJECT). ANPR never authorizes a gate.
- **Barrier:** device registry, explicit auditable commands (OPEN/CLOSE/STATUS),
  idempotency, ACK distinct from physical state, FAIL_CLOSED default.
- **Edge:** durable SQLite queue, offline entry/exit, at-least-once sync, central
  idempotency, partial ACK, sequence tracking, conflict handling, clock skew.

## 8. Hardware Compatibility Matrix

| Category | Interface | Standard | Tested | Physical |
|---|---|---|---|---|
| ANPR Camera | ANPRAdapter.parse | ONVIF Profile M | SIMULATOR_VERIFIED | PENDING |
| Barrier Controller | BarrierAdapter | ONVIF Profile D | SIMULATOR_VERIFIED | PENDING |
| Loop Sensor | sensor event | generic | CONTRACT_VERIFIED | PENDING |
| QR Scanner | PaymentAdapter | QRIS MPM/CPM | SIMULATOR_VERIFIED | PENDING |
| Edge Device | EdgeRuntime | site-local | SIMULATOR_VERIFIED | PENDING |

**ONVIF conformance is NOT claimed** without authoritative testing.

## 9. Payment Status

- CASH: fully functional in software.
- COMPLIMENTARY: explicit audited settlement.
- QRIS MPM/CPM: provider-neutral contract + deterministic simulator.
- **No real QRIS transaction processed.** REAL_PAYMENT_USED=NO.

## 10. Security Boundaries

- Tenant isolation enforced server-side (404 semantics, no existence leak).
- Role-based authorization (OWNER/ADMIN/MANAGER/SUPERVISOR/OPERATOR/VIEWER).
- VIEWER is read-only; no arbitrary state PATCH.
- Payment callback security: signature + server-to-server verify + amount/currency
  match + replay protection.
- No credentials in source; secret-reference architecture.
- CSV formula-injection safe.

## 11. Backup / Recovery

- `scripts/backup.sh`: pg_dump of Parking DB + SQLite backup of Edge.
- Edge restart durability verified (unsynced queue survives reopen).
- Central restart-safe (migration idempotent, state intact).
- Isolated restore verification performed in tests.

## 12. Known Limitations

- ANPR accuracy is simulator-only (`REAL_WORLD_ACCURACY=NOT_MEASURED`).
- No physical hardware tested.
- No real QRIS/payment provider integration.
- Operator console is a static monitoring UI; financial actions remain
  backend-command driven (no direct state mutation from UI).

## 13. Physical Hardware Pending Items

- ANPR camera physical test
- Barrier controller physical test
- Loop sensor physical test
- QR scanner physical test
- Edge device deployment at a real site

## 14. Gemini Finalization Checklist

- [ ] Review candidate release artifact
- [ ] Controlled cutover decision (no public exposure yet)
- [ ] Physical hardware acceptance (if hardware available)
- [ ] Real payment provider integration (if approved)
- [ ] Final security audit
- [ ] Production deployment packaging review
