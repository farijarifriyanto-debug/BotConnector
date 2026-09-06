# Retirement Map

**BUILT, NOT EXECUTED.** No path listed below has been deleted, moved, or
modified. Per your explicit gate (docs/migration/RETIREMENT-POLICY.md):
retirement of anything in `DELETE_AFTER_CUTOVER` may only happen after
that component's cutover has passed AND its rollback window has closed —
neither has happened for any component yet (no cutover has occurred at
all). This document extends RETIREMENT-POLICY.md with a concrete,
evidence-based path list instead of that document's earlier
category-only sketch.

Classification values used below: `DELETE_AFTER_CUTOVER`,
`KEEP_ACTIVE_RELEASE`, `KEEP_ROLLBACK_RELEASE`, `KEEP_RUNTIME_DATA`,
`KEEP_SECRET_CONFIG`, `KEEP_EXTERNAL_ECOSYSTEM`, `KEEP_AI_BUILDER`,
`ARCHIVE_ONLY`.

## Registered Git worktrees

Checked every BotConnector-related git repo on this box
(`git worktree list` in each): `BotConnector-Parking`,
`botconnector-full-site-poc`, `BotConnector` (AI Builder), and
`BotConnector-Platform` itself. **None have a linked worktree** — each
shows exactly one entry (itself). There is nothing to `git worktree
remove` on this box today. If one appears later, remove it with
`git worktree remove` then `git worktree prune` for stale metadata — never
raw-delete the directory.

## v6 / v6r1 / v6r2 / v6r3 store duplicates (new finding this phase)

| PATH | CLASSIFICATION | NOTES |
|---|---|---|
| `/home/botadmin/botconnector-store-production-v6r3-final` | KEEP_ACTIVE_RELEASE | this is the canonical import source for `apps/store` — proven byte-identical to the live release |
| `/home/botadmin/botconnector-store-production-v6r2-final` | DELETE_AFTER_CUTOVER | superseded, not the source of anything canonical |
| `/home/botadmin/botconnector-store-production-v6r1-final` | DELETE_AFTER_CUTOVER | superseded |
| `/home/botadmin/botconnector-store-production-v6-final` | DELETE_AFTER_CUTOVER | superseded |
| `/home/botadmin/backup/BotConnector-Store-Production-V6R3-FINAL-2026-08-12.zip` | ARCHIVE_ONLY | keep as a point-in-time archive; not part of any active or rollback path |
| `/home/botadmin/backup/BotConnector-Store-Production-V6R2-FINAL-2026-08-12.zip` | ARCHIVE_ONLY | |
| `/home/botadmin/backup/BotConnector-Store-Production-V6R1-FINAL-2026-08-12.zip` | ARCHIVE_ONLY | |
| `/home/botadmin/backup/BotConnector-Store-Production-V6-FINAL-2026-08-12.zip` | ARCHIVE_ONLY | |

## Live homepage runtime — newly identified 2026-09-06, NOT a delete candidate

| PATH | CLASSIFICATION |
|---|---|
| `/opt/botconnector-platform-starter-v0.3/homepage` | **ACTIVE_LIVE_SOURCE_PENDING_CONVERGENCE** — this is the real source for the live botconnector.id apex (Docker container `botconnector-platform-home`), hash-verified against the running image. It is not yet imported into the canonical repo and not yet superseded by anything. Do not classify as DELETE_AFTER_CUTOVER, ARCHIVE_ONLY, or any other retirement category until `docs/provenance/HOMEPAGE-CONVERGENCE.md`'s convergence decision (a canonical `apps/homepage-runtime` import) is actually carried out and proven. |

## Old `/opt` source trees (live production — the actual deployables)

These stay live until their own component's cutover succeeds AND passes
its rollback window (see ROLLBACK-PLAN.md `MAX_ROLLBACK_TIME` per
component for the minimum window to respect).

