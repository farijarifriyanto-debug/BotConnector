# Phase 4 Handoff

## PHASE

Phase 4: Event & Realtime Backbone

## STATUS

PASS / COMMITTED

## COMMIT HISTORY (TRUTHFUL SEQUENCE)

- `PHASE4_ORIGINAL_BASE_HEAD=0e7fd396a0c90403a364f82e30f7c7c5105c5cc7`
  Phase 3 FINAL checkpoint — where Phase 4 work originally started.
- `PRE_PHASE4_EVENT_CONTRACT_CORRECTION_HEAD=4f0519874bc7cff166c0a6a45e95df3da8ef1da9`
  Phase 1 correction: add generic domain event envelope.
- `PRE_PHASE4_SCHEMA_CORRECTION_HEAD=e518b136bfffb6ebdf9106dc369e86c0a8eb3905`
  Phase 2 correction: add durable event stream and outbox primitives.
- `PRE_PHASE4_CONTROL_CORRECTION_HEAD=2a5adc13496c61e65f7e522fec19c1b0983c42e5`
  Phase 3 correction: guard control entrypoint on import (6-line direct-entry
  guard, committed separately from Phase-4 implementation).
- `PHASE4_BASE_HEAD=2a5adc13496c61e65f7e522fec19c1b0983c42e5`
- `PHASE4_IMPLEMENTATION_HEAD=bed449e6f663fe05d7aa380dbbdccd833edbb29e`
  Phase 4: establish event and realtime backbone.
- Final Phase-4 repository checkpoint = the commit that contains this handoff
  file (Phase 4: finalize event and realtime backbone handoff). This handoff
  intentionally does not reference its own commit SHA.

## AI_CONTINUITY_SOURCE

opencode (mimo-v2.5-free)

## CROSS_AI_CONTINUITY_RESULT

PASS

- CROSS_AI_HANDOFF_READ=PASS
- BASE_PHASE3_CHECKPOINT_VERIFIED=PASS
- PHASE1_CONTRACTS_REUSED=PASS
- PHASE2_DATABASE_REUSED=PASS
- PHASE3_CONTROL_REUSED=PASS
- PRIOR_PHASES_NOT_REIMPLEMENTED=PASS
- LOCKED_ARCHITECTURE_PRESERVED=PASS

## EVENT STORAGE MODEL

- `EVENT_STORE=event.domain_events` — canonical immutable durable event
  history, replay source. Additive Phase-4 columns: sequence (bigint),
  event_version, correlation_id, causation_id, actor_type, actor_id,
  timestamp. Unique invariant (workspace_id, project_id, sequence).
- `PROJECT_SEQUENCE=event.project_sequences` — one row per
  (workspace_id, project_id); atomic allocation via
  INSERT ... ON CONFLICT ... DO UPDATE ... RETURNING; starts at 1
  (0 = "before first event" sentinel).
- `OUTBOX=event.outbox` — durable dispatch bookkeeping (NOT the replay
  store): composite-tenant-FK reference to the canonical event, delivery
  state (dispatched_at, attempt_count, next_attempt_at, sanitized last_error)
  and lease state (lease_token, lease_expires_at).
- Envelope mapping (locked):
  - `event.domain_events.event_version` → `DomainEventSchema.version`
  - `event.domain_events.event_type` → `DomainEventSchema.type`
  - `EventEnvelope.type` = 'domain_event' transport discriminator
    (generation_event variant preserved intact)

## OUTBOX MODEL

- `OUTBOX_DELIVERY=AT_LEAST_ONCE` (duplicates possible; stable event id +
  sequence enable client dedup)
- `OUTBOX_RETRY_LIFETIME=UNBOUNDED` — an outage never orphans a valid event;
  the row stays claimable while undispatched
- `OUTBOX_BACKOFF_CAP=60s` (backoff is capped, not delivery lifetime;
  attempt_count keeps increasing)
- Claim: per-workspace tenant transaction (RLS-scoped), atomic lease UPDATE,
  claim COMMIT before any Redis I/O. No DB transaction held during publish.
