# Phase 3 Handoff

## PHASE

Phase 3: Project / Artifact Control API

## STATUS

PASS / COMMITTED

## COMMIT HISTORY (TRUTHFUL SEQUENCE)

- `PHASE3_ORIGINAL_BASE_HEAD=7352a5663747493a4521b9f9341e62d4b5f935f4`
  Phase 2 FINAL checkpoint — the commit Phase 3 work originally started from.
- `PRE_PHASE3_CONTRACT_CORRECTION_HEAD=e8ebe7b9a62e7ed7cf5987a92174c553e2a0b699`
  Phase 1 correction: make revision contracts bigint-safe.
- `PHASE3_BASE_HEAD=e8ebe7b9a62e7ed7cf5987a92174c553e2a0b699`
  The commit the Phase 3 implementation was validated against.
- `PHASE3_IMPLEMENTATION_HEAD=098499f1fb40174cffc36523ae16ad4c6a70ba68`
  Phase 3: establish project and artifact control API.
- Final Phase-3 repository checkpoint = the commit that contains this handoff
  file (Phase 3: finalize project and artifact control API handoff).
  This handoff intentionally does not reference its own commit SHA.

## AI_CONTINUITY_SOURCE

opencode (mimo-v2.5-free)

## CROSS_AI_CONTINUITY_RESULT

PASS

## WHAT WAS IMPLEMENTED

- Created `apps/control/` Fastify 5.12 HTTP API application.
- Implemented database pool singleton with `DATABASE_URL` configuration.
- Implemented `withTenantTransaction` — transaction-local `app.workspace_id` via `set_config(local=true)`, `SET LOCAL ROLE application_role` for RLS enforcement.
- Implemented `RequestContext` — deterministic `request_id`, `PrincipalContext` via dependency-injected `PrincipalResolver`.
- Implemented `ControlApiError` class with 8 stable error codes.
- Implemented `sendSuccess`, `sendCreated`, `sendNoContent`, `sendError` response helpers with standard envelope.
- Implemented fingerprint-based idempotency: `fingerprintRequest` (SHA-256 of method+path+body), `getIdempotencyResult` (same request → return stored result, different request → 409).
- Implemented `parseIfMatch`, `assertRevisionMatch` for If-Match concurrency.
- Implemented Project CRUD with bigint-safe revision handling (no ::int cast).
- Implemented Artifact CRUD with bigint-safe revision handling.
- Implemented ArtifactVersion with sequential versioning.
- Implemented Phase metadata with ordinal auto-increment.
- Implemented Backlog items.
- Implemented runtime OpenAPI: GET `/api/v1/openapi.json`.
- Implemented OpenAPI file export: `npm run openapi`.
- Implemented health endpoint: GET `/api/v1/health`.
- Implemented structured logging with request timing hooks.
- Implemented graceful SIGTERM/SIGINT shutdown.
- Implemented dependency-injected `PrincipalResolver` — test-only reads `x-workspace-id` header.
- Created test database `botconnector_phase3_test`, migrated from all 19 Phase 2 migrations.
- Wrote 29 acceptance test suites (47 individual tests).
- All 47/47 control tests PASS.
- Phase 1 contracts regression: 40/40 PASS.
- Phase 2 database regression: 31/31 PASS.
- Typecheck: clean (both contracts and control).

## PHASE 1 BIGINT-SAFE CONTRACT CORRECTION

Between Phase 2 FINAL and the Phase 3 implementation commit, the canonical
Phase-1 revision contracts were corrected in a dedicated commit
(`e8ebe7b9a62e7ed7cf5987a92174c553e2a0b699`):

- `RevisionSchema` changed from `z.number().int().nonnegative()` to
  `z.string().regex(/^[0-9]+$/)` — canonical non-negative decimal string.
- All revision-bearing contracts (Project, Artifact, UIIR, SelectionContext,
  DesignDecision, ProjectMemoryRevision, AgentRun, ContextSnapshot,
  ModelRoute, Changeset, ValidationResult, RepairRun, Deployment, Task,
  Phase, FocusLock, AcceptanceContract, GenerationRun, RenderTransaction)
  now use the string revision representation.
- Deterministic JSON Schema / OpenAPI contract artifacts regenerated
  (`packages/contracts/schema/contracts.schema.json`,
  `packages/contracts/schema/openapi-components.json`).
- Phase-1 contract tests updated: 40/40 PASS including values above
  `Number.MAX_SAFE_INTEGER`.

## REVISION REPRESENTATION