| PATH | CLASSIFICATION |
|---|---|
| `/opt/botconnector-store` (+ `releases/`, `current`) | KEEP_ACTIVE_RELEASE now → DELETE_AFTER_CUTOVER once store's canonical deployment is proven in production and past rollback window |
| `/opt/botconnector-bisnis` | same pattern (business-suite) |
| `/opt/botconnector-integrasi` | same pattern (integrasi) |
| `/opt/botconnector-multichannel` (+ its `venv`) | same pattern — KEEP until business-suite/integrasi's shared runtime cutover is proven; note the `/opt/botconnector_multichannel` (underscore) symlink retires with it, not before |
| `/opt/botconnector-finance-core` (+ `releases/`, `evidence/`) | KEEP_ACTIVE_RELEASE + KEEP_ROLLBACK_RELEASE (evidence/ historical candidates) until proven |
| `/opt/botconnector-connector-core` (+ `releases/`, `current`, shared `venv`) | same pattern |
| `/opt/botconnector-shipping-{integration,location-resolver,location-public-gateway,public-gateway,router}` | same pattern, one per service |
| `/opt/botconnector-shipping-providers/rajaongkir-cost` | same pattern |
| `/opt/botconnector-drive` (image build context; the running container uses the built image, not this dir directly at runtime) | KEEP_ACTIVE_RELEASE until proven |
| `restaurant-seller-control` (Docker image, not a source dir on disk in the same sense) | KEEP_ACTIVE_RELEASE (image tag) until proven |
| `/home/botadmin/ai-workspace` | KEEP_ACTIVE_RELEASE until proven |
| `/home/botadmin/admin-gate` | KEEP_ACTIVE_RELEASE until proven |
| `/home/botadmin/ai-workspaces/BotConnector-Parking` | KEEP_ACTIVE_RELEASE until proven — this is also a live git repo (see worktree check above), not just a deploy path |
| `/opt/botconnector-ai-chat` (+ `releases/`) | KEEP_ACTIVE_RELEASE until proven |
| `/opt/restaurant-seller-control` | KEEP_ACTIVE_RELEASE (source for the restaurant image) until proven |

## Non-live shipping siblings (already excluded from active service source — Decision 1, earlier phase)

| PATH | CLASSIFICATION |
|---|---|
| `/opt/botconnector-shipping-core` | ARCHIVE_ONLY (LEGACY — no active unit, release history present) |
| `/opt/botconnector-shipping-stack` | ARCHIVE_ONLY (LEGACY) |
| `/opt/botconnector-shipping-location-index` | ARCHIVE_ONLY (ARCHIVE_CANDIDATE — only a `candidates/` subfolder) |

## Duplicate / superseded (already found, not new this phase)

| PATH | CLASSIFICATION |
|---|---|
| `/opt/botconnector-core` | **CORRECTED 2026-09-06 — do not delete.** The directory's *source* content is still an unreferenced connector-core-shaped legacy tree (no systemd unit or container runs code from it directly). But `/opt/botconnector-core/.env` specifically is **ACTIVE_SECRET_STORE_PENDING_MIGRATION** — it is the live `env_file` for `botconnector-backend-api` and `botconnector-backend-worker` (project `botconnector-backend-core`, compose file `/opt/botconnector-backend-core/docker-compose.yml`), discovered during the SMTP credential incident response. **DO_NOT_DELETE** until that credential is migrated to a protected file mechanism and the plaintext value is removed from this `.env` (see `docs/security/SMTP-CREDENTIAL-INCIDENT.md`). The original "no systemd unit references it" check was true but incomplete — it missed a Docker Compose `env_file:` reference, which isn't visible to a systemd-only search. |
| `/home/botadmin/ai-workspaces/botconnector-homepage-design-poc` | ARCHIVE_ONLY — a second design candidate not chosen for `packages/shared-design`; not wired to anything live |

## Completed / candidate POCs (public-site provenance)

| PATH | CLASSIFICATION |
|---|---|
| `/home/botadmin/ai-workspaces/botconnector-full-site-poc` | KEEP_ACTIVE_RELEASE — this is the canonical import source for `apps/public-site`, classified FUTURE_CANONICAL_SOURCE; not retirable, it's the thing being promoted |
| `/home/botadmin/ai-workspaces/botconnector-design-master` | KEEP_ACTIVE_RELEASE — canonical import source for `packages/shared-design` |

## Static `/var/www` deployment outputs (never imported as source — documented, not retirable by this plan)

All of these are DEPLOYMENT_CURRENT_STATE_REFERENCE — they are what's
*currently serving* botconnector.id and its sub-apps, not source. They
stay live until whatever replaces them (e.g. a real `apps/public-site`
cutover) is proven and past its own rollback window. This plan does not
propose deleting any of them; that decision belongs to the eventual
public-site/marketing cutover, out of scope here.

| PATH | CLASSIFICATION |
|---|---|
| `/var/www/botconnector` (static files at the old apex path) | **CORRECTED 2026-09-06 — ARCHIVE_ONLY, not KEEP_RUNTIME_DATA as previously stated here.** This is NOT what's actually live. The real botconnector.id apex is served by the Docker application `botconnector-platform-home` (port 8020) via nginx `proxy_pass`, not by static files from this path. This directory appears to be an unused/legacy static artifact from before the dynamic homepage existed. Not verified as safe to delete — reclassified from an incorrect "currently live" status to "needs its own investigation," not to DELETE_AFTER_CUTOVER, since its actual purpose (if any) is still unconfirmed. |
| `/var/www/botconnector-store/current` | KEEP_RUNTIME_DATA |
| `/var/www/botconnector-shipping-public/current` | KEEP_RUNTIME_DATA |
| `/var/www/botconnector-ai-console/current`, `-ai-r73-preview`, `-ai-chat-web-r17-*` | KEEP_RUNTIME_DATA (also: these back the EXCLUDED AI cluster, see KEEP_AI_BUILDER note below) |
| `/var/www/botconnector-business-suite`, `-restaurant`, `-retail`, `-shared-design`, `-integrations`, `-integration-hub`, `-connector-marketplace`, `-recipe-marketplace`, `-solutions`, `-automation-docs`, `-automation-home`, `-seo` | KEEP_RUNTIME_DATA (all confirmed no `.git`/source — pure build output; retiring any of these is a marketing-site decision, not a source-consolidation one) |

