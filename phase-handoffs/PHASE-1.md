# Phase 1 Handoff

## PHASE

Phase 1: Contracts Kernel

## STATUS

PASS / LOCKED

## BASE COMMIT

`9f45d1f55630188e4158541e152d20176bd00d5f`

## FINAL COMMIT

`cba4caa` — Phase 1: establish shared contracts kernel

## WHAT WAS IMPLEMENTED

- Created `packages/contracts/` as a shared TypeScript contracts kernel.
- Implemented 38 canonical Zod schemas covering core, work, generation, design,
  AI, change, validation, deployment, and transport contract families.
- Inferred static TypeScript types from Zod schemas as the single source of
  truth.
- Implemented strict runtime validation with locked enums for all domain states.
- Enforced `base_revision <= revision` invariant across all revisioned schemas.
- Added `ChatMessage` as a distinct contract per Architecture Lock 12.
- Implemented declarative-only UI-IR with recursive key/value sanitization
  that rejects executable event handlers, secrets, and executable URI schemes.
- Implemented UI-IR graph validation: acyclic, all nodes reachable from root,
  unique node IDs, no dangling child references.
- Implemented `SelectionContext` primary-in-selection invariant.
- Implemented workspace-relative POSIX path constraint for Changeset operations.
- Implemented 13-family typed `GenerationEvent` with monotonic sequence
  validation and `SteeringEvent` payload schemas.
- Implemented `ErrorEnvelope` for HTTP and WebSocket transport contracts.
- Implemented deterministic JSON Schema Draft 2020-12 export with local `$ref`
  rebasing so all 23 references resolve correctly.
- Implemented deterministic OpenAPI 3.1 schema component export with all 23
  references resolvable.
- Implemented shared consumer fixture tests for frontend/backend import
  feasibility.
- Added `README.md` with versioning strategy, schema library rationale, usage
  examples, and commands.

## ACCEPTANCE TESTS

```bash
npm run test:contracts        # 40/40 tests pass
npm run typecheck:contracts   # typecheck clean
npm run schema:contracts      # build + deterministic export
python3 -c "..."              # 38 contracts, 23 refs, ChatMessage distinct
sha256sum ...                  # schema determinism verified
git diff --check              # no whitespace issues
```

All acceptance items PASS.

- BASELINE_HEAD_VERIFIED=PASS (9f45d1f)
- WORKTREE_COUNT_ONE=PASS (1 worktree)
- BASELINE_CLEAN=PASS (clean git status pre-commit)
- CONTRACT_PACKAGE_PRESENT=PASS
- PROJECT_CONTRACT=PASS
- ARTIFACT_CONTRACT=PASS
- TASK_CONTRACT=PASS
- GENERATION_CONTRACT=PASS
- STEERING_CONTRACT=PASS
- UIIR_CONTRACT=PASS
- SELECTION_CONTEXT_CONTRACT=PASS
- AGENT_CONTRACT=PASS
- CAPABILITY_CONTRACT=PASS
- CHANGESET_CONTRACT=PASS
- VALIDATION_CONTRACT=PASS
- CHECKPOINT_CONTRACT=PASS
- DEPLOYMENT_CONTRACT=PASS
- EVENT_ENVELOPE=PASS
- ERROR_ENVELOPE=PASS
- CHAT_MESSAGE_CONTRACT=PASS (Architecture Lock 12)
- RUNTIME_VALIDATION=PASS
- INVALID_PAYLOAD_REJECTION=PASS
- JSON_SCHEMA_EXPORT=PASS
- OPENAPI_COMPONENT_EXPORT=PASS
- WS_PAYLOAD_VALIDATION=PASS
- VERSION_1_BASELINE=PASS
- NO_DUPLICATE_CONTRACT_DEFINITIONS=PASS
- NO_PHASE_2_IMPLEMENTATION=PASS
- TESTS=PASS (40/40)
- TYPECHECK=PASS
- DIFF_CHECK=PASS

## KNOWN GAPS

- JSON Schema propertyNames regex for UI-IR keys uses `z.refine` rather than
  native JSON Schema pattern due to Zod 4's limited `propertyNames` pattern
  generation. The constraint is enforced at runtime and in tests.
- Schema-level `pattern` for ChangeOperation paths is present in generated
  JSON Schema. UI-IR key constraints are runtime-only.

## LOCKED DECISIONS

- Zod 4 is the sole runtime schema library.
- `version: 1` is the baseline version for all contracts.
- `ChatMessage` is a distinct contract from Task, AgentRun, Changeset, and
  GenerationRun (Architecture Lock 12).
- UI-IR must contain declarative data only; no executable JavaScript, shell
  commands, or secrets.
- Changeset paths must be workspace-relative POSIX.

## DEFERRED TO LATER PHASES

- PostgreSQL schema, Redis, WebSocket gateway, task scheduler, sandbox,
  preview runtime, Canvas, AI provider SDK, deployment engine.
- HTTP API endpoints (Phase 3+).
- WebSocket server (Phase 4+).

## FILES OF INTEREST

- `packages/contracts/src/` — all contract source files
- `packages/contracts/tests/` — all contract tests
- `packages/contracts/schema/` — generated JSON Schema and OpenAPI exports
- `packages/contracts/README.md` — package documentation
- `phase-handoffs/PHASE-1.md` — this handoff
- `IMPLEMENTATION-PLAN.md` — phase status

## CURRENT RUNTIME STATE

No service, process, deployment, database, migration, or runtime configuration
was started, stopped, restarted, or changed.

## NEXT PHASE

`NEXT_PHASE=PHASE_2_POSTGRESQL_CONTROL_PLANE`

`PHASE2_STARTED=NO`

Phase 2 is not started or implicitly authorized by this handoff.

## DO NOT REPEAT

Do not recreate the contracts kernel, redefine locked semantic contracts,
rebuild the schema export pipeline, or begin Phase 2 without explicit kickoff.
