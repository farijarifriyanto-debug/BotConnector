# Phase 5: Task / Generation Kernel

## Status

PASS / COMMITTED

## Commits

```
BASE_COMMIT=154d8b94816a654094359abcb96c5a92e36925c0
  Phase 4 final checkpoint

PHASE5_IMPLEMENTATION_HEAD=6e87286b6dd26285ab5c736a819762ebbd7d388a
  Phase 5: establish task and generation kernel
```

## Scope

### New Files

| File | Purpose |
|---|---|
| `apps/control/src/task/state-machine.ts` | Task transition policy (canonical authority) |
| `apps/control/src/task/routes.ts` | Task CRUD + lifecycle HTTP routes |
| `apps/control/src/focus-lock/routes.ts` | FocusLock acquire/release HTTP routes |
| `apps/control/src/generation/state-machine.ts` | GenerationRun transition policy (canonical authority) |
| `apps/control/src/generation/routes.ts` | GenerationRun CRUD + lifecycle HTTP routes |
| `apps/control/src/generation/ack.ts` | Internal executor acknowledgement service |
| `apps/control/tests/phase5.test.ts` | 56 acceptance tests |

### Modified Files

| File | Change |
|---|---|
| `apps/control/src/errors/index.ts` | Added 4 error codes + `controlApiError` factory |
| `apps/control/src/index.ts` | Registered task, focus-lock, generation routes |

### Not Changed

- No contract changes (`packages/contracts`)
- No migration changes (`packages/database/migrations`)
- No Phase-6 files

---

## Task Kernel

### API

| Method | Route | Purpose |
|---|---|---|
| POST | `/api/v1/projects/:projectId/tasks` | Create task |
| GET | `/api/v1/projects/:projectId/tasks` | List project tasks |
| GET | `/api/v1/tasks/:taskId` | Read task |
| PATCH | `/api/v1/tasks/:taskId` | Update title (requires If-Match) |
| POST | `/api/v1/tasks/:taskId/approve` | Lifecycle: draft → approved |
| POST | `/api/v1/tasks/:taskId/queue` | Lifecycle: approved → queued |
| POST | `/api/v1/tasks/:taskId/cancel` | Lifecycle: any non-terminal → cancelled |

### State Machine

Canonical authority: `apps/control/src/task/state-machine.ts`

States (from Phase-1 contract):
`draft → approved → queued → active → validating → ready → applying → done`

Terminal: `done`, `cancelled`, `failed`

Cancellation allowed from any non-terminal state.

### Lifecycle Commands

Public commands map to fixed target states:

| Command | Target |
|---|---|
| approve | approved |
| queue | queued |
| cancel | cancelled |

### Status Injection Protection

PATCH `/api/v1/tasks/:taskId` only accepts `title`.

Attempts to inject lifecycle fields return:

```
HTTP 422
error.code = VALIDATION_ERROR
```

Rejected fields: `state`, `status`.

Generic PATCH cannot mutate lifecycle status.

### Revision Concurrency

- If-Match header required on PATCH
- Decimal string revision (bigint-safe)
- Stale revision → 409 REVISION_CONFLICT

### Idempotency

- Lifecycle commands accept `Idempotency-Key` header
- Same key + same request → cached 200
- Same key + different request → 409 IDEMPOTENCY_CONFLICT

### Tenant Isolation

- RLS scopes all queries to workspace
- Cross-tenant task access → 404
- Cross-project task reference → 404 (RLS blocks)

---

## Focus Lock

### API

| Method | Route | Purpose |
|---|---|---|
| POST | `/api/v1/projects/:projectId/focus-locks` | Acquire lock |
| GET | `/api/v1/projects/:projectId/focus-locks` | List project locks |
| GET | `/api/v1/focus-locks/:lockId` | Read lock |
| POST | `/api/v1/focus-locks/:lockId/release` | Release lock |

### Lock Types

- **Non-expiring**: `expires_at = NULL` (default)
- **Timed**: client supplies `expires_in_seconds`, stored as future `expires_at`

### Concurrency Authority

All acquisition paths serialize on:

```sql
SELECT id FROM core.projects WHERE id = $1 FOR UPDATE
```

inside the tenant transaction. This serializes all focus-lock acquisitions for the same project.

### Partial Unique Index

```sql
CREATE UNIQUE INDEX idx_focus_locks_active_unique
  ON work.focus_locks (project_id)
  WHERE expires_at IS NULL
```

This is an additional constraint for `expires_at IS NULL` locks. It is NOT the sole concurrency authority for timed locks.

### Conflict Behavior

- HTTP 409
- `error.code = FOCUS_LOCK_CONFLICT`
- No raw SQLSTATE/constraint details exposed
- DB unique_violation (23505) mapped to domain error

### True Concurrent Test

Two simultaneous acquisition attempts for same project:

```
SUCCESS_COUNT=1
CONFLICT_COUNT=1
ACTIVE_LOCK_COUNT=1
```

Loser receives HTTP 409 with FOCUS_LOCK_CONFLICT.

---

## Generation Run

### API

