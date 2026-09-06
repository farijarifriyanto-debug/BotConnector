# Cutover Plan

**PLANNING DOCUMENT ONLY. Nothing in this file has been executed.** No
production process was touched to produce it — everything below is either
already-proven build/redeploy evidence (docs/build-proof/BUILD-REDEPLOY-PROOF.md)
or read-only inventory of the current live systemd/nginx/Docker state.

## 0. Closing the 20 vs 19 count

`docs/provenance/SOURCE-MAP.md` lists 20 canonical components.
`docs/build-proof/BUILD-REDEPLOY-PROOF.md` proved 19 of them redeployable.
The 20th is `packages/shared-design`.

```
COMPONENT_20=packages/shared-design
CLASSIFICATION=STATIC_ASSET_PACKAGE
```

Reasoning: it is design documentation and reference mockup images
(`DESIGN-SYSTEM.md`, `SCREEN-CATALOG.md`, PNG references) with
`LIVE_RUNTIME=NONE` (confirmed in SOURCE-MAP.md) — no server, no build
step, nothing that runs. It's consumed by people (designers/engineers
reading it), not by a process. "Redeploy proof" doesn't apply to it any
more than it would to a README — there is nothing to prove beyond "the
files exist and are readable," which they are. This is different from
`packages/multichannel`, which also isn't directly deployed but DOES have
real build evidence (its own dependency lockfile installs cleanly, and two
real applications — business-suite, integrasi — import and run against
it) — that's why multichannel counts as proven and shared-design doesn't
need to.

```
DEPLOYABLE_COMPONENTS_TOTAL=19
REDEPLOY_PROVEN_DEPLOYABLES=19
UNPROVEN_DEPLOYABLES=0
```

All 19 actual deployables are proven. Planning may proceed.

## 1. Process safety guardrail (mandatory, effective immediately)

This rule exists because of a real near-miss during Phase 10.1: a
`pkill -f "uvicorn app:APP"` matched the exact command-line substring of
live production business-suite, integrasi, and shipping processes. It
happened not to kill them (confirmed immediately after and again later —
all healthy, uninterrupted `active` state throughout), but the pattern
itself was unsafe and must not be repeated.

**FORBIDDEN in any future isolated test, on this box, permanently:**
- `pkill -f` / `killall` by generic process or command-substring match
- Any process termination that relies on substring/pattern matching
  against a command line, rather than an exact PID captured at spawn time
- Broad `docker stop`/`docker restart` by name pattern or label glob
- `docker compose down` (can affect more than the one service intended)
- `systemctl restart` with globs or multiple unit names in one call

**Required procedure for any future isolated test:**
1. Capture the exact PID (`echo $!` right after backgrounding) or exact
   container ID (`docker run` returns it) at spawn time — never rediscover
   it later via `pgrep`/`ps grep`.
2. Before terminating, verify that PID/container's owner, working
   directory, and full command line actually match what you spawned (not
   just a similar-looking one).
3. Terminate only that exact PID/container ID.
4. After terminating, re-verify the real production PIDs/containers you
   might have been near are unchanged (uptime, health check, or
   `systemctl is-active`) — as was done throughout this consolidation.

```
BROAD_PROCESS_KILL_FORBIDDEN=YES
```

## 2. Live deployment inventory

Pulled from the live systemd/nginx/Docker state and cross-checked against
SOURCE-MAP.md — where the two disagreed, runtime evidence won (none did,
in this pass).