## Runtime data (never touched, never proposed for deletion, anywhere in this plan)

| PATH | CLASSIFICATION |
|---|---|
| All Postgres containers/volumes (`botconnector-core-postgres`, `botconnector-parking-postgres`, and whichever backs business-suite/integrasi) | KEEP_RUNTIME_DATA |
| Redis instances (`botconnector-core-redis`, if actually load-bearing — see CURRENT-STATE.md note that multichannel's own use of redis was found only in a test/acceptance script, not core runtime) | KEEP_RUNTIME_DATA |
| `/mnt/botconnector-storage`, `/var/lib/botconnector-drive/*` | KEEP_RUNTIME_DATA |
| Every SQLite file under any `/opt/botconnector-*` runtime path (store, shipping ledgers, restaurant licenses.db) | KEEP_RUNTIME_DATA |

## Secret/config (never in scope for deletion or repo inclusion)

| PATH | CLASSIFICATION |
|---|---|
| `/etc/botconnector/credentials/*`, `/etc/botconnector*/*.env`, `/etc/botconnector/secrets/*` | KEEP_SECRET_CONFIG |

## Explicit exclusions (out of scope for this entire consolidation, restated)

| PATH | CLASSIFICATION |
|---|---|
| `/home/botadmin/ai-workspaces/BotConnector` (AI Builder / Control Plane — also the working directory this session itself runs in) | KEEP_AI_BUILDER |
| Connect / trading / webhook ecosystem (per the VPS-wide CLAUDE.md: `codex-webhook-hub`, trading-lab, market-brain, etc.) | KEEP_EXTERNAL_ECOSYSTEM |
| long-horizon/restate research candidates (`botconnector-long-horizon-v3*`, `botconnector-restate-v3-candidate`, observed as running Docker containers during this session's incidental `docker ps` output) | KEEP_EXTERNAL_ECOSYSTEM |
| The excluded internal AI cluster (ai-console, ai-tool-platform, ai-mission-runner, desktop-ai-gateway, windows-tool-adapter) and its backing `/var/www` outputs | KEEP_AI_BUILDER (per your Phase 1 decision: only ai-chat-core is in scope for this platform; the rest is a different, excluded system) |

## Not yet audited (flagged, not classified)

A handful of Docker containers seen incidentally during this session's
`docker ps` output are NOT part of this consolidation's known component
list. **`botconnector-platform-home` (tenantization-v1) is now RESOLVED**
as of 2026-09-06 — see the "Live homepage runtime" section above; it was
in this unresolved list only because it hadn't yet been connected to the
live apex. The rest remain genuinely unresolved and were never
investigated: `botconnector-v2-app`, `botconnector-support-ai`,
`botconnector-searxng`, `botconnector-ai-*`
(console/local-intelligence/pgvector/llama-chat/llama-embed),
`botconnector-backend-core`/`botconnector-backend-worker`/`-api`
(labeled "smartbiz-ai-studio"/"smartbiz-internal-actions"), `anythingllm-*`,
`olahdokumen-*`, `maxkb-poc`, `onlyoffice-poc`. **Flag, not conclusion:**
the "smartbiz-ai-studio"/"smartbiz-internal-actions" labels on
`botconnector-backend-core`/`-worker`/`-api` match module names found in
the homepage source this pass (`smartbiz_ai_studio.py`,
`smartbiz_operations_ui.py`) — these may be the actual backend(s) those
homepage modules proxy to. Not traced further; do not assume this
correlation is confirmed. Some of these may overlap with the excluded AI
cluster or Connect ecosystem; none were traced. Do not assume any of
these are safe to touch based on this document — they remain UNRESOLVED,
not KEEP or DELETE.

```
UNKNOWN_SOURCE_OWNERSHIP=the containers listed immediately above (count not
  precisely enumerable without further investigation — flagged, not zero)
```

---

## Section 11 target — one-repo end state

```
CANONICAL_SOURCE_REPO=/home/botadmin/ai-workspaces/BotConnector-Platform
BOTCONNECTOR_MAIN_BUSINESS_SOURCE_REPOS=1
PERSISTENT_MAIN_WORKTREES=1
```

`UNKNOWN_SOURCE_OWNERSHIP=0` cannot be claimed honestly today — the
"Not yet audited" section above is real, non-zero unresolved ownership,
found incidentally while checking for worktrees, not chased down (out of
this phase's scope: source *retirement* planning for the 20 known
canonical components, not a full-box container audit). Flagging rather
than rounding down to 0.
