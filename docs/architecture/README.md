# Architecture Document Index

## Authority

Repository contents and Git history are the operational source of truth. The
project owner has declared the specifications below locked, but discovery at
the Phase 0 baseline found no complete repository copies or equivalent governing
documents. This index is therefore a status placeholder, not a reconstruction
of those specifications.

Do not infer missing details from filenames, prior chat, or model memory. Before
a future phase relies on a detail not stated in `ARCHITECTURE-LOCKS.md` or
`IMPLEMENTATION-PLAN.md`, the exact owner-approved specification must be
identified and added or linked through a governance-only change.

## Locked specification inventory

| Specification | Status in repository | Repository authority available now |
| --- | --- | --- |
| Internal Architecture Contract v1 | `LOCKED_REFERENCE_MISSING` | Lock summary only: `ARCHITECTURE-LOCKS.md` |
| Physical Architecture v1 | `LOCKED_REFERENCE_MISSING` | Lock summary only: `ARCHITECTURE-LOCKS.md` |
| Logical Data Model v1 | `LOCKED_REFERENCE_MISSING` | Lock summary only: `ARCHITECTURE-LOCKS.md` |
| PostgreSQL Schema v1 | `LOCKED_REFERENCE_MISSING` | Lock summary only: `ARCHITECTURE-LOCKS.md` |
| API Contract v1 | `LOCKED_REFERENCE_MISSING` | Lock summary only: `ARCHITECTURE-LOCKS.md` |
| Live Event / WebSocket Protocol v1 | `LOCKED_REFERENCE_MISSING` | Lock summary only: `ARCHITECTURE-LOCKS.md` |
| Execution Architecture v1 | `LOCKED_REFERENCE_MISSING` | Lock summary only: `ARCHITECTURE-LOCKS.md` |
| Deployment Topology + Technology Mapping v1 | `LOCKED_REFERENCE_MISSING` | Lock summary only: `ARCHITECTURE-LOCKS.md` |
| Implementation Master Plan v1 | `LOCKED_REFERENCE_MISSING` | Locked phase order only: `IMPLEMENTATION-PLAN.md` |

`LOCKED_REFERENCE_MISSING` means the specification is declared locked, but its
exact approved content was not found in the repository. It does not authorize
an agent to invent, expand, or revise the architecture.

## Governance map

| Concern | Authoritative repository document |
| --- | --- |
| AI working and fallback rules | `AGENTS.md` |
| Semantic architecture locks | `ARCHITECTURE-LOCKS.md` |
| Phase order and current phase | `IMPLEMENTATION-PLAN.md` |
| Handoff format | `phase-handoffs/README.md` |
| Phase 0 evidence | `phase-handoffs/PHASE-0.md` |