| COMPONENT | LIVE_SERVICE_OR_CONTAINER | LIVE_PORT | NGINX_ROUTE | CURRENT_RELEASE_ARTIFACT | STATEFUL |
|---|---|---|---|---|---|
| public-site | none (not deployed) | — | botconnector.id root serves `/var/www/botconnector` (unrelated deployment artifact, not this source) | N/A | NO |
| store | botconnector-store.service | 18194 | `/store/`, `/konektor/` | `/opt/botconnector-store/releases/store-v6-20260812T071559Z` via `current` symlink | YES (SQLite orders) |
| business-suite | botconnector-bisnis.service | 18199 | `/bisnis/` (implied by app; not separately confirmed in nginx this pass) | flat WorkingDirectory, no release-dir pattern | YES (shared Postgres) |
| integrasi | botconnector-integrasi.service | 18198 | `/integrasi/` | flat WorkingDirectory | NO (read-only) |
| restaurant (Seller Control) | Docker container `restaurant-seller-control` | 18192 | `/panel/restaurant/` | image tag `1.3.2-store-api-v2` | YES (SQLite licenses.db) |
| parking | botconnector-parking.service | 8711 | `/parking/` | flat WorkingDirectory (`.venv`) | YES (dedicated Postgres, container `botconnector-parking-postgres`) |
| drive | Docker Compose service `botconnector-drive` | 18190 | not confirmed in nginx this pass | image `botconnector-drive:0.2.0` | YES (bind-mounted file storage + SQLite meta) |
| ai-chat-preview | botconnector-ai-chat-core.service | 18220 | `/panel/ai/` area (frontend is a separate static build) | `releases/ai-chat-core-r6-20260814T035154Z`, no `current` symlink | YES (Postgres) |
| ai-workspace | ai-workspace.service | 18170 | `/workspace/`, `/workspace/api/` | flat WorkingDirectory | not confirmed this pass |
| admin-gate | admin-gate.service | 18160 | `/panel/` (overview) + backs every `auth_request` platform-wide | flat WorkingDirectory | NO (auth logic; session store not confirmed) |
| multichannel | shared package — not deployed | — | N/A | flat WorkingDirectory (`/opt/botconnector-multichannel`) | N/A (shared Postgres, via consumers) |
| shared-design | not deployed | — | N/A | N/A | NO |
| connector-core | botconnector-connector-core.service | 18196 | `/api/`, `/hook/` (webhook ingestion) | `releases/connector-core-v1-google-sheets-admin-20260813T090411Z` via `current` symlink | not confirmed this pass |
| finance-core | botconnector-finance-core.service | 18200 | not confirmed in nginx this pass (internal, consumed by business-suite/integrasi via `Requires=`) | `releases/finance-core-r8-period-close-foundation-...`, no `current` symlink | YES (Postgres, container `botconnector-core-postgres`) |
| shipping/integration | botconnector-shipping-integration.service | 18243 | internal only | `releases/shipping-integration-v1-...` | YES (SQLite) |
| shipping/location-resolver | botconnector-shipping-location-resolver.service | not confirmed | internal only | `releases/shipping-location-resolver-v1-...` | YES (SQLite) |
| shipping/location-public-gateway | botconnector-shipping-location-public-gateway.service | 18245 | internal only | `current` → `releases/location-public-gateway-v1.1-failsoft-...` | YES (SQLite) |
| shipping/public-gateway | botconnector-shipping-public-gateway.service | 18244 | `/pengiriman/`, `/konektor/rajaongkir/` (via `/var/www/botconnector-shipping-public`, a separate static artifact) | `current` → `releases/shipping-public-gateway-v1-...` | YES (SQLite audit log) |
| shipping/router | botconnector-shipping-router.service | not confirmed | internal only | `releases/shipping-provider-router-v1-...` | YES (SQLite) |
| shipping/rajaongkir-cost | botconnector-rajaongkir-cost.service | not confirmed | internal only | `releases/rajaongkir-cost-adapter-v1-...` | YES (SQLite ledger) |

SECRET_DEPENDENCIES and EXTERNAL_PROVIDER_DEPENDENCIES per component are
already fully enumerated in `docs/capability-registry/EXTERNAL-PROVIDERS.md`
and `docs/deployment/REDEPLOY-MAP.md` — not repeated here to avoid drift
between two copies of the same fact.

## 3. Cutover type per component

No universal deployment mechanism is imposed — each component keeps
whatever it already proved works.

