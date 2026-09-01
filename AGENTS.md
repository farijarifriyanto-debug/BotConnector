# AI Working Rules

## Authority and scope

These rules apply to the entire repository. Repository contents and Git history
are the operational source of truth. Prior chat, model memory, and external
summaries are not substitutes for repository evidence.

Read these documents before changing code:

1. `AGENTS.md`
2. `ARCHITECTURE-LOCKS.md`
3. `IMPLEMENTATION-PLAN.md`
4. `docs/architecture/README.md`
5. The latest applicable record in `phase-handoffs/`

The existing `.clinerules/00-botconnector-devcontainer-sandbox.md` remains a
tool-specific sandbox rule and complements this repository-wide contract.

## Required entry checks

Before mutation, record the repository root, branch, full HEAD, short status,
worktrees, and credential-safe remotes. Inspect relevant source, history, and
governing documents. Preserve unrelated or pre-existing worktree changes.

Do not create a replacement repository or a parallel implementation. Reconcile
with the repository structure that exists. Do not create duplicate governance
documents when an authoritative equivalent can be updated or referenced.

## Phase discipline

- Only the phase declared in `IMPLEMENTATION-PLAN.md` may be active.
- Do not start a later phase until every acceptance item for the active phase is
  PASS and the transition is explicitly authorized.
- Work outside the active phase goes to the Backlog; it is not implemented
  opportunistically.
- Work already recorded as PASS must not be repeated without evidence of a
  regression.
- Coding agents may choose internal implementation details only when those
  choices preserve all locked semantic contracts.
- During Phase 0, make governance and documentation changes only. Do not add
  website-builder features, contracts-kernel code, migrations, runtime code, or
  application scaffolding.

## Change and execution boundaries

- Git is canonical for source code after commit.
- An agent must not write directly to the canonical main repository in the
  product runtime design. Source mutation must use a Changeset, isolated task
  workspace, validation, and explicit apply flow.
- The Control Plane must not execute untrusted generated code. Generated code
  runs only in an isolated Sandbox.
- A result that fails validation or acceptance must not enter the main project.
- Never commit secret values. Secrets flow only through SecretStore or
  SecretBroker and must not enter prompts, source, events, Project Memory, or
  the control database.
- Review the complete diff and run the narrowest relevant validation before
  committing. Do not claim runtime success without runtime evidence.

## Continuity and fallback

A replacement AI or fallback model continues the same Task and active Phase
from Git, checkpoints, and the latest handoff. It must not restart the project,
recreate work already marked PASS, silently change scope, or begin the next
phase.

On takeover, the replacement must:

1. Re-run the required entry checks.
2. Read the governing documents and latest handoff.
3. Confirm the current phase, base/final commits, tests, known issues, and
   runtime state.
4. Resume only unfinished work in the same task and phase.
5. Produce or update a handoff using `phase-handoffs/README.md` before transfer.

Task, AgentRun, Changeset, GenerationRun, and Chat Message are distinct
concepts. Do not collapse them when implementing future phases.

## Render and interaction safeguards

Canvas is not canonical source after commit. Live Agent Cursor and brush state
must be driven by real GenerationEvent data, never timers or random animation.
A failed candidate render must never replace the Last Known Good render.
