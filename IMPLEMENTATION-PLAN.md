# Implementation Plan

## Current phase

```
CURRENT_PHASE=PHASE_0_REPOSITORY_ARCHITECTURE_GUARD
CURRENT_PHASE_STATUS=PASS_LOCKED
NEXT_PHASE=PHASE_1_CONTRACTS_KERNEL
NEXT_PHASE_STATUS=NOT_STARTED
PHASE_1_STARTED=NO
```

Phase 0 remains the current phase declaration after its PASS/LOCKED gate. Phase 1 is
not active and must not start until an explicit Phase 1 kickoff changes this
declaration. This prevents a successful guard phase from becoming implicit
authorization for feature work.

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

## Phase 0 scope

Phase 0 establishes repository governance only. It does not implement website
builder features, Contracts Kernel code, schemas, APIs, event infrastructure,
sandboxes, previews, UI, agents, deployment, or application scaffolding.

Phase 0 acceptance is recorded in `phase-handoffs/PHASE-0.md`. The detailed
Implementation Master Plan v1 was declared approved but its full source document
was not present in this repository at the Phase 0 baseline. Its inventory status
is explicit in `docs/architecture/README.md`; missing details must not be
reconstructed from memory or prior chat.
