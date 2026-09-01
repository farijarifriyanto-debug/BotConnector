# Phase 0 Handoff

## PHASE

Phase 0: Repository & Architecture Guard

## STATUS

PASS / LOCKED

## BASE COMMIT

`bc3fd77c4628428172d4c900a3b68869b4522b5d`

## ORIGINAL GOVERNANCE COMMIT

`18fe9d7305dd71944ea7dfd69e7857f9247d4d82`

## FINAL NORMALIZATION COMMIT

The commit with subject `Phase 0: normalize canonical repository baseline`.
Resolve its full hash with:

```bash
git log -1 --format=%H --grep='^Phase 0: normalize canonical repository baseline$'
```

The exact hash is also recorded in
`/home/botadmin/PHASE0-FINAL-NORMALIZATION-REPORT.txt`. A commit cannot embed its
own hash in the tree from which that hash is calculated.

## FINAL COMMIT

The commit that first adds this file and the Phase 0 governance set. Resolve it
with:

```bash
git log --diff-filter=A --format=%H -- phase-handoffs/PHASE-0.md
```

The exact full hash is also part of the Phase 0 execution report because a Git
commit cannot embed its own hash in its committed tree.

## WHAT WAS IMPLEMENTED

- Added repository-wide AI working and continuity rules.
- Recorded the 21 locked architecture principles.
- Recorded the locked phase order and current phase.
- Added a non-invented status index for the nine approved architecture
  specifications.
- Added the reusable phase handoff contract and this Phase 0 evidence record.
- Classified and normalized the pre-existing dirty baseline after owner review.
- Preserved approved Python and Support Center source, tests, and canonical API
  templates in Git.
- Moved the preserved stylesheet to canonical `api/static/style.css`.
- Retired generated evidence, visual diagnostics, debug probes, static
  security metadata, and duplicate root templates only after verified external
  archival.
- Removed tracked Python bytecode and added scoped ignore rules for caches,
  local OpenCode config, Playwright evidence, and runtime SQLite files.

No feature, Contracts Kernel, schema, API, runtime, application structure, or
website-builder implementation was added.

## ACCEPTANCE TESTS

- Verified hostname and workspace path.
- Verified Git root, branch, full baseline HEAD, short status, all worktrees,
  recent history, and credential-safe remote configuration.
- Audited tracked and untracked repository structure, governing-document names,
  architecture paths, Markdown content, and relevant history across refs.
- Confirmed that no equivalent governance set existed before this change.
- Checked the Phase 0 diff for governance/documentation-only scope, required
  headings, cross-references, and known final Git state.
- Verified the external archive against the source copies before removal and
  verified all 167 `SHA256SUMS` entries.
- Parsed every approved Python source and test with `ast.parse` without writing
  bytecode.
- Verified every template referenced by `api/app.py`, canonical static location,
  exact staged paths, excluded artifacts, and Git diff checks.
- Did not run production browser suites, restart services, or mutate the runtime
  database or production.

PASS

## KNOWN ISSUES

- The baseline worktree contained unrelated changes and untracked files before
  Phase 0. They were classified, approved, preserved or archived, and normalized
  by the final Phase 0 normalization commit.
- Full copies of all nine locked architecture specifications were absent. The
  index records `LOCKED_REFERENCE_MISSING`; agents must not reconstruct them.
- The current branch has no configured upstream branch.
- `api/templates/privacy_request.html` still references missing
  `/static/privacy.css`.
- `api/templates/security_report.html` still references missing
  `/static/security.css`.

Baseline short-status entries preserved outside Phase 0:

```text
 D src/__pycache__/agent.cpython-312.pyc
 D src/__pycache__/document_compare.cpython-312.pyc
 D src/__pycache__/document_extract.cpython-312.pyc
 D src/__pycache__/multi_document_ai.cpython-312.pyc
 M src/multi_document_ai.py
?? .opencode/
?? .playwright-mcp/
?? .well-known/
?? api/
?? home-desktop.png
?? mobil-futuristik.svg
?? pdfword-desktop-modal.png
?? pdfword-mobile.png
?? r22-desktop-empty.png
?? r24-desktop-mt5-summary.png
?? r24-mobile-mt5-summary.png
?? r24-public-mt5-summary.png
?? scripts/support_ai_e2e_suite.py
?? scripts/visual_smoke_suite.py
?? src/__init__.py
?? src/agent.py
?? src/document_compare.py
?? src/document_extract.py
?? static/
?? templates/
?? test_full_implementation.py
?? test_relevance_debug.py
?? test_tanya_relevance.py
?? test_tanya_relevance_fix.py
```

## LOCKED DECISIONS

- `ARCHITECTURE-LOCKS.md`
- `IMPLEMENTATION-PLAN.md`
- `docs/architecture/README.md`

No new product architecture was designed in Phase 0.

## FILES OF INTEREST

- `AGENTS.md`
- `ARCHITECTURE-LOCKS.md`
- `IMPLEMENTATION-PLAN.md`
- `docs/architecture/README.md`
- `phase-handoffs/README.md`
- `phase-handoffs/PHASE-0.md`

## CURRENT RUNTIME STATE

No service, process, deployment, database, migration, or runtime configuration
was started, stopped, restarted, or changed. The runtime SQLite database stayed
in place and was excluded from Git. Production-assumption browser suites were
preserved but not run.

## NEXT PHASE

`NEXT_PHASE=PHASE_1_CONTRACTS_KERNEL`

`PHASE1_STARTED=NO`

Phase 1 is not started or implicitly authorized by this handoff.

## DO NOT REPEAT

Do not rebuild the governance layer, recreate these documents under alternate
names, rerun Phase 0 work without regression evidence, restore retired baseline
artifacts into the repository, or begin Phase 1 without explicit kickoff.

## FINAL NORMALIZATION STATE

```text
CANONICAL_WORKTREE_COUNT=1
FINAL_BRANCH=canary-routing-r1-20260821
FINAL_HEAD=FINAL_NORMALIZATION_COMMIT_RESOLVER_ABOVE
ARCHIVE=/home/botadmin/phase0-baseline-retired-20260901T041238Z
ARCHIVE_FILE_COUNT=166
ARCHIVE_SHA256_ENTRIES=167
ARCHIVE_SHA256SUMS_SHA256=9e3fb045b9b7d22b67e343ed62fd6f36bf60150cc87cb62362ba8b8cbe1854d9
ARCHIVE_CHECKSUM_STATUS=PASS
API_TEMPLATES_CANONICAL=PASS
STATIC_LOCATION_NORMALIZED=PASS
LOCAL_OPENCODE_NOT_TRACKED=PASS
SQLITE_RUNTIME_NOT_TRACKED=PASS
PHASE0_STATUS=PASS_LOCKED
NEXT_PHASE=PHASE_1_CONTRACTS_KERNEL
PHASE1_STARTED=NO
```

The local `.opencode/` directory remains physically present and excluded from
Git. `api/support/data/support.db` remains physically present, was not inspected
for row content during normalization, and is excluded from Git.
