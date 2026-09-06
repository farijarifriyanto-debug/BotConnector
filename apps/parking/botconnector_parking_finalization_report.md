# BotConnector Parking V1 — Master Finalization & Release Audit Report

**Auditor:** Gemini (Release Auditor / Finalizer)  
**Date:** 2026-08-29  
**Initial Baseline SHA:** `4a038941d522ad8749cb628b3a02085b2b819821`  
**Final Audit SHA:** `7738a77bbeff31ec937ba5220ff8ce200b19c5fc`  
**Dedicated Database:** PostgreSQL `botconnector_parking` (Port `55432`)  
**Test Database:** PostgreSQL `botconnector_parking_test` (Port `55432`)  
**Migration Head:** `0004`  

---

## Executive Release Verdict

| Dimension | Decision | Rationale |
|---|---|---|
| **SOFTWARE_RELEASE_READY** | **YES** | 139/139 automated tests pass. Tenant isolation, RBAC, state machine invariants, integer IDR tariff arithmetic, callback verification, edge durability, and export sanitization fully verified. |
| **INTERNAL_RUNTIME_READY** | **YES** | Local isolated service (`127.0.0.1:8711`), liveness/readiness endpoints operational, console UI validated across desktop/mobile viewports with zero console errors. |
| **PUBLIC_WEB_CUTOVER_READY** | **YES** | Ready for publication upon operator sign-off; public nginx routing, homepage product card, and catalog links remain untouched pending approval. |
| **PHYSICAL_SITE_GO_LIVE_READY** | **NO** | Physical barrier controllers, ONVIF Profile M cameras, and loop sensors pending on-site physical hardware deployment. |
| **REAL_QRIS_GO_LIVE_READY** | **NO** | Real acquirer/PJP production credentials and merchant onboarding pending; QRIS MPM/CPM contracts verified via deterministic simulator. |

---

## A. Source State & Traceability

- **Baseline Tests:** 136 / 136 PASS (DeepSeek baseline)
- **Final Audit Tests:** 139 / 139 PASS (0 FAIL, 2 benign deprecation warnings)
- **Files Changed:**
  - `parking/api/admin.py` (Enforced ADMIN/MANAGER roles, blocked operator role escalation)
  - `parking/api/tariffs.py` (Enforced MANAGER role on tariff plan/rule mutations)
  - `parking/api/sessions.py` (Enforced OPERATOR/SUPERVISOR roles on state mutations)
  - `parking/ops/reports.py` (Hardened CSV formula-injection neutralization)
  - `scripts/backup.sh` (Dynamic database user extraction from connection URL)
  - `tests/helpers.py` (Added role parameter to `new_operator`)
  - `tests/test_api.py` (Added API role authorization & escalation regression tests)

---

## B. Specifications Reviewed

1. **BotConnector Parking Master Specification (M1–M12)**
2. **Candidate Release Artifact (`botconnector_parking_candidate_release_report.md`)**
3. **Database Migration Baseline (0001–0004)**
4. **ONVIF Profile M (Metadata/ANPR) & Profile D (Access Control Peripheral) Contracts**
5. **QRIS MPM/CPM Payment Integration Specifications**

---

## C. M1–M12 Full Traceability Matrix

| Milestone | Module | Database Entities | Domain Commands / API | Tests | Status |
|---|---|---|---|---|---|
| **M1 Foundation** | `parking.models`, `parking.domain` | `parking_tenant`, `parking_site`, `parking_gate`, `parking_lane`, `parking_operator`, `parking_vehicle`, `parking_shift` | `POST /sites`, `POST /sites/{id}/gates`, `POST /sites/{id}/lanes`, `POST /operators` | `tests/test_foundation.py` | **PASS** |
| **M2 Session Engine** | `parking.services.session_service`, `parking.services.entry` | `parking_session`, `parking_event`, `parking_audit_log`, `uq_parking_session_active_vehicle` | `POST /sessions/entry`, `POST /sessions/{ref}/cancel` | `tests/test_session_engine.py` | **PASS** |
| **M3 Tariff Engine** | `parking.tariff.engine`, `parking.tariff.snapshot` | `parking_tariff_plan`, `parking_tariff_rule` | `POST /sessions/{ref}/calculate`, snapshot freeze/reproduce | `tests/test_tariff.py` | **PASS** |
| **M4 Gate Runtime** | `parking.gate.runtime` | `parking_gate_runtime`, `parking_lane_runtime`, `parking_idempotency_record` | `GateRuntimeService.entry_request` | `tests/test_gate_runtime.py` | **PASS** |
| **M5 Exit Runtime** | `parking.exit.runtime` | `parking_exit_quote` | `ExitRuntimeService.create_exit_quote`, `exit_decision`, `authorize_exit` | `tests/test_exit_runtime.py` | **PASS** |
| **M6 Payment Runtime** | `parking.payment.service` | `parking_payment`, `parking_payment_attempt`, `parking_payment_event` | `PaymentService.create_payment`, `confirm_cash`, `handle_callback` | `tests/test_payment_runtime.py` | **PASS** |
| **M7 ANPR Runtime** | `parking.anpr.service` | `parking_anpr_event`, `parking_anpr_correction` | `AnprService.process`, `list_review`, `correct_plate` | `tests/test_anpr_runtime.py` | **PASS** |
| **M8 Device Runtime** | `parking.device.service` | `parking_device`, `parking_device_runtime`, `parking_barrier_command` | `BarrierService.dispatch`, `acknowledge`, `report_physical_state` | `tests/test_device_runtime.py` | **PASS** |
| **M9 Offline Edge** | `parking.edge.runtime`, `parking.edge.store` | SQLite store + `parking_edge`, `parking_edge_sync_event` | `EdgeRuntime.offline_entry`, `offline_exit`, `CentralSyncService.receive_batch` | `tests/test_edge_runtime.py` | **PASS** |
| **M10 Dashboard** | `parking.ops.dashboard`, `parking.static` | Real-time session & device aggregates | `GET /sites/{id}/dashboard`, `GET /sites/{id}/live`, `/parking/console/` | `tests/test_dashboard.py` | **PASS** |
| **M11 Reports & Audit** | `parking.ops.reports` | Immutable payment, session, audit records | `GET /sites/{id}/reports/*`, `GET /audit`, `GET /reports/daily/export` | `tests/test_reports.py` | **PASS** |
| **M12 Production Readiness** | `parking.ops.readiness` | System health & deployment packages | `GET /parking/api/liveness`, `GET /parking/api/readiness` | `tests/test_readiness.py` | **PASS** |

