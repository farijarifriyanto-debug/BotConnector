# Source Map

Generated during Phase 2–4 of the BotConnector Platform consolidation
(2026-09-06). Read-only investigation against live systemd units, nginx
config, and on-disk layout — no runtime was modified to produce this.

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
LIVE_ROUTE=NONE (see homepage note below — the live botconnector.id root is a separate deployment artifact, not this source)
PROVENANCE_CONFIDENCE=MEDIUM
NOTES=Classified FUTURE_CANONICAL_SOURCE per explicit user decision. No generator/source repo was found behind any live /var/www/botconnector* root (checked business-suite, restaurant, retail, store, shared-design, and the bare botconnector/ doc root — no .git, package.json, or sourcemaps in any of them). Live roots are DEPLOYMENT_ARTIFACT / CURRENT_LIVE_OUTPUT only; not imported as source per instruction.

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

COMPONENT=restaurant
ORIGINAL_SOURCE=/opt/restaurant-seller-control
RESOLVED_SOURCE=(same, not a symlink)
CANONICAL_TARGET=apps/restaurant
LIVE_RUNTIME=Docker container `restaurant-seller-control` (up 7d at time of check), health on 127.0.0.1:18192 — not a systemd unit
LIVE_ROUTE=/panel/restaurant/ (nginx proxy_pass to 127.0.0.1:18192)
PROVENANCE_CONFIDENCE=HIGH
NOTES=Some files (backup.sh, rollback-remove.sh, status.sh) are root-owned 700; read via scoped read-only sudo per explicit grant, backup/import are COMPLETE not partial.

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

COMPONENT=business-suite
ORIGINAL_SOURCE=NOT FOUND
RESOLVED_SOURCE=N/A
CANONICAL_TARGET=apps/business-suite (created empty)
LIVE_RUNTIME=UNKNOWN
LIVE_ROUTE=/var/www/botconnector-business-suite exists as a deployment artifact only (no .git/package.json/sourcemaps)
PROVENANCE_CONFIDENCE=NONE
NOTES=NEEDS_DECISION. No dedicated "business-suite thin app" source directory was found anywhere on disk. The only filesystem hit for the name is an unrelated one-off patch script (business-suite-trial-3d-seller-patch-v1.sh). Not fabricating a source — left as an empty target pending your input on where this actually lives (it may be logic embedded inside multichannel/local_business rather than a separate app).

---

COMPONENT=multichannel
ORIGINAL_SOURCE=/opt/botconnector-multichannel
RESOLVED_SOURCE=(same, not a symlink)
CANONICAL_TARGET=packages/multichannel
LIVE_RUNTIME=Backs botconnector-bisnis.service, botconnector-bisnis-telegram*.service, botconnector-integrasi.service (WorkingDirectory for those is /opt/botconnector-bisnis and /opt/botconnector-integrasi respectively — this package appears to be the shared library those deployments are built from, not itself the deployed WorkingDirectory)
LIVE_ROUTE=N/A (shared package)
PROVENANCE_CONFIDENCE=MEDIUM
NOTES=candidates/, vendor/, and backup*/ subdirectories were excluded from import as non-canonical WIP/vendored/backup content (root-owned, 700, not part of the deployed shared package). Exact relationship between this package and the separately-deployed /opt/botconnector-bisnis and /opt/botconnector-integrasi working directories was not traced further — flagging as a gap, not asserting they're identical copies. Contains a secret-scan finding, remediated: see below.

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
LIVE_RUNTIME=botconnector-shipping-public-gateway.service (systemd, enabled/active)
LIVE_ROUTE=/pengiriman/, /konektor/rajaongkir/ (root /var/www/botconnector-shipping-public/current — a separate static deployment artifact, not this app source)
PROVENANCE_CONFIDENCE=HIGH
NOTES=Very small (2 files) — a thin gateway, plausible for its role.

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