- `REVISION_CONTRACT_TYPE=DECIMAL_STRING` (canonical non-negative decimal string, bigint-safe in JS)
- `REVISION_DB_TYPE=BIGINT` (PostgreSQL column type, unchanged)
- `REVISION_PRECISION_LOSS_POSSIBLE=NO` (no Number() conversion; BigInt() used for comparison/arithmetic; `::bigint` cast in SQL comparisons)
- Stale `If-Match` → HTTP `409` with `error.code = REVISION_CONFLICT`.
- Missing `If-Match` → explicitly implemented validation/precondition policy
  (409 REVISION_CONFLICT via `parseIfMatch`).

## IDEMPOTENCY SEMANTICS

- Same idempotency key + same request fingerprint → replay stored result (HTTP 200).
- Same idempotency key + different request fingerprint → HTTP 409 IDEMPOTENCY_CONFLICT.
- Fingerprint = SHA-256 of (method, path, body), stored in
  `ops.idempotency_keys.operation`.

## PRINCIPAL RESOLUTION

- Test-only PrincipalResolver reads `x-workspace-id` header and must be
  explicitly injected into `buildApp()`.
- Production entry `main()` fails closed (`process.exit(1)`) without a
  trusted PrincipalResolver.
- `PRODUCTION_X_WORKSPACE_ID_TRUST=NO`.

## ACCEPTANCE GATE

### CONTINUITY

- CROSS_AI_HANDOFF_READ=PASS
- BASE_PHASE2_COMMIT_VERIFIED=PASS (7352a56...)
- PHASE1_CONTRACTS_REUSED=PASS (with dedicated bigint-safe correction commit)
- PHASE2_SCHEMA_REUSED=PASS

### HTTP STACK

- FASTIFY_INSTALLED=PASS (5.12.1)
- ROUTES_REGISTERED=PASS (8 route groups)
- HEALTH_ENDPOINT=PASS
- OPENAPI_ENDPOINT=PASS

### DATABASE

- DATABASE_URL_CONFIGURED=PASS
- TENANT_TRANSACTION=PASS
  - BEGIN → set_config('app.workspace_id', ws, true) → SET LOCAL ROLE application_role → QUERY → COMMIT
- APPLICATION_ROLE_EFFECTIVE=PASS
- TRANSACTION_LOCAL_WORKSPACE_CONTEXT=PASS
- TENANT_CONTEXT_POOL_LEAK=PASS

### REVISION BIGINT

- REVISION_DB_TYPE=BIGINT (verified via information_schema)
- REVISION_CONTRACT_TYPE=DECIMAL_STRING (Phase-1 correction commit e8ebe7b)
- REVISION_NO_INT32_DOWNCAST=PASS (no ::int cast on revision/base_revision)
- REVISION_PRECISION_LOSS_POSSIBLE=NO
- REVISION_CONTRACT_PRECISION_GAP=NO

### IDEMPOTENCY

- IDEMPOTENT_SAME_KEY_SAME_REQUEST=PASS (returns stored result, HTTP 200)
- IDEMPOTENT_SAME_KEY_NO_DUPLICATE_RESOURCE=PASS (no second INSERT)
- IDEMPOTENT_SAME_KEY_DIFFERENT_REQUEST_409=PASS (IDEMPOTENCY_CONFLICT)
- IDEMPOTENCY_SCHEMA_GAP=NO (schema supports fingerprint in `operation` column)

### ERROR HANDLING

- ERROR_CODES_STABLE=PASS (8 codes)
- ERROR_ENVELOPE=PASS (code, message, request_id, details)
- VALIDATION_ERROR=PASS (422)
- NOT_FOUND=PASS (404)
- STALE_IF_MATCH_HTTP_STATUS=409
- STALE_IF_MATCH_ERROR_CODE=REVISION_CONFLICT
- IDEMPOTENCY_CONFLICT=PASS (409)

### CONCURRENCY

- IF_MATCH_HEADER=PASS
- REVISION_MISMATCH_409=PASS (never 412)

### TENANCY

- WORKSPACE_ISOLATION=PASS
- CROSS_TENANT_SELECT_BLOCKED=PASS
- APPLICATION_ROLE_ENFORCED=PASS
- TRANSACTION_LOCAL_CONTEXT=PASS

### PRINCIPAL RESOLUTION