- Mark-dispatched requires the matching lease token. Multi-worker safe:
  active lease blocks double claim; expired leases reclaimable.
- last_error sanitized (redis:// credentials redacted), truncated 500 chars.

## DISPATCH MODEL

`OutboxDispatcher` (apps/control/src/events/dispatcher.ts): enumerates
workspaces from core.workspaces (tenant-boundary metadata, no RLS there),
then processes each workspace under SET LOCAL ROLE application_role +
transaction-local app.workspace_id. No BYPASSRLS role. `runOnce()` drivable
for tests; `start()/stop()` interval loop for production.

## REDIS MODEL

`REDIS_MODEL=TRANSIENT_ONLY` — pub/sub fanout only; never canonical state.
Internal channel naming `botconnector:events:{workspaceId}:{projectId}`;
clients never supply channel names; channel naming is NOT a security
boundary (authorization enforced per connection before delivery).

System Redis note (truthful):
- `SYSTEM_REDIS_PACKAGE_INSTALLED=YES` (redis-server 7.0.15, installed via
  apt during Phase-4 work; package retained as the local test tool)
- `SYSTEM_REDIS_SERVICE_ACTIVE=NO` (stopped)
- `SYSTEM_REDIS_SERVICE_ENABLED=NO` (disabled)
- `SYSTEM_REDIS_6379_LISTENING=NO` (no host-level 6379 listener)
- A pre-existing Docker container `botconnector-core-redis` (redis:7-alpine,
  up since 2026-08-29, containerd-managed) predates Phase 4, belongs to a
  different stack on this VPS, and was NOT touched.

TEST_REDIS=isolated disposable process on port 6380 (temp dir, no
persistence), spawned/killed by the test harness; outage tests stop/restart it.

## WEBSOCKET / REALTIME

- `WS_ENDPOINT=/ws/v1` (@fastify/websocket, modular monolith inside
  apps/control; separate dispatcher module, no microservice)
- Trusted PrincipalResolver required; fail-closed (4401) without one;
  production path never trusts arbitrary x-workspace-id.
- `SUBSCRIPTION_MODEL`: subscribe/unsubscribe/replay/ping ops (zod-validated
  transport framing; no EventEnvelope duplication). Project authorization
  (RLS-scoped DB check) BEFORE any attach/replay; non-disclosure for foreign
  projects.
- `SEQUENCE_MODEL`: per-project bigint, decimal string at the JSON boundary
  (no Number conversion).
- `REPLAY_MODEL=durable PostgreSQL event.domain_events` — never Redis.
- `REPLAY_LIVE_HANDOFF=buffer-before-high-water + replay + dedup + ordered
  flush` — attach buffer → capture durable high-water → replay
  (after_sequence, high-water] → deduplicate buffered events by id/sequence →
  flush remaining in sequence order → replay_complete → live.
- `HANDOFF_BUFFER=explicitly bounded` (count-based per subscription)
- `HANDOFF_OVERFLOW=snapshot_required / recoverable, no silent drop`
  (overflow aborts the handoff deterministically)
- `SNAPSHOT_FALLBACK=PASS` (future cursor; replay range > 1000 events)
- `BACKPRESSURE=PASS` (bounded by ws bufferedAmount; slow client closed 1013;
  recovery via replay)

## EVENT EMISSION (PHASE-3 INTEGRATION)

Same-transaction emission for implemented mutations only:
project.created/updated, artifact.created/updated,
artifact_version.created, phase.created, backlog.created.
- `IDEMPOTENCY_EVENT_DEDUP=PASS` (cached replay creates no second event/outbox row)
- `REVISION_CONFLICT_NO_EVENT=PASS` (stale If-Match emits nothing)
- correlation_id seeded from request_id (ids never conflated); no public
  POST /events; no internal HTTP needed (direct module interface).

## DATABASE SECURITY

- APPLICATION_ROLE_EFFECTIVE=PASS
- TRANSACTION_LOCAL_WORKSPACE_CONTEXT=PASS
- RLS_REMAINS_ENABLED=PASS (new tables FORCE RLS; no BYPASSRLS dispatcher role)
- TENANT_CONTEXT_NO_POOL_LEAK=PASS

## ACCEPTANCE TESTS

- `PHASE4_TESTS=48/48 PASS` (tests/phase4.test.ts — includes targeted
  semantic-check tests: handoff-buffer bounds/overflow/recovery, outbox
  retry beyond cap with capped backoff)
- `PHASE1_REGRESSION=42/42 PASS`
- `PHASE2_REGRESSION=47/47 PASS` (31 acceptance + 16 event-stream, phase4_test)
- `PHASE3_REGRESSION=47/47 PASS` (acceptance.test.ts against phase4_test —
  current canonical schema; phase2_test/phase3_test untouched)
- TYPECHECK=CONTRACTS OK / CONTROL OK
- DIFF_CHECK=CLEAN
- Test DB: botconnector_phase4_test (all 21 canonical migrations)

## BOUNDARIES

- TASK_ENGINE_IMPLEMENTED=NO
- GENERATION_ENGINE_IMPLEMENTED=NO
- SANDBOX_IMPLEMENTED=NO
- PREVIEW_IMPLEMENTED=NO
- CANVAS_IMPLEMENTED=NO
- AI_PROVIDER_IMPLEMENTED=NO
- DEPLOYMENT_ENGINE_IMPLEMENTED=NO
- PRODUCTION_DB_MUTATED=NO
- PERSISTENT_PRODUCTION_REDIS_STARTED=NO
- SERVICE_RESTARTED=NO (apt system redis service stopped+disabled per owner
  authorization; pre-existing Docker stack untouched)

## KNOWN_GAPS

- Project DELETE deferred (`DEFERRED_SCHEMA_CONTRACT_GAP`, unchanged).
- PostgreSQL 16.15 running vs 18+ target (unchanged).
- Phase-0 CSS backlog unchanged (/static/privacy.css, /static/security.css).
- snapshot materialization itself belongs to a later phase; Phase 4 provides
  only the protocol fallback signal.
- A pre-existing Docker container `botconnector-core-redis` (redis:7-alpine)
  from another stack runs on this host since 2026-08-29 — untouched, reported
  for owner awareness.

## DEFERRED_TO_LATER_PHASES

- Task scheduler / task engine (Phase 5)
- Sandbox (Phase 6), Preview (Phase 7), Canvas (Phase 8)
- Live generation + Agent Cursor (Phase 9), AI providers (Phase 10)
- Validation + repair (Phase 11), Task DAG (Phase 12), Checkpoint/Apply (Phase 13)
- Deployment (Phase 14), Hardening (Phase 15)

## FILES_OF_INTEREST

- `apps/control/src/events/service.ts` — durable event service, sequence
  allocator, replay, high-water
- `apps/control/src/events/dispatcher.ts` — lease/claim/retry dispatcher
- `apps/control/src/realtime/redis.ts` — transient fanout client
- `apps/control/src/realtime/protocol.ts` — WS framing schemas
- `apps/control/src/realtime/hub.ts` — authorization, live routing, replay
  handoff, snapshot fallback, backpressure
- `apps/control/src/realtime/gateway.ts` — /ws/v1 handler
- `apps/control/tests/phase4.test.ts` — 48-test acceptance suite
- `apps/control/tests/helpers/test-redis.ts` — isolated test Redis harness
- `packages/database/migrations/1725168020000_create_event_stream_outbox.cjs`
- `packages/contracts/src/transport/index.ts` — EventEnvelope (2 variants)

## DO_NOT_REPEAT

- Do not recreate contracts, migrations, control API, or the Phase-4
  corrections (4f05198, e518b13, 2a5adc1).
- Do not make Redis the canonical event source.
- Do not add a BYPASSRLS dispatcher role.
- Do not reintroduce unbounded handoff buffering or a retry lifetime cap.
- Do not trust x-workspace-id in production paths.
- Do not start Phase 5 without explicit authorization.

## NEXT_PHASE

`NEXT_PHASE=PHASE_5_TASK_GENERATION_KERNEL`

`PHASE5_STARTED=NO`

Phase 5 is not started or implicitly authorized by this handoff.