| Method | Route | Purpose |
|---|---|---|
| POST | `/api/v1/projects/:projectId/generation-runs` | Create (starts at planning) |
| GET | `/api/v1/projects/:projectId/generation-runs` | List project runs |
| GET | `/api/v1/generation-runs/:runId` | Read run |
| POST | `/api/v1/generation-runs/:runId/start` | Lifecycle: planning → running |
| POST | `/api/v1/generation-runs/:runId/pause` | Lifecycle: running → pausing |
| POST | `/api/v1/generation-runs/:runId/resume` | Lifecycle: paused → running |
| POST | `/api/v1/generation-runs/:runId/stop` | Lifecycle: allowed → stopping |

### State Machine

Canonical authority: `apps/control/src/generation/state-machine.ts`

States (from Phase-1 contract):
`planning → running → pausing → paused → running (resume)`
`running/pausing/paused → stopping → stopped`

Terminal: `completed`, `failed`, `stopped`

### Public vs Executor Transitions

**Public commands** (user/control-plane):
- `start` (planning → running)
- `pause` (running → pausing) — NOT directly to paused
- `resume` (paused → running)
- `stop` (allowed → stopping) — NOT directly to stopped

**Executor-only transitions** (internal):
- `pausing → paused` (safe-point acknowledgement)
- `stopping → stopped` (safe-point acknowledgement)

### Public Ack Route

**REMOVED.** There is NO:

```
POST /api/v1/generation-runs/:runId/ack
```

Returns 404 for any caller.

### Internal Acknowledgement Service

Canonical authority: `apps/control/src/generation/ack.ts`

```typescript
ackGenerationRun(tx, principal, requestId, runId, expectedFrom)
```

- Validates `expectedFrom` matches current state
- Validates `isExecutorOnlyTransition(from, to)`
- Increments revision
- Mutates state transactionally
- Emits exactly one domain event + outbox row
- Rejects stale/invalid acknowledgement without event

---

## Event Integration

### Transactional Emission

Both Task and GenerationRun lifecycle mutations emit events in the SAME tenant transaction as the domain mutation:

```
BEGIN tenant transaction
  → revision / transition validation
  → state mutation
  → emitDomainEventForMutation(tx, ...)
    → event.domain_events INSERT
    → event.outbox INSERT
COMMIT
```

On rollback: no partial state, no orphan events.

### Event Types

| Aggregate | Event |
|---|---|
| task | task.created, task.updated, task.approved, task.queued, task.cancelled |
| generation_run | generation_run.created, generation_run.started, generation_run.pause_requested, generation_run.resumed, generation_run.stop_requested, generation_run.paused, generation_run.stopped |

### Rejected/Stale Transitions

- No state mutation
- No lifecycle event
- No outbox row

### Idempotent Replay

- No duplicate transition
- No duplicate event
- No duplicate outbox row

### Project Sequence

- Strictly increasing per project
- Reuses Phase-4 project_sequences upsert mechanism

---

## Security

| Check | Status |
|---|---|
| APPLICATION_ROLE_EFFECTIVE | PASS |
| TRANSACTION_LOCAL_WORKSPACE_CONTEXT | PASS |
| RLS_REMAINS_ENABLED | PASS |
| TENANT_CONTEXT_NO_POOL_LEAK | PASS |
| PRODUCTION_HEADER_TRUST | NO |

No migration_owner. No BYPASSRLS. No arbitrary x-workspace-id production trust.

---

## Boundaries

### Not Implemented (Deferred)

| Feature | Status |
|---|---|
| TASK_DAG | NO |
| MULTI_AGENT | NO |
| MODEL_FALLBACK | NO |
| GIT_WORKSPACE | NO (Phase 6) |
| SANDBOX | NO (Phase 6) |
| PREVIEW | NO |
| CANVAS | NO |
| LIVE_GENERATION | NO |
| AI_PROVIDER | NO |
| VALIDATION_REPAIR | NO |
| CHANGESET_APPLY | NO |
| DEPLOYMENT | NO |

### Host/Production

| Check | Status |
|---|---|
| PRODUCTION_DB_MUTATED | NO |
| PRODUCTION_REDIS_MUTATED | NO |
| SERVICE_RESTARTED | NO |

---

## Test Results

| Suite | Result |
|---|---|
| PHASE5_TESTS | 56/56 PASS |
| PHASE1_REGRESSION | 42/42 PASS |
| PHASE2_REGRESSION | 31/31 PASS |
| PHASE3_REGRESSION | 47/47 PASS |
| PHASE4_REGRESSION | 48/48 PASS |
| TYPECHECK | PASS |
| DIFF_CHECK | PASS |

**TEST_DATABASE**: `botconnector_phase5_test`
**CANONICAL_MIGRATIONS_APPLIED**: 21

---

## Known Existing Gaps

| Gap | Status |
|---|---|
| PROJECT_DELETE | DEFERRED_SCHEMA_CONTRACT_GAP |
| PostgreSQL target | 18+ (current runtime may remain 16.15) |
| Phase-0 CSS backlog | /static/privacy.css, /static/security.css |
| Docker Redis | Pre-existing, belongs to another stack, untouched |

---

## Next Phase

**NEXT_PHASE**: PHASE_6_GIT_WORKSPACE_SANDBOX

**PHASE6_STARTED**: NO
