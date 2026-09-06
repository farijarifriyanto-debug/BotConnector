# Legacy Path Classification

Nothing listed here has been deleted, moved, or modified. This is a
read-only classification of what exists on disk today, made during the
2026-09-06 consolidation pass. Every canonical source below is still the
live production location — the monorepo is a COPY.

## ACTIVE_SOURCE_PENDING_CUTOVER
(Still the real, live source. Stays in place until you explicitly run a
cutover phase — not part of this task.)

- /home/botadmin/botconnector-store-production-v6r3-final (store)
- /opt/restaurant-seller-control (restaurant, Docker container)
- /home/botadmin/ai-workspaces/BotConnector-Parking (parking)
- /opt/botconnector-drive (drive)
- /opt/botconnector-ai-chat/releases/ai-chat-core-r6-20260814T035154Z (ai-chat-core)
- /home/botadmin/ai-workspace (ai-workspace)
- /home/botadmin/admin-gate (admin-gate)
- /opt/botconnector-multichannel (multichannel)
- /opt/botconnector-connector-core (connector-core, via `current` symlink)
- /opt/botconnector-finance-core (finance-core)
- /opt/botconnector-shipping-{integration,location-resolver,location-public-gateway,public-gateway,router} (5 live shipping services)
- /opt/botconnector-shipping-providers/rajaongkir-cost (live, 6th shipping service)

## DEPLOYMENT_ARTIFACT
(Build/deploy output being served by nginx right now. Not source — do not
treat as canonical, do not import into the monorepo.)

- /var/www/botconnector (main botconnector.id document root)
- /var/www/botconnector-store/current
- /var/www/botconnector-shipping-public/current
- /var/www/botconnector-ai-console/current
- /var/www/botconnector-ai-r73-preview
- /var/www/botconnector-ai-chat-web-r17-desktop-job-bridge-v1.1-r2-20260815T030144Z
- /var/www/botconnector-business-suite, -restaurant, -retail, -shared-design,
  -integrations, -integration-hub, -connector-marketplace,
  -recipe-marketplace, -solutions, -automation-docs, -automation-home, -seo
  (all confirmed: no .git, no package.json, no sourcemaps — static output only)

## DUPLICATE
(A second copy or unrelated legacy directory competing with the chosen
canonical source. Not imported.)

- /opt/botconnector-core — legacy connector-core-shaped directory with no
  systemd unit pointing at it. Canonical connector-core is
  /opt/botconnector-connector-core (has the live unit). ARCHIVE_CANDIDATE
  once you confirm it's dead.
- /home/botadmin/ai-workspaces/botconnector-homepage-design-poc — a second
  design candidate, not imported; packages/shared-design was sourced from
  botconnector-design-master instead (more complete doc set). Confirm this
  choice — see SOURCE-MAP.md shared-design entry.

## ARCHIVE_CANDIDATE
- /opt/botconnector-shipping-location-index (only a `candidates/` subfolder,
  no live unit)
- /opt/botconnector-shipping-core, /opt/botconnector-shipping-stack (LEGACY,
  see SOURCE-MAP.md — has release history but no active unit today)

## EXTERNAL_ECOSYSTEM
(Explicitly out of scope per your Phase 1 provenance decisions — not
touched, not audited further in this pass.)

- /home/botadmin/ai-workspaces/BotConnector (AI Builder / Control Plane —
  this is also literally the working directory this Claude session was
  invoked in; nothing in it was read for consolidation purposes beyond
  confirming it's the excluded control-plane repo)
- Connect / trading / webhook ecosystem (per the VPS-wide CLAUDE.md: 
  codex-webhook-hub, trading-lab, market-brain, etc.)
- long-horizon/restate research candidates

## KEEP
- All Phase 2 backup archives under
  /home/botadmin/backups/botconnector-platform-consolidation/ — these are
  the source-of-truth snapshots, deliberately kept outside the canonical
  repo and outside git.

## NEEDS_DECISION (not classified — see SOURCE-MAP.md for detail)
- "business-suite" thin app: no source directory found anywhere on disk.
- The exact relationship between packages/multichannel
  (/opt/botconnector-multichannel) and the separately-deployed
  /opt/botconnector-bisnis and /opt/botconnector-integrasi working
  directories — not traced in this pass.
