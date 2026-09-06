# Source Map

Generated during Phase 2–4 of the BotConnector Platform consolidation
(2026-09-06). Read-only investigation against live systemd units, nginx
config, and on-disk layout — no runtime was modified to produce this.

**COMPONENTS_TOTAL=21** (current, authoritative — grew from the original
19-component skeleton after `apps/integrasi` was identified as a distinct
live deployable (→20), then again after `apps/homepage-runtime` was
identified and imported 2026-09-06 (→21); see the business-suite/integrasi
and homepage-runtime entries below).

```
COMPONENTS_TOTAL=21
DEPLOYABLE_COMPONENTS_TOTAL=20 (packages/shared-design remains the one non-deployable static asset package)
NON_DEPLOYABLE_COMPONENTS=1 (packages/shared-design)
```

Format per component:

```
COMPONENT=
ORIGINAL_SOURCE=
LIVE_SYMLINK=          (only if the live path was a `current` symlink)
RESOLVED_SOURCE=       (the real dereferenced release dir actually imported)
CANONICAL_TARGET=
LIVE_RUNTIME=
LIVE_ROUTE=
PROVENANCE_CONFIDENCE=
NOTES=
```

---

COMPONENT=public-site
ORIGINAL_SOURCE=/home/botadmin/ai-workspaces/botconnector-full-site-poc
RESOLVED_SOURCE=(same, not a symlink)
CANONICAL_TARGET=apps/public-site
LIVE_RUNTIME=NONE — this POC is not deployed anywhere
LIVE_ROUTE=NONE — **CORRECTED 2026-09-06**: the live botconnector.id apex is NOT a static deployment artifact as previously stated here. It is served by a real, dynamic application — see the new `COMPONENT=homepage-runtime` entry immediately below and the full audit in `docs/provenance/HOMEPAGE-CONVERGENCE.md`. The earlier "no generator/source repo found behind any live /var/www/botconnector* root" finding was correct as far as it checked (those `/var/www` paths genuinely are static output), but it never checked where nginx's `location /` actually proxies to — which is a live Docker container, not those static paths.
PROVENANCE_CONFIDENCE=MEDIUM (unchanged for this component's own POC status — apps/public-site itself is still confirmed static-only with zero forms/JS calls)
NOTES=Classified FUTURE_CANONICAL_SOURCE per explicit user decision — that classification still stands for the STATIC/PRESENTATION content this candidate provides, but it is not a drop-in replacement for the live apex, which carries real auth/session/gateway/support functionality this candidate does not implement. See HOMEPAGE-CONVERGENCE.md's convergence decision (OPTION_B_FRONTEND_BACKEND_SPLIT) before any apex cutover is planned.

---

COMPONENT=apps/homepage-runtime (IMPORTED 2026-09-06)
ORIGINAL_SOURCE=/opt/botconnector-platform-starter-v0.3/homepage
RESOLVED_SOURCE=/opt/botconnector-platform-starter-v0.3/homepage/app (the package actually running in the live container)
CANONICAL_TARGET=apps/homepage-runtime/ (imported via COPY, canonical source only — old source never moved, never modified)
LIVE_RUNTIME=Docker container `botconnector-platform-home`, image `botconnector-platform-home:tenantization-v1-20260828`, uvicorn `app.main:app`, port 127.0.0.1:8020
LIVE_ROUTE=botconnector.id apex (`location /` in nginx), plus `/products`, `/login`, `/register`, `/support`, `/docs`, `/status`, `/app/{slug}/...` (application gateway to business-suite/parking/webhook-connector/langkah/business-automation/personal-automation/monitor-resolve, per `core_bridge.py`'s routing table), and more — see HOMEPAGE-CONVERGENCE.md for the full route inventory
PROVENANCE_CONFIDENCE=HIGH — hash-verified: all 94 files under the source's `app/` directory match the live image's `/app/app` contents byte-for-byte (SHA256), captured via a throwaway `docker run --rm` inspection, the live container itself untouched
SOURCE_DELIVERY_MODE=baked into the Docker image at build time (not a live bind-mount)
ENTRYPOINT=app/main.py (`uvicorn app.main:app`)
DOCKERFILE=apps/homepage-runtime/Dockerfile (identical to the live source's Dockerfile — `python:3.12-slim`, copies `requirements.txt`, `app/`, `tests/`)
COMPOSE_FILE=apps/homepage-runtime/docker-compose.yml (production reference — mounts `/etc/botconnector/credentials/{homepage-db-password,redis-password}` read-only to `/run/secrets/*`, plus `/var/lib/botconnector-platform` and two external networks; NOT used for this session's isolated proof, which used plain `docker run` with ephemeral Postgres/Redis instead)
DEPENDENCY_MANIFEST=apps/homepage-runtime/requirements.txt (pre-existing, direct/intent, already near-exact pins) + apps/homepage-runtime/requirements.lock.txt (new, exact pins captured from the live image: Python 3.12.13)
NOTES=Real, load-bearing platform infrastructure: session/auth issuance (`bc_session` cookie — the same cookie name used elsewhere in the platform), Postgres and Redis backed, and the actual gateway customers go through to reach Business Suite/Parking/etc. Classified `ACTIVE_LIVE_SOURCE_PENDING_CONVERGENCE` — not a delete candidate. **Security finding, fixed in the canonical copy only**: `app/support.py` had a hardcoded, real-looking SMTP password as the fallback default for `SMTP_PASSWORD` (confirmed not overridden by any `.env` on the box, meaning the hardcoded literal was the value actually in live use) — replaced with an empty-string safe default in the canonical copy, matching the same no-default pattern this file already correctly used for its Postgres/Redis passwords. The live source at `/opt/botconnector-platform-starter-v0.3/homepage` was NOT modified — this fix exists only in `apps/homepage-runtime`. Two open questions before this component is used for anything beyond documentation: whether its Drive-sharing suite overlaps with `apps/drive`, and whether its SmartBiz/AI-widget modules overlap with Business Suite or the excluded internal AI cluster (see `docs/architecture/PUBLIC-SITE-RUNTIME-CONTRACT.md` and `docs/capability-registry/CAPABILITIES.md` for what's classified so far).
BUILD_PROOF=PASS — `docker build` from `apps/homepage-runtime` only (no reference to the old `/opt` source in the build), image ran isolated against ephemeral, disposable Postgres + Redis (random ports, dummy credentials, never the real ones) and `/health`, `/login`, `/register`, `/products`, `/app` (gateway — correctly redirected unauthenticated requests to `/login`, HTTP 303), and `/support` all loaded successfully (HTTP 200 or a correct redirect). No production Postgres/Redis was touched. Everything (container, image, ephemeral DB/Redis) was removed after the proof.

---

COMPONENT=store
ORIGINAL_SOURCE=/home/botadmin/botconnector-store-production-v6r3-final
RESOLVED_SOURCE=(same, not a symlink)
CANONICAL_TARGET=apps/store
LIVE_RUNTIME=botconnector-store.service (systemd, enabled/active)
LIVE_ROUTE=/store/, /konektor/ (root /var/www/botconnector-store/current)
PROVENANCE_CONFIDENCE=HIGH
NOTES=Live deployment output lives at /var/www/botconnector-store/current, separate from this source tree — deployment artifact, not re-imported.

---

COMPONENT=restaurant (Restaurant Seller Control — NOT the Restaurant POS feature)
ORIGINAL_SOURCE=/opt/restaurant-seller-control
RESOLVED_SOURCE=(same, not a symlink)
CANONICAL_TARGET=apps/restaurant
LIVE_RUNTIME=Docker container `restaurant-seller-control` (up 7d at time of check), health on 127.0.0.1:18192 — not a systemd unit
LIVE_ROUTE=/panel/restaurant/ (nginx proxy_pass to 127.0.0.1:18192)
PROVENANCE_CONFIDENCE=HIGH
NOTES=CORRECTED 2026-09-06 (was misidentified earlier as the restaurant POS/KDS app): reading apps/restaurant/app/app.py shows this is a licensing/entitlement admin panel — `licenses.db`, EC-signed license keys, edition tiers (Essential, Lengkap, Professional, Multi Outlet), seller admin auth. It has nothing to do with kitchen/table/menu operations. The actual Restaurant POS/KDS capability the public site markets lives inside Business Suite (`/bisnis/api/restaurant`, `/bisnis/api/kitchen`) — see the business-suite entry below. Some files (backup.sh, rollback-remove.sh, status.sh) are root-owned 700; read via scoped read-only sudo per explicit grant, backup/import are COMPLETE not partial.

---

COMPONENT=business-suite
ORIGINAL_SOURCE=/opt/botconnector-bisnis (systemd WorkingDirectory)
RESOLVED_SOURCE=/opt/botconnector-bisnis/app.py (single-file entrypoint, 3588 lines)
CANONICAL_TARGET=apps/business-suite
LIVE_RUNTIME=botconnector-bisnis.service (systemd, enabled/active, `Requires=botconnector-finance-core.service`), uvicorn `app:APP --app-dir /opt/botconnector-bisnis` on 127.0.0.1:18199, DB credential loaded via systemd `LoadCredential` from `/etc/botconnector/credentials/bisnis-db-password` (not a plain .env)
LIVE_ROUTE=/bisnis/ (PWA shell + `/bisnis/api/*`: state, products, inventory, sales, transfers, restaurant, kitchen, offline/sync)
PROVENANCE_CONFIDENCE=HIGH — CONFIRMED END-TO-END 2026-09-06
NOTES=BUSINESS_SUITE_SOURCE=THIN_ENTRYPOINT_PLUS_MULTICHANNEL. The entrypoint does `sys.path.insert(0, "/opt")` then `import botconnector_multichannel...`, which resolves via the `/opt/botconnector_multichannel` (underscore) symlink to `/opt/botconnector-multichannel` (hyphen) — proven by directly resolving the symlink, not inferred. Runs on the Multichannel package's own venv interpreter (`/opt/botconnector-multichannel/venv/bin/python`), so it has no independent dependency set of its own — DEPENDENCIES_IDENTIFIED should be read against packages/multichannel, not this directory (which itself has no requirements.txt). Live health check at time of audit: `{"ok":true,"service":"botconnector-business-suite","database":"connected"}`.

---

COMPONENT=integrasi
ORIGINAL_SOURCE=/opt/botconnector-integrasi (systemd WorkingDirectory)
RESOLVED_SOURCE=/opt/botconnector-integrasi/app.py (single-file entrypoint, 145 lines)
CANONICAL_TARGET=apps/integrasi (created — not part of the original Phase 3 skeleton, added because it is a distinct live deployable with its own systemd unit; see CURRENT-STATE.md)
LIVE_RUNTIME=botconnector-integrasi.service (systemd, enabled/active, `Requires=botconnector-finance-core.service`), uvicorn `app:APP --app-dir /opt/botconnector-integrasi` on 127.0.0.1:18198
LIVE_ROUTE=/integrasi/, /api/public/state, /api/public/inventory
PROVENANCE_CONFIDENCE=HIGH — CONFIRMED END-TO-END 2026-09-06
NOTES=Same thin-entrypoint-over-Multichannel pattern as business-suite (same `/opt` sys.path trick, same symlink). Its own docstring: "Read-only. Tidak memanggil keluar. Tidak membuka token." The marketplace cards it renders (Shopee, Tokopedia, TikTok Shop, Blibli, Lazada) are hardcoded status="SEGERA_HADIR" (Coming Soon) with the code comment "no real external connection yet" — confirmed NOT live by reading the source directly, not inferred. Live health check: `{"ok":true,"service":"botconnector-integrasi"}`.

---

COMPONENT=parking
ORIGINAL_SOURCE=/home/botadmin/ai-workspaces/BotConnector-Parking
RESOLVED_SOURCE=(same, not a symlink)
CANONICAL_TARGET=apps/parking
LIVE_RUNTIME=botconnector-parking.service (systemd, enabled/active), WorkingDirectory = this same path
LIVE_ROUTE=NOT VERIFIED in this pass (not re-checked against nginx)
PROVENANCE_CONFIDENCE=HIGH
NOTES=Full git history preserved separately as a verified git bundle in the Phase 2 backup (parking-history.bundle, PASS). The .git directory was intentionally excluded from the monorepo copy to avoid a nested repo.

---

COMPONENT=drive
ORIGINAL_SOURCE=/opt/botconnector-drive
RESOLVED_SOURCE=(same, not a symlink)
CANONICAL_TARGET=apps/drive
LIVE_RUNTIME=botconnector-drive.service (systemd, enabled/active), WorkingDirectory = this same path
LIVE_ROUTE=NOT VERIFIED in this pass
PROVENANCE_CONFIDENCE=HIGH
NOTES=(none)

---

COMPONENT=ai-chat-preview
ORIGINAL_SOURCE=/opt/botconnector-ai-chat/releases/ai-chat-core-r6-20260814T035154Z (systemd WorkingDirectory points directly at this dated release; no `current` symlink exists at this path)
RESOLVED_SOURCE=(same as original — no symlink layer)
CANONICAL_TARGET=apps/ai-chat-preview
LIVE_RUNTIME=botconnector-ai-chat-core.service (systemd, enabled/active), uvicorn app:app on 127.0.0.1:18220
LIVE_ROUTE=/panel/ai/ area serves a separate static frontend build (/var/www/botconnector-ai-chat-web-r17-.../); the exact proxy path to port 18220 was not traced in this pass
PROVENANCE_CONFIDENCE=MEDIUM
NOTES=Only 2 files (app.py, SHA256SUMS.txt) — single-file FastAPI app, consistent with BETA/preview scope per your Phase 1 provenance decision (only ai-chat-core included from the AI cluster; ai-console, mission-runner, tool-platform, desktop-ai-gateway, windows-tool-adapter are all deliberately excluded).

---

COMPONENT=ai-workspace
ORIGINAL_SOURCE=/home/botadmin/ai-workspace
RESOLVED_SOURCE=(same, not a symlink)
CANONICAL_TARGET=apps/ai-workspace
LIVE_RUNTIME=ai-workspace.service (systemd, enabled/active), WorkingDirectory = this same path
LIVE_ROUTE=NOT VERIFIED in this pass
PROVENANCE_CONFIDENCE=HIGH
NOTES=Distinct from /home/botadmin/ai-workspaces/ (plural) which is this Claude session's own scratch tree of unrelated POC candidates — not a component.

---

COMPONENT=admin-gate
ORIGINAL_SOURCE=/home/botadmin/admin-gate
RESOLVED_SOURCE=(same, not a symlink)
CANONICAL_TARGET=apps/admin-gate
LIVE_RUNTIME=admin-gate.service (systemd, enabled/active), WorkingDirectory = this same path
LIVE_ROUTE=Backs the /_botconnector_auth and per-panel auth_request checks referenced throughout botconnector-cutover.conf
PROVENANCE_CONFIDENCE=HIGH
NOTES=(none)

---

COMPONENT=business-suite (SUPERSEDED — see the resolved entry above)
STATUS=RESOLVED 2026-09-06. Kept this stale entry visible on purpose to
show the trail: the original search here (no filesystem match for a
"business-suite" directory name) was correct as far as it went — the
component just isn't named that on disk, it's named `bisnis`
(`/opt/botconnector-bisnis`). See the business-suite entry above for the
proven answer.

---

COMPONENT=multichannel
ORIGINAL_SOURCE=/opt/botconnector-multichannel
RESOLVED_SOURCE=(same, not a symlink)
CANONICAL_TARGET=packages/multichannel
LIVE_RUNTIME=Shared package, not itself deployed. CONFIRMED 2026-09-06 (was
MEDIUM confidence / untraced before): imported directly by both
`/opt/botconnector-bisnis/app.py` and `/opt/botconnector-integrasi/app.py`
via `sys.path.insert(0, "/opt")` + `import botconnector_multichannel`,
which resolves through the `/opt/botconnector_multichannel` (underscore)
symlink → `/opt/botconnector-multichannel` (hyphen, this directory). Also
backs botconnector-bisnis-telegram*.service (same app, different process
for the outbox/summary workers).
LIVE_ROUTE=N/A (shared package)
PROVENANCE_CONFIDENCE=HIGH (was MEDIUM — now proven via symlink resolution, not inferred)
NOTES=candidates/, vendor/, and backup*/ subdirectories were excluded from import as non-canonical WIP/vendored/backup content (root-owned, 700, not part of the deployed shared package). Contains a secret-scan finding, remediated: see below.

---

COMPONENT=shared-design
ORIGINAL_SOURCE=/home/botadmin/ai-workspaces/botconnector-design-master
RESOLVED_SOURCE=(same, not a symlink)
CANONICAL_TARGET=packages/shared-design
LIVE_RUNTIME=NONE (design documentation + reference mockups, not a runtime component)
LIVE_ROUTE=NONE
PROVENANCE_CONFIDENCE=LOW
NOTES=NEEDS_DECISION on confidence — chosen because it's the most complete design package found (README, DESIGN-SYSTEM.md, DESIGN-INVENTORY.md, PRODUCT-FLOW.md, SCREEN-CATALOG.md, IMPLEMENTATION-HANDOFF.md, reference PNGs). A second candidate, botconnector-homepage-design-poc, exists and was NOT imported (see LEGACY-PATHS.md) to avoid duplicate release directories — confirm this is the right pick.

---

COMPONENT=connector-core
ORIGINAL_SOURCE=/opt/botconnector-connector-core/current
LIVE_SYMLINK=/opt/botconnector-connector-core/current
RESOLVED_SOURCE=/opt/botconnector-connector-core/releases/connector-core-v1-google-sheets-admin-20260813T090411Z
CANONICAL_TARGET=services/connector-core
LIVE_RUNTIME=botconnector-connector-core.service (systemd, enabled/active), uvicorn main:app on 127.0.0.1:18196
LIVE_ROUTE=Backs the connector marketplace area referenced in botconnector-cutover.conf
PROVENANCE_CONFIDENCE=HIGH
NOTES=A separate, unrelated legacy directory /opt/botconnector-core also exists on disk with no systemd unit pointing at it — classified DUPLICATE/ARCHIVE_CANDIDATE (see LEGACY-PATHS.md), not imported.

---

COMPONENT=finance-core
ORIGINAL_SOURCE=/opt/botconnector-finance-core/releases/finance-core-r8-period-close-foundation-20260813T143444Z (systemd WorkingDirectory points directly at this dated release; no `current` symlink exists at this level)
RESOLVED_SOURCE=(same as original — no symlink layer)
CANONICAL_TARGET=services/finance-core
LIVE_RUNTIME=botconnector-finance-core.service (systemd, enabled/active)
LIVE_ROUTE=NOT VERIFIED in this pass
PROVENANCE_CONFIDENCE=HIGH
NOTES=(none)

---

COMPONENT=services/shipping/integration
ORIGINAL_SOURCE=/opt/botconnector-shipping-integration/releases/shipping-integration-v1-20260813T122333Z (no `current` symlink at this level)
RESOLVED_SOURCE=(same as original)
CANONICAL_TARGET=services/shipping/integration
LIVE_RUNTIME=botconnector-shipping-integration.service (systemd, enabled/active), uvicorn app:APP on 127.0.0.1:18243 (binary is actually connector-core's venv — shares an interpreter/venv with connector-core)
LIVE_ROUTE=NOT VERIFIED in this pass
PROVENANCE_CONFIDENCE=HIGH

---

COMPONENT=services/shipping/location-resolver
ORIGINAL_SOURCE=/opt/botconnector-shipping-location-resolver/releases/shipping-location-resolver-v1-20260813T122333Z (no `current` symlink at this level)
RESOLVED_SOURCE=(same as original)
CANONICAL_TARGET=services/shipping/location-resolver
LIVE_RUNTIME=botconnector-shipping-location-resolver.service (systemd, enabled/active)
LIVE_ROUTE=NOT VERIFIED in this pass
PROVENANCE_CONFIDENCE=HIGH

---

COMPONENT=services/shipping/location-public-gateway
ORIGINAL_SOURCE=/opt/botconnector-shipping-location-public-gateway/current
LIVE_SYMLINK=/opt/botconnector-shipping-location-public-gateway/current
RESOLVED_SOURCE=/opt/botconnector-shipping-location-public-gateway/releases/location-public-gateway-v1.1-failsoft-20260813T141718Z
CANONICAL_TARGET=services/shipping/location-public-gateway
LIVE_RUNTIME=botconnector-shipping-location-public-gateway.service (systemd, enabled/active), uvicorn app:app on 127.0.0.1:18245
LIVE_ROUTE=NOT VERIFIED in this pass
PROVENANCE_CONFIDENCE=HIGH

---

COMPONENT=services/shipping/public-gateway
ORIGINAL_SOURCE=/opt/botconnector-shipping-public-gateway/current
LIVE_SYMLINK=/opt/botconnector-shipping-public-gateway/current
RESOLVED_SOURCE=/opt/botconnector-shipping-public-gateway/releases/shipping-public-gateway-v1-20260813T123718Z
CANONICAL_TARGET=services/shipping/public-gateway
LIVE_RUNTIME=botconnector-shipping-public-gateway.service (systemd, enabled/active), uvicorn on 127.0.0.1:18244
LIVE_ROUTE=/pengiriman/, /konektor/rajaongkir/ (root /var/www/botconnector-shipping-public/current — a separate static deployment artifact, not this app source)
PROVENANCE_CONFIDENCE=HIGH
NOTES=Very small (2 files) — a thin gateway, plausible for its role. CONFIRMED LIVE END-TO-END 2026-09-06: a real, non-destructive `POST /api/shipping/rates` request (origin "Jakarta Pusat", destination "Bandung", weight 1000g, courier JNE) returned real resolved addresses (postal codes 10520/40614) and real courier tariffs (REG 12000 IDR, YES 24000 IDR, etc.) in ~1.5s, proving the full chain public-gateway → integration (127.0.0.1:18243) → RajaOngkir. Each call inserts one row into this service's own local `public_rate_requests` SQLite table (rate-limit/audit log) — non-destructive, no customer or order data touched.

---

COMPONENT=services/shipping/router
ORIGINAL_SOURCE=/opt/botconnector-shipping-router/releases/shipping-provider-router-v1-20260813T122333Z (no `current` symlink at this level)
RESOLVED_SOURCE=(same as original)
CANONICAL_TARGET=services/shipping/router
LIVE_RUNTIME=botconnector-shipping-router.service (systemd, enabled/active)
LIVE_ROUTE=NOT VERIFIED in this pass
PROVENANCE_CONFIDENCE=HIGH

---

COMPONENT=services/shipping/rajaongkir-cost
ORIGINAL_SOURCE=/opt/botconnector-shipping-providers/rajaongkir-cost/releases/rajaongkir-cost-adapter-v1-20260813T115940Z (no `current` symlink at this level)
RESOLVED_SOURCE=(same as original)
CANONICAL_TARGET=services/shipping/rajaongkir-cost
LIVE_RUNTIME=botconnector-rajaongkir-cost.service (systemd, enabled/active) — NOTE: this is a differently-named unit than the other 5 shipping services; it lives one level deeper under /opt/botconnector-shipping-providers/rajaongkir-cost rather than its own /opt/botconnector-shipping-rajaongkir-cost
LIVE_ROUTE=NOT VERIFIED in this pass
PROVENANCE_CONFIDENCE=HIGH
NOTES=Added per your Decision 1 (2026-09-06) as a 6th live shipping subfolder.

---

## Non-live shipping directories (audited, NOT imported as active service source — Decision 1)

COMPONENT=shipping/core-legacy
ORIGINAL_SOURCE=/opt/botconnector-shipping-core
LIVE_RUNTIME=NONE — no matching systemd unit found
CLASSIFICATION=LEGACY
NOTES=Has a releases/ directory (deploy-pattern present) suggesting it WAS deployed at some point; not currently active.

COMPONENT=shipping/stack-legacy
ORIGINAL_SOURCE=/opt/botconnector-shipping-stack
LIVE_RUNTIME=NONE — no matching systemd unit found
CLASSIFICATION=LEGACY
NOTES=Has a releases/ directory; possibly an orchestration/compose bundle rather than its own deployable. Not traced further.

COMPONENT=shipping/location-index-archive-candidate
ORIGINAL_SOURCE=/opt/botconnector-shipping-location-index
LIVE_RUNTIME=NONE — no matching systemd unit found
CLASSIFICATION=ARCHIVE_CANDIDATE
NOTES=Only contains a `candidates/` subdirectory — reads as exploratory/draft work, not a shipped service.

---

## Remediated secret-scan finding

COMPONENT=packages/multichannel (tests/)
FINDING=Two secret-shaped strings matched by the Phase 2/5 scanner in tests/run_acceptance.sh and tests/tenantization_fixture.py.
VERIFICATION=Checked the literal "Tenantization-Test-2026!" (exact string match, and sha256 hash comparison without printing any real value) against all 186 credential-shaped files under /etc, /root, /opt on this box — zero matches. Confirmed test-only.
ACTION=In the canonical repo copy only (NOT in the live /opt/botconnector-multichannel source): replaced the literal password with TEST_ONLY_DUMMY_PASSWORD_DO_NOT_USE and regenerated a matching argon2id hash (same params: v=19, m=65536, t=3, p=2) so the fixture's login-flow behavior is unchanged. run_acceptance.sh's ACCEPTANCE_PASSWORD default ("acceptance_test_only_nonsecret") was left as-is — it was already an explicit non-secret placeholder.
RESULT=TEST_FIXTURE_SECRET_SCAN_NOISE_REMOVED=YES

---

## Entrypoint completeness (2026-09-06 follow-up pass)

Corrects the original Phase 9 pass, which only checked component root
directories and wrongly read some nested entrypoints as missing.

| Component | SOURCE_PRESENT | ENTRYPOINT_IDENTIFIED | DEPENDENCIES_IDENTIFIED | CONFIG_INTERFACE_IDENTIFIED | LIVE_RUNTIME_MAPPING_IDENTIFIED |
|---|---|---|---|---|---|
| public-site | YES | YES (index.html) | N/A (static) | N/A | NO live mapping (not deployed) |
| store | YES | YES (app/app.py — nested) | YES (app/requirements.txt) | YES (/etc/botconnector-store/.env) | YES |
| business-suite | YES | YES (app.py) | NO OWN MANIFEST — runs on packages/multichannel's venv, has no requirements.txt of its own; a real gap if this app is ever deployed independently of that venv | YES (systemd LoadCredential, not a plain .env) | YES |
| integrasi | YES | YES (app.py) | Same as business-suite — shares Multichannel's venv, no own manifest | YES (same LoadCredential mechanism) | YES |
| restaurant | YES | YES (app/app.py — nested) | YES (app/requirements.txt) | YES (env vars: LICENSE_DB, LICENSE_PRIVATE_KEY, SELLER_ADMIN_PASSWORD_HASH, SELLER_SESSION_SECRET) | YES (Docker, not systemd) |
| parking | YES | YES (root — not checked for nested override) | YES (requirements.txt) | YES (.env.example present, real file at /etc/botconnector/parking.env) | YES |
| drive | YES | YES (app.py) | YES (requirements.txt) | UNKNOWN (env vars not enumerated this pass) | YES |
| ai-chat-preview | YES | YES (app.py) | NO OWN MANIFEST found | YES (DATABASE_URL, AI_CHAT_SCHEMA, ORCHESTRATOR_URL, LOCAL_INTELLIGENCE_URL/TOKEN — all read directly from app.py) | YES |
| ai-workspace | YES | YES (app.py) | NO OWN MANIFEST found | UNKNOWN | YES |
| admin-gate | YES | YES (admin_gate.py) | NO OWN MANIFEST — imports httpx + fastapi with nothing pinning versions | UNKNOWN | YES |
| multichannel | YES | N/A — shared package, not directly deployed (correct, not a gap) | NO MANIFEST found anywhere in the package; its venv exists at `/opt/botconnector-multichannel/venv` but what's installed in it isn't reconstructable from source alone — a real gap | N/A | N/A (see business-suite/integrasi for its runtime hosts) |
| connector-core | YES | YES (main.py) | YES (requirements.txt) | UNKNOWN | YES |
| finance-core | YES | YES (app/main.py — nested) | NO OWN MANIFEST found in the release; has its own venv (`$APPDIR/venv`), contents not reconstructable from source | YES (/etc/botconnector-finance-core/finance-core.env, plus dynamic Postgres IP resolution via `docker inspect botconnector-core-postgres`) | YES |
| 6 shipping services | YES (all 6) | YES (all 6 — app.py at root) | NO OWN MANIFEST on any of the 6 | PARTIAL (env vars read directly in public-gateway's app.py; others not individually enumerated) | YES (all 6, plus one proven live end-to-end) |

**Real gap, not a false negative**: five components (business-suite,
integrasi, ai-chat-preview, ai-workspace, admin-gate, multichannel itself,
finance-core, and all 6 shipping services) have no tracked dependency
manifest in source — their actual installed package versions live only in
each release's own venv on the VPS, not in anything importable into this
repo. This is a genuine `CAN_RECONSTRUCT_DEPLOYMENT=NO` finding for those
components until each venv's `pip freeze` (or equivalent) is captured
separately — not something this consolidation pass can fix by re-reading
source harder.

---

## Dependency manifest closure (2026-09-06 follow-up — CLOSED)

The gap above is now closed for all 8 units. Every lockfile below is a
verbatim, read-only `pip freeze` capture from the live production venv —
no install/upgrade was performed, no venv/container was mutated.

| Component | PYTHON_VERSION | DEPENDENCY_MANIFEST | DEPENDENCY_LOCK_SOURCE | EXACT_RUNTIME_PINS |
|---|---|---|---|---|
| packages/multichannel | 3.12.3 | `packages/multichannel/requirements.lock.txt` | PROVEN_LIVE_VENV | YES |
| apps/business-suite | 3.12.3 | none of its own — see BUSINESS_SUITE_DEPENDENCY_OWNER below | PROVEN_LIVE_VENV (via owner) | YES (via owner) |
| apps/integrasi | 3.12.3 | none of its own — see INTEGRASI_DEPENDENCY_OWNER below | PROVEN_LIVE_VENV (via owner) | YES (via owner) |
| apps/ai-chat-preview | 3.12.3 | `apps/ai-chat-preview/requirements.lock.txt` | PROVEN_LIVE_VENV | YES |
| apps/ai-workspace | 3.12.3 | `apps/ai-workspace/requirements.lock.txt` | PROVEN_LIVE_VENV | YES |
| apps/admin-gate | 3.12.3 | `apps/admin-gate/requirements.lock.txt` | PROVEN_LIVE_VENV | YES |
| services/finance-core | 3.12.3 | `services/finance-core/requirements.lock.txt` | PROVEN_LIVE_VENV | YES |
| services/connector-core + 6 shipping services | 3.12.3 | DIRECT_REQUIREMENTS=`services/connector-core/requirements.txt` (pre-existing, loose ranges, unchanged) / EXACT_LOCK=`services/connector-core/requirements.lock.txt` (new, exact pins) | PROVEN_LIVE_VENV | YES |

```
BUSINESS_SUITE_DEPENDENCY_OWNER=packages/multichannel
INTEGRASI_DEPENDENCY_OWNER=packages/multichannel
SHARED_PYTHON_RUNTIME_OWNER=services/connector-core
SHIPPING_DEPENDENCY_MODEL=ONE_SHARED_RUNTIME
SHIPPING_LOCKFILE_COPIES=1 (services/connector-core/requirements.lock.txt only — not duplicated into any of the 6 shipping directories)
```

Lockfile safety audit (grep across all 6 lockfiles for editable installs,
local/`file://` paths, private or localhost package-index URLs, and
embedded credentials/tokens):

```
EDITABLE_REFERENCES=0
LOCAL_PATH_REFERENCES=0
PRIVATE_URL_REFERENCES=0
SECRET_REFERENCES=0
```

All 6 lockfiles were also line-validated against `name==version` /
comment syntax — zero malformed lines, zero packages with an unresolved
origin (every package traces to a specific live venv this session
actually queried).

---

## Canonical independence closure (2026-09-06, Phase 10.1 — CLOSED)

Three real leaks were caught by the build/redeploy proof and fixed, each
re-verified by running the ACTUAL committed file (not a workaround copy)
directly from the canonical repo:

- **apps/business-suite/app.py + run.sh**: `sys.path.insert(0, "/opt")`
  replaced with a repo-relative computation
  (`Path(__file__).resolve().parents[2] / "packages"`) plus an explicit
  `sys.modules` alias so `import botconnector_multichannel` resolves to
  `packages/multichannel` without any symlink or source duplication.
  `run.sh` rewritten to resolve its own script directory and default to
  `packages/multichannel/venv` (overridable via `MULTICHANNEL_VENV`).
  Re-verified: ran the unmodified `run.sh` from the canonical repo,
  `/health` returned `{"ok":false,...,"database":"disconnected"}` (correct
  — no production credential was ever supplied).
- **apps/integrasi/app.py + run.sh**: identical fix. Re-verified the same
  way: unmodified `run.sh` → `/health` returned `{"ok":true,...}`.
- **services/finance-core/run-finance-core.sh**: hardcoded
  `/opt/botconnector-finance-core/releases/...` replaced with a
  script-relative `APPDIR`/venv path; the Postgres-host resolution via
  `docker inspect` was made opt-in (`FINANCE_CORE_POSTGRES_CONTAINER`)
  rather than hardwired, so a plain `FINANCE_DB_HOST` env var works
  everywhere. Re-verified: unmodified script, dummy DB config,
  `/openapi.json` → 200.
- **packages/multichannel/providers/shopee.py**: the hardcoded
  `/opt/botconnector-shopee-real-provider` foundation-probe path is now
  read from `SHOPEE_OFFLINE_FOUNDATION_ROOT` (env var), defaulting to the
  same production path — config-driven, not hardcoded. No capability
  change: `kemampuan` stays `frozenset()` regardless.

Remaining old-path references were classified, not silently deleted (per
instruction — see `/tmp` scratch classification note, folded in here):
TEST_TOOLING (packages/multichannel's own acceptance/test scripts, 7
files; one parking dev screenshot utility) and LEGACY_DEPLOYMENT_TOOL /
MIGRATION_REFERENCE (apps/store's deploy/rollback/patch scripts; two
finance-core historical candidate canary scripts under `evidence/`). None
of these are imported by, or required to start, any canonical app — proven
by the same import/run proofs above.

```
BUSINESS_SUITE_CANONICAL_IMPORT=PASS
BUSINESS_SUITE_RUN_SCRIPT=PASS
INTEGRASI_CANONICAL_IMPORT=PASS
INTEGRASI_RUN_SCRIPT=PASS
FINANCE_CORE_SCRIPT_CANONICAL=YES
FINANCE_CORE_OLD_RUNTIME_SOURCE_REQUIRED=NO
CANONICAL_RUNTIME_DEPENDENCY_ON_OLD_SOURCE=0 (for application imports, run scripts, build scripts, redeploy recipes, and active runtime config — the only categories this target covers per instruction)
```