- TEST_PRINCIPAL_RESOLVER=TEST_ONLY (dependency-injected PrincipalResolver)
- PRODUCTION_HEADER_TRUST=NO (default is fail-closed, not test resolver)
- FAIL_CLOSED_WITHOUT_TRUSTED_PRINCIPAL=PASS (buildApp() throws without resolver)
- DEFAULT_APP_HEADER_TRUST=NO (buildApp() requires principalResolver)
- TEST_HEADER_RESOLVER_REQUIRES_EXPLICIT_INJECTION=PASS (tests inject testPrincipalResolver)
- DEFAULT_APP_WITHOUT_TRUSTED_RESOLVER_FAILS_CLOSED=PASS (buildApp({}) throws)

### OPENAPI

- SPEC_GENERATION=PASS (8 paths, 56 schemas)
- PHASE1_REGRESSION=PASS (40/40)
- PHASE2_REGRESSION=PASS (31/31)

### TESTS

- ACCEPTANCE_TESTS=PASS (47/47, 29 suites)
- TYPECHECK=PASS
- GIT_DIFF_CHECK=PASS

### BOUNDARY

- PRODUCTION_DB_MUTATED=NO
- SERVICE_RESTARTED=NO
- PHASE4_IMPLEMENTED=NO

## FILES CREATED

### apps/control/

- `package.json` — workspace config, dependencies
- `tsconfig.json`, `tsconfig.build.json`, `vitest.config.ts`
- `src/index.ts` — Fastify app entry, buildApp() with PrincipalResolver injection
- `src/db/pool.ts` — pg Pool singleton
- `src/db/tenant.ts` — beginTenantTransaction, withTenantTransaction
- `src/db/idempotency.ts` — fingerprintRequest, getIdempotencyResult, claimIdempotencyKey
- `src/db/concurrency.ts` — If-Match helpers (409 REVISION_CONFLICT)
- `src/errors/index.ts` — ControlApiError, ErrorCode
- `src/errors/response.ts` — sendSuccess, sendCreated, sendNoContent, sendError
- `src/request-context/index.ts` — PrincipalContext, RequestContext
- `src/project/routes.ts` — Project CRUD routes
- `src/artifact/routes.ts` — Artifact CRUD routes
- `src/artifact-version/routes.ts` — ArtifactVersion routes
- `src/phase/routes.ts` — Phase metadata routes
- `src/backlog/routes.ts` — Backlog routes
- `src/openapi/index.ts` — runtime OpenAPI route
- `src/openapi/export.ts` — OpenAPI file export
- `tests/acceptance.test.ts` — 29 test suites (47 tests)

### apps/schema/

- `openapi.json` — generated OpenAPI 3.1.0 spec (8 paths, 56 schemas)

### Root

- `package.json` — updated with `apps/control` workspace

## IDEMPOTENCY SCHEMA ANALYSIS

Locked schema (`ops.idempotency_keys`):
- `id`: text PRIMARY KEY (idempotency key)
- `workspace_id`: text NOT NULL (FK to core.workspaces)
- `operation`: text NOT NULL (stores SHA-256 fingerprint of request)
- `result`: jsonb (stores serialized response)
- `created_at`: timestamptz NOT NULL
- `expires_at`: timestamptz NOT NULL

The schema supports required semantics:
- Same key + same request: `operation` matches fingerprint → return stored `result`
- Same key + different request: `operation` mismatches → HTTP 409

## KNOWN_GAPS

- `PROJECT_DELETE_POLICY=DEFERRED_SCHEMA_CONTRACT_GAP` — Project DELETE
  omitted; schema has no soft-delete column.
- No Redis, WebSocket, Task engine, Generation engine, Sandbox, Canvas, AI provider, Deployment engine.
- PostgreSQL 16.15 running vs 18+ target (UUIDv7 native function not used).

## DEFERRED_TO_LATER_PHASES

- Redis (Phase 4)
- WebSocket server (Phase 4)
- Event dispatcher (Phase 4)
- Task scheduler (Phase 5)
- Sandbox (Phase 6)
- Preview (Phase 7)
- Canvas (Phase 8)
- AI provider integration (Phase 10)
- Deployment engine (Phase 14)

## DO_NOT_REPEAT

- Do not recreate the contracts kernel (Phase 1).
- Do not recreate the database migrations (Phase 2).
- Do not re-apply the Phase-1 bigint-safe revision correction (already committed as e8ebe7b).
- Do not redesign the locked architecture.
- Do not start Phase 4 without explicit authorization.
- Do not modify production databases.
- Do not restart services.

## NEXT_PHASE

`NEXT_PHASE=PHASE_4_EVENT_REALTIME_BACKBONE`

`PHASE4_STARTED=NO`

Phase 4 is not started or implicitly authorized by this handoff.