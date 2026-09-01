# Implementation Plan

## Current phase

```
CURRENT_PHASE=PHASE_7_PREVIEW_RUNTIME_AND_BRIDGE
CURRENT_PHASE_STATUS=PASS_READY_TO_COMMIT
NEXT_PHASE=PHASE_8_CANVAS_SELECTION_DIRECT_EDITING
NEXT_PHASE_STATUS=NOT_STARTED
PHASE_0_STARTED=YES
PHASE_0_STATUS=PASS_LOCKED
PHASE_1_STARTED=YES
PHASE_1_STATUS=PASS_LOCKED
PHASE_2_STARTED=YES
PHASE_2_STATUS=PASS_LOCKED
PHASE_3_STARTED=YES
PHASE_3_STATUS=PASS_LOCKED
PHASE_4_STARTED=YES
PHASE_4_STATUS=PASS_LOCKED
PHASE_5_STARTED=YES
PHASE_5_STATUS=PASS_LOCKED
PHASE_6_STARTED=YES
PHASE_6_STATUS=PASS_LOCKED
PHASE_7_STARTED=YES
```

Phase 7 acceptance gate has passed (33 Phase 7 tests, 105/105 sandbox-manager
regression tests, 151/151 control tests, 47 database tests, 42 contract tests,
and typechecks clean). Code is ready to commit. Phase 8 must not start until
Phase 7 is committed and explicit authorization is given.

## Locked phase order

1. Phase 0: Repository & Architecture Guard
2. Phase 1: Contracts Kernel
3. Phase 2: PostgreSQL Control Plane
4. Phase 3: Project / Artifact Control API
5. Phase 4: Event & Realtime Backbone
6. Phase 5: Task / Generation Kernel
7. Phase 6: Git Workspace & Sandbox
8. Phase 7: Preview Runtime & Bridge
9. Phase 8: Canvas + Selection + Direct Editing
10. Phase 9: Live Generation + Agent Cursor / Brush
11. Phase 10: AI Agent Engine
12. Phase 11: Validation + Repair + Last Known Good
13. Phase 12: Task DAG + Multi-Agent + Model Fallback
14. Phase 13: Checkpoint + Apply + Merge
15. Phase 14: Deployment
16. Phase 15: Hardening + Production Acceptance

The order is locked. Only one phase may be active. A phase transition requires
a PASS acceptance gate and explicit authorization. Out-of-phase ideas are
Backlog items. Passing work is not repeated without regression evidence.

## Phase 1 scope

Phase 1 implements shared TypeScript contract types, runtime validation schemas,
JSON Schema and OpenAPI-compatible schema exports, event payload schemas, and
contract version metadata. It does not implement persistence, HTTP or WebSocket
servers, scheduling, sandboxes, previews, Canvas, AI providers, or deployment.

Phase 0 acceptance is recorded in `phase-handoffs/PHASE-0.md`. Phase 1 acceptance
will be recorded in `phase-handoffs/PHASE-1.md`. Missing architecture references
listed in `docs/architecture/README.md` must not be reconstructed from memory or
prior chat.