---

## D. Genuine Defects Found & Repaired

1. **Role Authorization on Administrative and Mutating Endpoints:**
   - *Defect:* `POST /sites`, `POST /sites/{id}/gates`, `POST /sites/{id}/lanes`, `POST /operators`, `POST /sites/{id}/tariff-plans`, and session mutation routes lacked explicit server-side role checks.
   - *Repair:* Added `require_role(scope, "ADMIN")` to site and operator creation; `require_role(scope, "MANAGER")` to gates, lanes, and tariff configurations; `require_role(scope, "OPERATOR")` to entry/payment/exit mutations; and `require_role(scope, "SUPERVISOR")` to cancellation and complimentary waivers.
   - *Escalation Guard:* Added validation in `create_operator` preventing operators from creating accounts with higher privilege than their own.

2. **CSV Formula Injection Hardening:**
   - *Defect:* Formula neutralization (`_safe_cell`) checked only immediate prefix characters, vulnerable to whitespace padding (e.g. ` =SUM(1,1)` or `\t=cmd`).
   - *Repair:* Hardened `_safe_cell` to strip leading whitespace before checking for formula symbols (`=`, `+`, `-`, `@`) and neutralized leading control characters (`\t`, `\r`, `\n`).

3. **Backup Script User Parsing:**
   - *Defect:* `scripts/backup.sh` hardcoded `-U parking` regardless of the user defined in `PARKING_DATABASE_URL`.
   - *Repair:* Extracted DB username dynamically from the connection URL with fallback to `parking`.

---

## E. Architectural & Security Verification Summary

- **Tenant Isolation:** Deny-by-default, 404 semantics on foreign tenant lookups. Zero cross-tenant data leaks.
- **Session Concurrency:** Database-level partial unique index `uq_parking_session_active_vehicle` blocks duplicate active sessions under concurrency.
- **Monetary Precision:** Exact integer IDR; floating-point math completely prohibited.
- **Tariff Reproducibility:** Historical quotes frozen in JSON snapshots; live plan changes do not mutate old bills.
- **Gate Separation:** ANPR events and device adapters cannot authorize access or mark payments paid. Only Central/Edge runtime domain state machine creates admission and barrier action intents.
- **Barrier Safety:** Default failure policy is `FAIL_CLOSED`. Loss of network never triggers unintended gate opening.
- **Edge Durability:** Events persisted to SQLite WAL queue before operations are accepted. Offline queue survives crash/restart.
- **Secret Hygiene:** Zero embedded production secrets. All credentials managed via external environment files or secret references.

---

## F. Hardware & Payment Compatibility Status

- **ANPR Cameras:** `PROFILE_M_CONTRACT_READY=PASS`, `REAL_CAMERA_VERIFIED=NO`
- **Barrier Controllers:** `PROFILE_D_CONTRACT_READY=PASS`, `REAL_BARRIER_VERIFIED=NO`
- **Loop Sensors / Peripherals:** `CONTRACT_VERIFIED=PASS`, `PHYSICAL_TEST_PENDING`
- **QRIS Payment MPM/CPM:** `QRIS_MPM_SOFTWARE_READY=PASS`, `QRIS_CPM_SOFTWARE_READY=PASS`, `REAL_PJP_CONFIGURED=NO`, `REAL_QRIS_GO_LIVE_READY=NO`
- **Overall Hardware Acceptance:** `PHYSICAL_HARDWARE_ACCEPTANCE=PENDING_REAL_HARDWARE`

---

## G. Production & System Safety

- **Production Systems Touched:** `NO` (BotConnector main, AI Support, Business Suite unaffected)
- **OlahDokumen Touched:** `NO` (Document Assistant and related services untouched)
- **Public Cutover Performed:** `NO` (No public nginx routes, no homepage links, waiting for user cutover command)
- **Disk Availability:** 8.1 GB free on root filesystem.

---

## H. Next Recommended Real-World Steps

1. **Physical Site Deployment:** Connect physical IP ANPR camera and barrier controller to local site Edge gateway on site-local subnet.
2. **PJP Onboarding:** Provision merchant credentials with licensed payment partner (e.g., Midtrans / Xendit / Bank PJP) and configure production signing keys.
3. **Controlled Public Exposure:** Upon operational acceptance, add `/parking/` route to production reverse proxy and enable portal entry in BotConnector console.