| COMPONENT | CUTOVER_TYPE | WHY |
|---|---|---|
| public-site | STATIC_ATOMIC_SYMLINK | plain static files; production already has no live equivalent to switch — this would be a first deploy, not a cutover |
| shared-design | NO_CUTOVER_NEEDED | never deployed, nothing to switch |
| store | SYSTEMD_RELEASE_SWITCH | already uses `releases/<ts>` + `current` symlink |
| business-suite | SHARED_RUNTIME_SWITCH | flat WorkingDirectory sharing Multichannel's venv — a cutover here means updating the app.py/run.sh in place plus (if changed) reinstalling the shared venv, not a symlink flip |
| integrasi | SHARED_RUNTIME_SWITCH | same as business-suite |
| multichannel | SHARED_RUNTIME_SWITCH | its venv is the shared unit both business-suite and integrasi restart against |
| restaurant (Seller Control) | DOCKER_IMAGE_RECREATE | already versioned by image tag |
| parking | SYSTEMD_RELEASE_SWITCH (new) — currently flat `.venv`, no release-dir pattern exists yet. A cutover would need to either introduce one (out of scope for this plan) or accept a brief stop/pip-install/start window on the same directory |
| drive | DOCKER_IMAGE_RECREATE | already versioned by image tag via docker-compose |
| ai-chat-preview | SYSTEMD_RELEASE_SWITCH | already uses dated `releases/` dirs, though no `current` symlink layer exists — systemd points at the dated dir directly, so a cutover means updating the unit's `WorkingDirectory`/`ExecStart` to the new dated dir |
| ai-workspace | SHARED_RUNTIME_SWITCH — flat WorkingDirectory, own venv, no release-dir pattern |
| admin-gate | SHARED_RUNTIME_SWITCH — flat WorkingDirectory, own venv, no release-dir pattern. Highest blast-radius of any single component (it's the platform's one auth seam) |
| connector-core | SYSTEMD_RELEASE_SWITCH | already uses `releases/` + `current` |
| finance-core | SYSTEMD_RELEASE_SWITCH | already uses dated `releases/` dirs (no `current` symlink — same pattern as ai-chat-preview) |
| shipping/public-gateway, location-public-gateway | SYSTEMD_RELEASE_SWITCH | both already have `current` symlinks |
| shipping/integration, location-resolver, router, rajaongkir-cost | SYSTEMD_RELEASE_SWITCH | dated `releases/` dirs, no `current` symlink — same caveat as ai-chat-preview/finance-core |

## 4. Dependency / cutover graph

```
Postgres (multiple containers: botconnector-core-postgres,
          botconnector-parking-postgres, and business-suite/integrasi's
          shared DB — not confirmed to be the same instance as
          "core-postgres" in this pass, flagged as NEEDS_DECISION)
  → finance-core
  → business-suite, integrasi (both Requires= finance-core)
  → parking (dedicated instance)
  → ai-chat-preview

packages/multichannel (shared venv)
  → business-suite
  → integrasi

services/connector-core (shared venv)
  → shipping/integration, location-resolver, location-public-gateway,
    public-gateway, router, rajaongkir-cost

admin-gate
  → every panel route platform-wide (auth_request) — this is a dependency
    of nginx's routing decision for ALL other components' panel UIs, not
    a runtime import dependency. Restarting admin-gate briefly would 401
    every panel, not crash the backends themselves.

shared-design
  → no runtime dependents (design reference only)

External providers (RajaOngkir, Midtrans, Google Sheets/Drive/Picker,
Telegram) → capability readiness only, per your instruction — none of
them gate whether a *cutover* can happen, only whether a capability may
be marketed as live afterward.
```

```
CUTOVER_PREDECESSORS(business-suite) = packages/multichannel, finance-core, Postgres
CUTOVER_PREDECESSORS(integrasi) = packages/multichannel, finance-core, Postgres
CUTOVER_PREDECESSORS(6 shipping services) = services/connector-core (shared venv)
CUTOVER_PREDECESSORS(everything else) = none (each is self-contained: own venv/image, own release pattern)

CUTOVER_DEPENDENTS(packages/multichannel) = business-suite, integrasi
CUTOVER_DEPENDENTS(services/connector-core) = 6 shipping services
CUTOVER_DEPENDENTS(admin-gate) = every panel route (routing-level, not process-level)
CUTOVER_DEPENDENTS(finance-core) = business-suite, integrasi (hard systemd Requires=)

CAN_ROLLBACK_INDEPENDENTLY:
  public-site, shared-design, store, restaurant, parking, drive,
  ai-chat-preview, ai-workspace, admin-gate, connector-core, finance-core = YES
  business-suite, integrasi = only independently if the multichannel venv
    itself isn't what changed; if multichannel's own dependencies changed,
    they must roll back together
  6 shipping services = only independently if connector-core's shared venv
    itself isn't what changed; same coupling as multichannel/business-suite
```

