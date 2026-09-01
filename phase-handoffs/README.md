# Phase Handoff Contract

Create one handoff record for each completed or transferred phase. A handoff is
an execution record and must reference governing documents rather than duplicate
or reinterpret them. Use factual repository and test evidence; do not report
intent as completed work.

Minimum format:

```text
PHASE
<phase number and name>

STATUS
<IN_PROGRESS | BLOCKED | PASS | FAIL>

BASE COMMIT
<full commit hash>

FINAL COMMIT
<full commit hash or an unambiguous method to resolve the containing commit>

WHAT WAS IMPLEMENTED
<scope completed in this phase>

ACCEPTANCE TESTS
<commands/checks and evidence>
PASS / FAIL

KNOWN ISSUES
<open issues and constraints>

LOCKED DECISIONS
<newly approved decisions or references to existing locks>

FILES OF INTEREST
<paths needed by the next model>

CURRENT RUNTIME STATE
<services, processes, deployments, migrations, and whether they were changed>

NEXT PHASE
<next phase by the locked order; not automatic authorization to start it>

DO NOT REPEAT
<completed work that must not be redone without regression evidence>
```

For fallback or model transfer within an unfinished phase, keep `STATUS` as
`IN_PROGRESS` or `BLOCKED`, identify the exact unfinished work, and retain the
same Task and Phase. Never use a handoff to silently advance scope.
