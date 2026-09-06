# Destructive Acceptance Safety Policy (post-incident)

## Root cause
On 2026-08-21 an opencode build agent (`ses_fdac10da0ffe...`,
model `deepseek-v4-flash`) executed inline `DELETE FROM local_business.*`
commands directly against the **production** `botconnector` database while
running local_business acceptance tests. Because the suites' `_cleanup()`
used **unscoped `DELETE FROM` / `TRUNCATE`** against shared tables with no
tenant filter, the entire `local_business` + `multichannel` test-relevant
data was wiped. Business 336 was among the casualties (later recovered via
selective restore).

## Permanent fix (this change)
1. **Shared production guard** — `persistence/guard.py`
   `assert_isolated_test_db()` fails CLOSED unless:
   - explicit test mode (`BC_ACCEPTANCE_TEST=1` / `BC_BOTCONNECTOR_ACCEPTANCE=1`)
   - database name is NOT `botconnector`
   - connection is NOT the production host
   - database name carries isolated-test marker `botconnector_test_`
   - `require_test_tenant()` refuses the production tenant `LOCAL-PILOT`
   Deterministic error: `REFUSING_DESTRUCTIVE_TEST_ON_PRODUCTION`.

2. **Isolated acceptance DB** — dedicated container
   `botconnector-acceptance-postgres` (postgres:16-alpine, own volume, own
   network `botconnector-acceptance-net`, no published port, NOT reachable by
   production services). Tagged disposable DBs `botconnector_test_<tag>`.

3. **Repaired suites** — `local_business/acceptance.py`,
   `local_business/acceptance_expansion.py`, `local_business/scenario.py`
   now call `assert_isolated_test_db()` + `require_test_tenant()` + print
   `ACCEPTANCE_DATABASE/ACCEPTANCE_TEST_MODE/PRODUCTION_DATABASE/TENANT`
   before ANY migration/fixture/delete/truncate. All use disposable tenant
   `LOCAL-TEST-<tag>` (never `LOCAL-PILOT`).

4. **Safe-by-default runner** — `tests/run_acceptance.sh`
   is the intended entry point. It creates a fresh isolated DB, bootstraps
   schema-only, runs the destructive suites, and aborts if anything resolves
   to production.

## How to run destructive acceptance
```
bash /opt/botconnector-multichannel/tests/run_acceptance.sh
```
This is the ONLY supported way. Running the suites directly (no test flag,
default DB) will hard-fail with `REFUSING_DESTRUCTIVE_TEST_ON_PRODUCTION`.

## Hard rule
Never run destructive legacy suites against the production `botconnector`
database. If a developer explicitly points a destructive suite at production,
the shared guard still hard-fails.
