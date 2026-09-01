# Implementation Plan

## Current phase

```
CURRENT_PHASE=PHASE_1_CONTRACTS_KERNEL
CURRENT_PHASE_STATUS=PASS_LOCKED
NEXT_PHASE=PHASE_2_POSTGRESQL_CONTROL_PLANE
NEXT_PHASE_STATUS=NOT_STARTED
PHASE_1_STARTED=YES
PHASE_2_STARTED=NO
```

Phase 0 remains PASS/LOCKED. The project owner explicitly started Phase 1 to
implement the shared Contracts Kernel. Phase 2 is not active and must not start
until the Phase 1 acceptance gate passes and a separate explicit kickoff changes
this declaration.

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
