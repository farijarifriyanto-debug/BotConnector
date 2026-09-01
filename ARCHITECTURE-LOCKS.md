# Architecture Locks

Status: `LOCKED`

These principles are semantic constraints, not implementation suggestions.
They must not be changed as an incidental part of coding. A future change
requires explicit owner approval, an authoritative decision record, and updates
to every affected contract and handoff.

1. Project is the root aggregate.
2. Git is canonical for source code after commit.
3. PostgreSQL stores durable relational control state only. Source code, large
   binaries, secret values, `node_modules`, and ephemeral Sandbox state do not
   belong in PostgreSQL.
4. Redis stores transient coordination, live events, and cache only. Redis is
   not durable project state.
5. BlobStore stores binary and large immutable objects.
6. Secrets flow only through SecretStore or SecretBroker. Secret values must
   not enter prompts, source, event payloads, Project Memory, or the control
   database.
7. The Control Plane does not execute untrusted generated code.
8. Generated code executes only in an isolated Sandbox.
9. Agents do not write directly to the canonical main repository.
10. Source mutation uses Changeset, isolated task workspace, validation, and
    apply flow.
11. The main project does not accept results that fail validation or
    acceptance.
12. Task, AgentRun, Changeset, GenerationRun, and Chat Message are distinct
    concepts.
13. Only one phase is active at a time.
14. The next phase cannot start until the active phase acceptance gate is PASS.
15. New ideas outside the active phase go to the Backlog.
16. A replacement AI or fallback model continues the same task and phase from
    repository state, checkpoints, and handoff instead of restarting work.
17. Work already marked PASS is not repeated without regression evidence.
18. Canvas is not canonical source of truth after commit.
19. Live Agent Cursor and brush behavior is event-driven from real
    GenerationEvent data, not timer or random animation.
20. A failed candidate render cannot replace the Last Known Good render.
21. A coding agent may choose internal implementation details only when they do
    not change a locked semantic contract.

The architecture specification inventory and current availability are recorded
in `docs/architecture/README.md`.
