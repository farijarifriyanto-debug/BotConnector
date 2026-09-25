# Phase 8: Canvas, Selection, and Direct Editing

## Status

**CONDITIONAL — VNext user slice and Control API slice pass independently; production end-to-end integration is not proven**

## Base

- Previous committed Phase 7 head: `04dc0ec`
- Phase 8 implementation is currently uncommitted.

## Grand Design Alignment

This slice follows the Grand Design requirements that:

- the artifact work surface is represented by declarative UI-IR;
- selections are bound to the UI-IR revision and only reference existing nodes;
- deterministic direct edits target explicit content, layout, style, or token paths;
- every mutation is tenant-scoped, revision-checked, and emitted as a durable domain event;
- Canvas state is not treated as canonical source code.

## Implemented

- Added the shared `DirectEditCommandSchema` and `DirectEditTargetSchema`.
- Added tenant-scoped Canvas create/list/read routes backed by `design.canvases`.
- Added revision-bound SelectionContext creation.
- Added deterministic direct edits for node content, layout, style, and tokens.
- Added optimistic concurrency with `If-Match` and UI-IR validation after mutation.
- Added `canvas.created` and `canvas.direct_edit_applied` domain events.
- Added cross-workspace isolation and stale revision acceptance coverage.
- Implemented the corresponding OlahDokumen vNext Builder surface in
  `/home/botadmin/olahdokumen-vnext` with a persisted local canvas, selectable
  UI-IR-like nodes, contextual inspector, and direct-edit controls.

## API Surface

- `POST /api/v1/projects/:projectId/canvases`
- `GET /api/v1/projects/:projectId/canvases`
- `GET /api/v1/canvases/:canvasId`
- `POST /api/v1/canvases/:canvasId/selections`
- `POST /api/v1/canvases/:canvasId/direct-edits`

## Validation Evidence

- Contracts: `43` tests passed.
- Control: `156` tests passed.
- Database: `47` tests passed.
- Sandbox manager: `105` tests passed.
- Root build and control/contracts typechecks passed.
- `npm run test:all` passed.
- `git diff --check` passed.
- vNext Builder `npm test` passed: `69` passed, `3` skipped.
- Authenticated browser acceptance passed on project
  `f075dbba-3bb9-43a0-9d4a-90576c4d1e01`: created a Builder surface, selected
  `builder-heading`, edited its content through the inspector, observed
  revision `1` and `Tersimpan`, then reloaded and verified the edited value
  persisted.
- Desktop and mobile Builder screenshots were captured as
  `phase8-builder-accepted.png` and `phase8-builder-mobile.png`.
- Browser console reported `0` errors and `0` warnings during acceptance.

## Independent Full Audit Reconciliation

- The authenticated VNext browser path is real and functional: its Next.js
  service is active on `127.0.0.1:47100`, and project/canvas create, edit,
  stale-revision rejection, and reload persistence were exercised over HTTP.
- The VNext Builder persists project and canvas data in local SQLite through
  `src/engine/persistence/projectStore.ts`; it does not call the BotConnector
  Canvas API or PostgreSQL control plane.
- BotConnector Canvas routes were exercised over an ephemeral HTTP server with
  an explicitly injected test principal and real PostgreSQL. They passed the
  create, artifact, canvas, selection, direct-edit, and read sequence, but the
  repository has no deployable production Control API entrypoint: direct
  execution exits because no production `PrincipalResolver` is configured.
- Therefore the evidence supports two independently working slices, not one
  production end-to-end Canvas path. This is a release blocker for a claim that
  the full Phase 8 architecture is operational.
- The aggregate Control test suite failed on the first two full audit runs:
  `155/156` passed with the crash-after-publish WebSocket test timing out;
  subsequent isolated and aggregate reruns passed (`156/156`). The latest
  aggregate `npm run test:all` passed, but the observed intermittent timeout
  remains a test determinism risk.
- The audit corrected two build-gate configuration defects: Sandbox Manager now
  builds from its existing `tsconfig.json`, and the migration-only database
  package no longer advertises nonexistent TypeScript build/typecheck scripts.
  Database migration tests passed (`47/47`).

## Explicit Non-Goals

- No frontend application was introduced inside this BotConnector repository;
  the approved builder UI lives in the separate vNext application listed above.
- No Git source mutation, changeset apply, checkpoint, or deploy behavior was
  added. Those remain later source-of-truth boundaries.
- No live generation cursor, brush, timer animation, or AI editing was added.

## Next Gate

The VNext user-facing acceptance is complete, but the Phase 8 architecture gate
remains open until the Canvas data path is unified or explicitly declared as a
separate boundary, a production Control API/auth entrypoint exists, and the
aggregate test/build gates are deterministic and green. Phase 9 must not start.
The runtime correctly returns `403` without the canary allowlist/session; no auth
bypass was used.
