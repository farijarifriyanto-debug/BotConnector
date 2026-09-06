# Retirement Policy — Final Cleanup End-State

Recorded 2026-09-06 per explicit instruction. This is a policy for a LATER
phase — nothing in this document has been executed. No source was deleted,
no worktree was touched, no runtime was changed to produce this file.

## Target end-state

```
ONE_CANONICAL_REPO=/home/botadmin/ai-workspaces/BotConnector-Platform
ONE_PERSISTENT_MAIN_WORKTREE=YES
BOTCONNECTOR_PLATFORM_REPOS_FOR_MAIN_BUSINESS=1
PERSISTENT_MAIN_WORKTREES=1
DUPLICATE_SOURCE_TREES=0
STALE_POCS=0
UNKNOWN_CANONICAL_SOURCES=0
CANONICAL_SOURCE_OF_TRUTH=BotConnector-Platform
```

Every future deployment must trace back to a commit in the canonical repo.

## Gate — preconditions before ANY retirement action

All of the following must be true, per component, before its old source is
touched:

1. Imported into the canonical repo (done for 18/19 targets as of the
   Day-Zero baseline commit `4918b2e` — see docs/provenance/SOURCE-MAP.md)
2. Provenance documented (SOURCE-MAP.md + LEGACY-PATHS.md)
3. Provider readiness classified (docs/capability-registry/EXTERNAL-PROVIDERS.md)
4. Build/redeploy proven **from the canonical repo**
5. Production cutover PASS
6. Rollback proven

**Current status: only steps 1–3 are done. Steps 4–6 have not happened —
this session has not built, deployed, cut over, or rolled back anything.**
Per your explicit instruction ("Jangan lakukan cleanup sampai cutover gate
seluruh component PASS"), no deletion or worktree removal may happen until
every component clears all six steps. This document exists so that future
phase knows the rule; it does not itself authorize cleanup.

## Delete candidates (once the gate above is PASS — not yet)

Categories, per your instruction: duplicate source trees, old home-dir
copies, v6/v6r1/v6r2-style source copies, stale candidate trees, completed
POCs, old design POCs, superseded source snapshots, obsolete Git repos,
retired linked worktrees, and /opt source trees the runtime no longer
uses.

This session already surfaced some candidates while building
LEGACY-PATHS.md — listed here as a starting point for the eventual audit,
**not vetted for deletion yet**:

- `/opt/botconnector-core` (DUPLICATE — no live systemd unit; canonical
  connector-core is `/opt/botconnector-connector-core`)
- `/home/botadmin/ai-workspaces/botconnector-homepage-design-poc`
  (DUPLICATE — a second design candidate not chosen for packages/shared-design)
- `/opt/botconnector-shipping-core`, `/opt/botconnector-shipping-stack`
  (LEGACY — release history present, no active systemd unit)
- `/opt/botconnector-shipping-location-index` (ARCHIVE_CANDIDATE — only a
  `candidates/` subfolder)

A full sweep for v6/v6r1/v6r2-style copies, stale POCs, and obsolete repos
across the box was **not performed in this pass** — that's the retirement
audit itself, which per your instruction happens after cutover, not now.

For any candidate that turns out to be a registered Git worktree: use
`git worktree remove`, then `git worktree prune` for stale metadata. Never
raw-delete a worktree directory.

## Never delete (standing rule, not conditional on the gate)

Postgres data/volumes, Redis persistence, active SQLite runtime data,
uploads/customer data, `/etc/botconnector` protected credentials, active
deployment artifacts, required runtime config, the current release, the
rollback release during its rollback window, the Connect/trading/webhook
ecosystem, and the AI Builder / Control Plane repo
(`/home/botadmin/ai-workspaces/BotConnector`).

## Public capability rule

Source living in the canonical repo does not by itself authorize a
capability to appear on botconnector.id. Only a capability whose registry
entry in docs/capability-registry/EXTERNAL-PROVIDERS.md (or an equivalent
future entry) reads:

```
STATUS=LIVE
PROVIDER_READY=YES
REAL_E2E_PROVEN=YES
PUBLIC_READY=YES
```

may be promoted as an available production feature. Per the current
registry, that's RajaOngkir shipping cost lookup and Store manual
checkout only — everything else (Midtrans/QRIS, Google Sheets, Google
Drive/Picker, Telegram, Parking payment) stays unpromoted until re-proven.
PARTIAL_PROVIDER_BLOCKED / BETA_SANDBOX / LEGACY / UNKNOWN entries must not
be presented as production-ready.
