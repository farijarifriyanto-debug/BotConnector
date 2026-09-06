# Current State — BotConnector Platform

Documents what is actually deployed and running today, as of the
2026-09-06 consolidation pass. This is a description of reality, not a
target design. No system was changed to produce this document.

## Deployment topology

Every module below runs as its own OS-level process (systemd unit or
Docker container) on the single VPS this platform lives on. There is no
shared application runtime — "module" here means a source tree with its
own process, not a library boundary within one binary.

| Module | Live runtime | Canonical target |
|---|---|---|
| Public Site | none (static POC only, not deployed) | `apps/public-site` |
| Store | `botconnector-store.service` | `apps/store` |
| Business Suite | `botconnector-bisnis.service` (thin entrypoint over Multichannel) | `apps/business-suite` |
| Integrasi | `botconnector-integrasi.service` (thin entrypoint over Multichannel) | `apps/integrasi` |
| Restaurant Seller Control | Docker container `restaurant-seller-control` — a licensing/entitlement panel, NOT the Restaurant POS feature (that's inside Business Suite) | `apps/restaurant` |
| Parking | `botconnector-parking.service` | `apps/parking` |
| Drive | `botconnector-drive.service` | `apps/drive` |
| AI Preview | `botconnector-ai-chat-core.service` | `apps/ai-chat-preview` |
| AI Workspace | `ai-workspace.service` | `apps/ai-workspace` |
| Admin Gate | `admin-gate.service` | `apps/admin-gate` |
| Multichannel | (shared package — see below) | `packages/multichannel` |
| Connector Core | `botconnector-connector-core.service` | `services/connector-core` |
| Finance Core | `botconnector-finance-core.service` | `services/finance-core` |
| Shipping (6 services) | see below | `services/shipping/*` |

Full per-component detail (exact paths, nginx routes, confidence) is in
`docs/provenance/SOURCE-MAP.md` — this document is the shape, that one is
the evidence.

## Seams

**Admin Gate is the platform's one cross-cutting seam.** Every panel route
for every other module (`/panel/restaurant/`, `/panel/ai/`, etc.) sits
behind an nginx `auth_request` call into Admin Gate. Callers (nginx, and
transitively every vertical's admin UI) only need to know one thing about
this seam: does this request get a 2xx or a 401/403. None of them know how
Admin Gate decides that. That's a deep module by this platform's own
`codebase-design` vocabulary — worth preserving as the single seam if this
platform is ever restructured, rather than letting individual verticals
grow their own auth checks.

**Shipping is not one module — it's a cluster of six adapters behind no
shared interface yet.** `router`, `location-resolver`,
`location-public-gateway`, `public-gateway`, `integration`, and
`rajaongkir-cost` are six independently deployed processes, each with its
own systemd unit and port. `public-gateway` is the one exposed to the
public internet (`/pengiriman/`, `/konektor/rajaongkir/`); the other five
are internal. There is currently no single "Shipping" interface a caller
goes through — callers (nginx, or other modules) reach whichever of the
six they need directly. Two live non-live siblings (`core-legacy`,
`stack-legacy`) and one draft (`location-index-archive-candidate`) exist on
disk with no active unit — see LEGACY-PATHS.md. This fragmentation is
recorded as observed reality, not endorsed; if this platform is
restructured later, whether these six belong behind one Shipping interface
or stay independently deployed is an open design question, not answered
here.

CONFIRMED LIVE END-TO-END (2026-09-06): a real, non-destructive request
through `public-gateway` (port 18244) → `integration` (port 18243) →
RajaOngkir returned real courier quotes for a Jakarta→Bandung shipment in
~1.5s. This is the strongest evidence in this entire audit — an actual
successful request through the whole chain, not an inference from code or
config. See docs/capability-registry/EXTERNAL-PROVIDERS.md.

**Multichannel is a shared package with two thin entrypoints on top —
proven, not inferred.** `packages/multichannel` is imported directly by
two separate FastAPI processes: `/opt/botconnector-bisnis/app.py`
(Business Suite, port 18199) and `/opt/botconnector-integrasi/app.py`
(Integrasi, port 18198). Both do the identical trick —
`sys.path.insert(0, "/opt")` then `import botconnector_multichannel` —
which resolves through a literal symlink, `/opt/botconnector_multichannel`
(underscore, importable) → `/opt/botconnector-multichannel` (hyphen, this
package's real directory). Both run on Multichannel's own venv
interpreter and both require `botconnector-finance-core.service` to start.
This is "one shared package, two thin application entrypoints" — the
cleanest of the three shapes this document originally left open. Business
Suite (`/bisnis/api/*`) is the deep one: POS, inventory, restaurant/
kitchen, transfers, reporting, offline sync — all real, live, DB-backed
(`database: connected` on health check). Integrasi (`/integrasi/`) is
shallow by design today: a single read-only marketplace-status page whose
own docstring says "Tidak memanggil keluar. Tidak membuka token" (no
outbound calls, no token exposure) — its Shopee/Tokopedia/TikTok
Shop/Blibli/Lazada cards are hardcoded "Segera Hadir" (Coming Soon), not
live integrations.

## Naming collision (resolved)

**"Restaurant" means two unrelated things on this platform.** The
public-site `/restaurant/` page markets recipe/BOM, table management, and
Kitchen Display (KDS/KOT) — that capability is real and lives inside
**Business Suite** (`/bisnis/api/restaurant`, `/bisnis/api/kitchen`), not
in `apps/restaurant`. `apps/restaurant` (Docker container
`restaurant-seller-control`) is actually a licensing/entitlement admin
panel — edition tiers (Essential, Lengkap, Professional, Multi Outlet),
EC-signed license issuance — unrelated to kitchen operations. Anyone
reading "Restaurant" in this repo without this note would reasonably
assume `apps/restaurant` is the POS feature; it is not.

## Known gaps (not invented, not resolved)

- **Public Site vs. live homepage**: the live botconnector.id root
  (`/var/www/botconnector`) has no discoverable source or generator. The
  imported `apps/public-site` (from the `full-site-poc`) is a candidate for
  becoming that source, not a proven replica of what's live today.
- **Telegram outbox reliability**: `botconnector-bisnis-telegram-outbox.service`
  logs showed a burst of `low_stock_outbox_poll_error (OperationalError)`
  roughly every 2 seconds for about a minute, ending in a service restart
  at 09:35:37 today, timed close to a Postgres/Redis credential rotation
  observed the same morning (fresh files under `/etc/botconnector/credentials/`
  dated today). Post-restart the worker reports `db_poll_ready` with no
  further errors, and Business Suite/Integrasi/Finance Core show zero
  errors in the last 2 hours — reads as a resolved, isolated blip tied to
  the credential rotation, not an ongoing problem. Flagging because this
  session did not cause it and did not restart anything — purely observed
  via `journalctl`, read-only.

## Component count: 20 total, 19 deployable

`docs/provenance/SOURCE-MAP.md` lists 20 canonical components. 19 are
independently deployable and redeploy-proven end-to-end (see
`docs/build-proof/BUILD-REDEPLOY-PROOF.md`). The 20th, `packages/shared-design`,
is a static asset/documentation package with `LIVE_RUNTIME=NONE` — there is
nothing to build, start, or redeploy for it; "proof" doesn't apply to it
any more than it would to a README. See `docs/deployment/CUTOVER-PLAN.md`
Section 0 for the full reasoning.

## Redis: present in a dependency lockfile, not load-bearing in core runtime

`packages/multichannel/requirements.lock.txt` includes `redis==8.1.0`, but
the only actual `import redis` found in the package is inside
`local_business/acceptance_low_stock.py` — a test/acceptance script, not
the main Business Suite or Integrasi request path. Do not assume Redis is
a hard runtime dependency for Business Suite/Integrasi based on the
lockfile alone; it isn't, as far as this investigation found.

## Process safety guardrail (added after a near-miss, 2026-09-06)

A broad `pkill -f "uvicorn app:APP"` during an isolated build-proof test
matched the exact command-line substring of live production
business-suite, integrasi, and shipping processes. It did not kill them
(confirmed immediately after and re-confirmed later — all remained
`active`, uninterrupted), but the pattern itself was unsafe. Documented in
full, with the required procedure for future isolated tests, in
`docs/deployment/CUTOVER-PLAN.md` Section 1 — treat that section as a
standing rule for this repo, not a one-time note.