## 5. Proposed cutover waves

Not the example order from your prompt — derived from the actual
dependency graph above: lowest blast-radius and zero/soft dependencies
first, hard-coupled shared-runtime groups grouped together, admin-gate
deliberately placed late (it's the widest blast-radius single component:
touch it and every panel briefly 401s), and every stateful/Postgres-backed
component last, each in its own wave so a bad rollback on one never drags
down another.

### Wave 0 — canonical deployment tooling / release skeleton
COMPONENTS=none live yet — this wave is only about staging the venvs/release-dir conventions documented in REDEPLOY-MAP.md (e.g. building `packages/multichannel/venv`, `services/connector-core/venv` at their canonical repo paths) so later waves have something to switch to.
WHY_GROUPED=Nothing here touches a live process; it's pure staging.
EXPECTED_DOWNTIME=0
PRECHECK=confirm `git log` HEAD matches the reviewed commit; confirm disk floor (10GB, same rule as Phase 10A)
DEPLOY_ACTION=build shared venvs per REDEPLOY-MAP.md `BUILD_COMMAND`s, on the side, without touching any systemd unit
HEALTH_GATE=N/A (nothing live yet)
REAL_FUNCTION_GATE=N/A
ROLLBACK_TRIGGER=N/A
ROLLBACK_ACTION=delete the staged venv, nothing was live
POSTCHECK=confirm zero production units were touched

### Wave 1 — RETIRED 2026-09-06, see replacement below

**The premise of the original Wave 1 was factually wrong and must not be
executed as written.** It assumed the botconnector.id apex had "no
existing equivalent to replace." It does: a real, live Docker application
(`botconnector-platform-home`) handling authentication, session issuance,
a product-routing gateway, and support ticketing — see
`docs/provenance/HOMEPAGE-CONVERGENCE.md` for the full audit. Deploying
`apps/public-site` to the apex under the old plan would have silently
broken login, registration, and every customer's path into Business
Suite/Parking/etc. This was caught during precheck, before any nginx
change — nothing was touched.

### Wave 1 (replacement, conceptual only — not ready to execute)

Split into two distinct, separately-gated concerns per the homepage
convergence decision (OPTION_B_FRONTEND_BACKEND_SPLIT). Neither is
executed in this plan. `apps/homepage-runtime` is now imported and
build-proven (see docs/provenance/SOURCE-MAP.md and
HOMEPAGE-CONVERGENCE.md) — that unblocks planning for concern 1, but
production still runs the old `/opt` source unchanged, and no nginx
change has been made.

#### 1. HOME_RUNTIME_CANONICALIZATION — EXECUTED, PASS (2026-09-06)

Goal: make `apps/homepage-runtime` the source production actually runs
from, WITHOUT changing what's served (same app, same routes, same
behavior) and WITHOUT touching the apex routing decision.

**Done.** Built `botconnector-platform-home:348f3f2-20260906T094839Z`
directly from `apps/homepage-runtime` at commit `348f3f2`, updated only
the `image:` line in `/opt/botconnector-platform-starter-v0.3/homepage/docker-compose.yml`
(one-line diff, backed up first), recreated only `botconnector-platform-home`.
All acceptance checks (health, login, register, catalog, application
gateway, support, Postgres, Redis, SMTP AUTH) passed against the live
container. nginx, Postgres, Redis, and backend-core were not touched or
restarted. `/var/lib/botconnector-platform` data confirmed intact. Old
image (`tenantization-v1-20260828`, digest `sha256:80682abba1de...`)
retained locally for rollback. Full acceptance record:
`docs/deployment/HOMEPAGE-CUTOVER-2026-09-06.md`.

COMPONENTS=apps/homepage-runtime
WHY_GROUPED=alone — this is a source-of-truth switch, not a functional or routing change. It should be indistinguishable to any user if done correctly.
EXPECTED_DOWNTIME=one container recreate, seconds — same class of action as the drive/restaurant Docker cutovers in Wave 7
PRECHECK=build the image from `apps/homepage-runtime` (proven this session — PASS); diff the built image's `/app/app` against the currently-live image's `/app/app` to confirm byte-for-byte parity (the SMTP fix is the one intentional difference — that diff should show exactly one line, otherwise stop and investigate); confirm `docker-compose.yml` in the canonical copy still matches production's actual mounts/networks
DEPLOY_ACTION=undetermined — this is the smallest, most mechanical of the two concerns, but "smallest" does not mean risk-free: it's the platform's login system. NOT executed in this plan.
HEALTH_GATE=`/health` → 200; the same routes proven in isolation this session (`/login`, `/register`, `/products`, `/app`, `/support`) return the same status codes against production
REAL_FUNCTION_GATE=a real login by a real (non-production-customer) test account succeeds, session cookie issues correctly, and at least one `/app/{slug}/...` gateway hop reaches its real backend
ROLLBACK_TRIGGER=any auth failure, any 5xx on a previously-200 route, or any support/catalog regression
ROLLBACK_ACTION=recreate the container from the previous image tag (`botconnector-platform-home:tenantization-v1-20260828`), unchanged, per the same pattern already proven for drive/restaurant
POSTCHECK=confirm business-suite/parking (the application-gateway's real downstream dependents) still receive traffic correctly

#### 2. PUBLIC_MARKETING_FRONTEND_CUTOVER

Goal: decide where (if anywhere) `apps/public-site`'s marketing
presentation actually goes, now that it's confirmed NOT to collide with
anything except the apex `/` itself.

COMPONENTS=apps/public-site
WHY_GROUPED=alone — this is a pure presentation decision, entirely separate from concern 1's source-of-truth switch
EXPECTED_DOWNTIME=0 if placed additively (a new path/subdomain); undetermined if the apex `/` itself is ever chosen — that specific choice requires resolving the one real collision documented in `docs/architecture/PUBLIC-SITE-RUNTIME-CONTRACT.md` and is a separate, explicit, future approval, not a default
PRECHECK=Playwright acceptance already PASS for the candidate in isolation (this session, twice)
DEPLOY_ACTION=undetermined — placement not chosen; NOT executed in this plan
HEALTH_GATE=HTTP 200 on all canonical pages
REAL_FUNCTION_GATE=no unsupported capability claims (PUBLIC-SURFACE.md gate) PLUS confirm every CTA that should reach HOMEPAGE_RUNTIME (login, register, and anything under `/app/...`) still resolves correctly after whatever placement is chosen
ROLLBACK_TRIGGER=any 5xx or broken asset
ROLLBACK_ACTION=revert the nginx location/config change (config-only)
POSTCHECK=confirm HOME_RUNTIME_CANONICALIZATION's routes are unaffected

```
READY_FOR_HOMEPAGE_RUNTIME_CUTOVER_PLANNING=YES (import + build proof done; production switch itself not planned in detail — the precheck above is the next concrete step, not yet executed)
READY_FOR_PUBLIC_FRONTEND_CUTOVER_PLANNING=NO (placement/routing decision for the `/` collision has not been made)
READY_FOR_APEX_CUTOVER=NO
```

### Wave 2 — self-contained internal services, own release pattern already proven
COMPONENTS=finance-core, ai-chat-preview
WHY_GROUPED=Both use the dated-`releases/`-dir-without-`current`-symlink pattern (systemd `WorkingDirectory` points at the dated dir directly) — same cutover mechanics, both proven redeployable this session, both stateful via Postgres but each with an independent schema/data path (no cross-dependency between the two).
EXPECTED_DOWNTIME=one systemd restart each (seconds), sequential not parallel
PRECHECK=new release directory built and dependency-installed per REDEPLOY-MAP.md; `FINANCE_DB_HOST`/`DATABASE_URL` reachable from the new dir
DEPLOY_ACTION=update `WorkingDirectory=`/`ExecStart=` in each unit to the new dated dir, `systemctl daemon-reload && systemctl restart <unit>` — NOT executed in this plan
HEALTH_GATE=`/openapi.json` → 200 (finance-core); ai-chat-preview's own health path once identified
REAL_FUNCTION_GATE=finance-core: a real read against Postgres succeeds; ai-chat-preview: session round-trip through its already-live `ORCHESTRATOR_URL` succeeds
ROLLBACK_TRIGGER=health gate fails, or Requires=-dependent business-suite/integrasi report `database:disconnected` after finance-core's restart
ROLLBACK_ACTION=point the unit back at the previous dated release dir, restart
POSTCHECK=confirm business-suite/integrasi (finance-core's dependents) still report healthy

### Wave 3 — shared connector-core runtime + 6 shipping services
COMPONENTS=connector-core, shipping/integration, shipping/location-resolver, shipping/location-public-gateway, shipping/public-gateway, shipping/router, shipping/rajaongkir-cost
WHY_GROUPED=All 7 share exactly one venv (proven in Phase 9/10). If that shared venv needs updating, all 7 must move together to avoid a dependency-version mismatch across processes that are otherwise independently deployed. If only individual app code changed (not shared deps), each of the 7 can restart independently using their existing `releases/`+`current` or dated-dir pattern.
EXPECTED_DOWNTIME=one restart per affected unit, seconds each; `public-gateway` is public-facing (RajaOngkir chain) so schedule for lowest-traffic window
PRECHECK=shared venv rebuilt/verified against `services/connector-core/requirements.lock.txt`; re-run the real RajaOngkir E2E check (already proven working this session) against the new code before flipping traffic
DEPLOY_ACTION=release-dir/`current`-symlink flip per component, or shared-venv reinstall if deps changed — NOT executed in this plan
HEALTH_GATE=each service's own `/health`-equivalent; public-gateway specifically: a real `POST /api/shipping/rates` returns real quotes (same test performed this session)
REAL_FUNCTION_GATE=SHIPPING_REAL_E2E=PASS (same bar already met once — must be re-met post-cutover before calling this wave done)
ROLLBACK_TRIGGER=E2E chain fails, or any of the 6 fails its own health check
ROLLBACK_ACTION=symlink/dated-dir revert per component; if the shared venv was the change, revert the venv for all 7 together
POSTCHECK=repeat the real E2E chain call once more post-rollback-or-success to confirm final state

### Wave 4 — AI Preview, AI Workspace (self-contained, low external coupling)
COMPONENTS=ai-workspace
WHY_GROUPED=Standalone tool workspace, own venv, no dependents, no Postgres dependency confirmed. (ai-chat-preview was already placed in Wave 2 because it shares the dated-release-dir mechanics with finance-core and IS Postgres-backed — kept it there rather than forcing an artificial "AI" grouping across differing risk profiles.)
EXPECTED_DOWNTIME=one restart, seconds
PRECHECK=venv rebuilt per REDEPLOY-MAP.md
DEPLOY_ACTION=restart against updated source — NOT executed in this plan
HEALTH_GATE=liveness signal (no dedicated `/health`; `/openapi.json` or equivalent)
REAL_FUNCTION_GATE=none identified beyond liveness (internal tool workspace, not customer-facing)
ROLLBACK_TRIGGER=health gate fails
ROLLBACK_ACTION=git revert + restart
POSTCHECK=confirm process alive

### Wave 5 — Admin Gate (deliberately isolated — widest blast radius)
COMPONENTS=admin-gate
WHY_GROUPED=Alone, on purpose. It backs `auth_request` for every panel route platform-wide. A bad deploy here doesn't crash other services, but it can 401 every panel simultaneously. Isolating it means a failure here is trivially attributable and instantly reversible without touching anything else.
EXPECTED_DOWNTIME=one restart, seconds — but a bad deploy's blast radius is "every panel returns 401" until rolled back, so treat this wave's rollback trigger as hair-trigger
PRECHECK=venv rebuilt; smoke-test the auth flow against a non-production session before restart
DEPLOY_ACTION=restart against updated source — NOT executed in this plan
HEALTH_GATE=`/openapi.json`-equivalent AND a real `auth_request` round-trip (hit any panel route, confirm 2xx/401 as expected, not 5xx)
REAL_FUNCTION_GATE=at least one real panel login/session round-trip succeeds
ROLLBACK_TRIGGER=any panel route starts returning 5xx instead of 401/2xx
ROLLBACK_ACTION=git revert + restart, immediately
POSTCHECK=spot-check 2–3 panel routes across different verticals (e.g. `/panel/ai/`, `/panel/restaurant/`)

### Wave 6 — shared Multichannel runtime + Business Suite + Integrasi
COMPONENTS=packages/multichannel (shared venv), business-suite, integrasi
WHY_GROUPED=Business Suite is the deepest, most-used capability in the
whole platform (Retail POS, Restaurant POS, Kitchen/KDS, Inventory,
Transfers, Reports, offline sync) and shares one venv with Integrasi.
Placed after admin-gate specifically so that if admin-gate had a problem,
it's already resolved before touching the platform's highest-value
capability.
EXPECTED_DOWNTIME=one restart per app, seconds each; if the shared venv changed, both restart together
PRECHECK=shared venv rebuilt/verified; confirm Finance Core (Wave 2) and Postgres are healthy first — both are hard `Requires=`
DEPLOY_ACTION=restart business-suite and integrasi against updated source/venv — NOT executed in this plan
HEALTH_GATE=business-suite `/health` → `database:connected`; integrasi `/health` → `ok:true`
REAL_FUNCTION_GATE=at least one real read through `/bisnis/api/state` or equivalent succeeds (no write attempted as part of a gate check — reads only)
ROLLBACK_TRIGGER=`database:disconnected` persists beyond a brief reconnect window, or any 5xx on core POS routes
ROLLBACK_ACTION=git revert both apps; if the shared venv changed, revert the venv too, then restart both
POSTCHECK=confirm Finance Core still reports healthy (business-suite/integrasi restarting shouldn't affect it, but it's the cheapest possible check)

### Wave 7 — stateful, independently-owned apps (each its own sub-wave, sequential, never parallel)
COMPONENTS=store, then parking, then drive, then restaurant (Seller Control) — four independent sub-waves, run one at a time, each with its own full precheck/health/rollback cycle, specifically BECAUSE none of them share a runtime or a dependency edge with each other. Grouping them under one wave number is bookkeeping convenience, not a claim that they're coupled — a failure in one must never pause or roll back another.
WHY_GROUPED=All four are customer-facing, stateful, and each has its own dedicated storage (Store: SQLite orders; Parking: dedicated Postgres; Drive: bind-mounted file storage + SQLite meta; Restaurant Seller Control: SQLite licenses.db) — highest real-world stakes if something goes wrong, hence last and most cautious.
EXPECTED_DOWNTIME=one restart/recreate each, seconds to ~10s for Docker recreate; schedule each for its own lowest-traffic window, not necessarily the same window
PRECHECK=per REDEPLOY-MAP.md's per-component recipe; for Docker components (drive, restaurant), confirm the new image builds and passes its own isolated health check BEFORE recreating the live container (exactly as proven this session)
DEPLOY_ACTION=Store: release-dir + `current` symlink flip. Parking: restart against new source in the same directory (no release-dir pattern exists yet — see Section 3 caveat). Drive, Restaurant: `docker compose up`/`docker run` with the new image tag, replacing the old container. NOT executed in this plan.
HEALTH_GATE=Store: liveness signal (no dedicated `/health`). Parking: `/parking/api/health` → `{"status":"ok",...}`. Drive: `/health` → `{"status":"ok",...}`. Restaurant: HTTP 200 on its served route.
REAL_FUNCTION_GATE=Store: a real product-page render succeeds. Parking: a real authenticated read (not just the 401 seen in this session's ephemeral-DB proof) succeeds against production data. Drive: a real file listing/read succeeds. Restaurant: a real license-status read succeeds.
ROLLBACK_TRIGGER=health gate fails, or (for parking/drive specifically) any data-path error suggesting the new code can't read existing production rows/files
ROLLBACK_ACTION=Store: flip `current` back. Parking: restart against the previous source in place. Drive/Restaurant: recreate the container from the previous image tag.
POSTCHECK=for each: confirm no other, unrelated wave's components regressed (they shouldn't — zero shared runtime — but a cheap platform-wide health sweep costs little and catches surprises)

```
CUTOVER_WAVES=8 (0 through 7, per above)
CUTOVER_ORDER=0 → 1 (public-site — RETIRED/BLOCKED, see correction above; not orderable until homepage-runtime convergence is resolved) → 2 (finance-core, ai-chat-preview) → 3 (connector-core + 6 shipping) → 4 (ai-workspace) → 5 (admin-gate) → 6 (multichannel + business-suite + integrasi) → 7 (store, parking, drive, restaurant — sequential sub-waves)
```

## 6. Public capability gate (unchanged, restated)

A successful cutover changes WHERE code runs from, never WHAT is proven
about external providers. Post-cutover, re-read
`docs/capability-registry/EXTERNAL-PROVIDERS.md` and
`docs/capability-registry/PUBLIC-SURFACE.md` as still authoritative:

- RajaOngkir shipping cost — remains LIVE (re-verify with one real call post-cutover, same as Wave 3's REAL_FUNCTION_GATE)
- Google Sheets — remains MOCK_ONLY, not public-ready, regardless of a successful connector-core cutover
- Midtrans — remains BETA_SANDBOX, store's manual-payment path remains the only PUBLIC_READY payment claim
- Google Drive/Picker — remains PARTIAL_UNPROVEN
- Telegram — remains PARTIAL_UNPROVEN
- AI Preview — remains BETA regardless of ai-chat-preview's cutover succeeding

```
PUBLIC_CAPABILITY_GATE_PRESERVED=YES
```

## 7. Data safety (stateful components)

| COMPONENT | DATA_LOCATION | BACKUP_AVAILABLE | MIGRATION_REQUIRED | SCHEMA_CHANGE_EXPECTED |
|---|---|---|---|---|
| store | `$STORE_DATA/store.db` (SQLite) | UNKNOWN — not verified this pass | NO (canonical source is byte-identical to live release) | NO |
| business-suite / integrasi | shared Postgres (host/instance not independently confirmed this pass) | UNKNOWN | NO (no schema-affecting change proposed by this plan) | NO |
| finance-core | Postgres, container `botconnector-core-postgres` | UNKNOWN | NO | NO |
| parking | dedicated Postgres, container `botconnector-parking-postgres` | UNKNOWN | Only if new migrations exist beyond the 5 already applied in production — not the case today (canonical repo's alembic history matches what this session ran) | NO beyond already-applied migrations |
| drive | bind-mounted `/mnt/botconnector-storage` + `/var/lib/botconnector-drive/{tmp,meta}` | UNKNOWN | NO | NO |
| restaurant (Seller Control) | `$LICENSE_DB` (SQLite) | UNKNOWN | NO | NO |
| shipping/* (all 6) | per-service SQLite ledgers | UNKNOWN | NO | NO |
| ai-chat-preview | Postgres, schema `$AI_CHAT_SCHEMA` | UNKNOWN | NO | NO |

**No component in this plan requires a schema mutation or data migration
to cut over** — every proposed cutover reuses existing production data
in place (new code pointed at the same data store, not a data move).
`BACKUP_AVAILABLE`/`BACKUP_AGE` are marked UNKNOWN throughout because this
phase is read-only and did not verify backup freshness for any production
datastore — that verification should happen as its own precheck before
any real cutover, not be assumed from this plan.

```
STATEFUL_COMPONENTS=store, business-suite, finance-core, parking, drive, restaurant, 6×shipping, ai-chat-preview (13 total; integrasi and admin-gate are the only app-tier components confirmed stateless)
SCHEMA_MIGRATIONS_REQUIRED=NO
```

## 8. Secret safety

Every recipe in `docs/deployment/REDEPLOY-MAP.md` already sources secrets
from existing protected mechanisms only:
- `/etc/botconnector/credentials/*` (systemd `LoadCredential` — business-suite, integrasi)
- `/etc/botconnector*/*.env` files (root-only, 600/640 perms — store, finance-core, shipping, drive, etc.)
- Docker `-e` flags reading from the same external env files at container-start time (restaurant, drive)

No recipe embeds a secret value in a release artifact, and none of this
session's docs contain one (verified repeatedly across every commit this
consolidation made — see the secret scans in each phase's report).

```
SECRET_VALUES_IN_REPO=0
SECRET_VALUES_IN_RELEASE_ARTIFACT=0
```
