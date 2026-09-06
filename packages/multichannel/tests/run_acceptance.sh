#!/usr/bin/env bash
# ============================================================
# Safe-by-default destructive acceptance runner.
#
# Runs the destructive local_business suites (acceptance.py,
# acceptance_expansion.py, scenario.py) ONLY inside an isolated,
# ephemeral, disposable acceptance Postgres database.
#
# This runner is the ONLY intended way to execute these suites.
# It FAILS CLOSED: it never targets the production database.
#
# Safety guarantees:
#   - Creates a fresh, tagged isolated test DB each run.
#   - Initializes schema from production schema-only (structure, no data).
#   - Sets BC_ACCEPTANCE_TEST=1 + isolated DB env so the shared
#     production guard (persistence.guard) permits execution.
#   - Production DB is never referenced or selected.
#   - If any suite resolves to database=botconnector or tenant=LOCAL-PILOT,
#     the runner aborts immediately.
# ============================================================
set -euo pipefail

# --- Config (override via env if needed) --------------------
ACCEPTANCE_CONTAINER="${ACCEPTANCE_CONTAINER:-botconnector-acceptance-postgres}"
ACCEPTANCE_SUPERUSER="${ACCEPTANCE_SUPERUSER:-acceptance_app}"
ACCEPTANCE_PASSWORD="${ACCEPTANCE_PASSWORD:-acceptance_test_only_nonsecret}"
REPO="/opt/botconnector-multichannel"
VENV="${REPO}/venv/bin/python"

# --- Resolve container IP -------------------------------------
ACCEPTANCE_IP=$(docker inspect -f '{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}' "$ACCEPTANCE_CONTAINER" 2>/dev/null || true)
if [ -z "$ACCEPTANCE_IP" ]; then
    echo "FATAL: isolated acceptance container '$ACCEPTANCE_CONTAINER' not running."
    exit 1
fi

TAG=$(date +%Y%m%d%H%M%S)
TEST_DB="botconnector_test_${TAG}"

echo "======================================================"
echo " ISOLATED ACCEPTANCE RUN"
echo " container : $ACCEPTANCE_CONTAINER ($ACCEPTANCE_IP)"
echo " test_db   : $TEST_DB"
echo " production: NOT TOUCHED (fail-closed guard)"
echo "======================================================"

# --- Create fresh tagged isolated DB -------------------------
docker exec "$ACCEPTANCE_CONTAINER" psql -U "$ACCEPTANCE_SUPERUSER" -d postgres \
    -c "CREATE DATABASE $TEST_DB OWNER botconnector_app" >/dev/null

# --- Bootstrap schema (production schema-only, no data) ------
docker exec botconnector-core-postgres pg_dump -U botconnector_app -d botconnector \
    --schema-only --schema=multichannel --schema=local_business > /tmp/biz_schemas_bootstrap.sql
docker cp /tmp/biz_schemas_bootstrap.sql "$ACCEPTANCE_CONTAINER":/tmp/biz_schemas_bootstrap.sql
docker exec "$ACCEPTANCE_CONTAINER" psql -U botconnector_app -d "$TEST_DB" \
    -v ON_ERROR_STOP=1 -f /tmp/biz_schemas_bootstrap.sql >/dev/null

# --- Environment for the suites (safe-by-default) ------------
export BC_ACCEPTANCE_TEST=1
export BC_BOTCONNECTOR_ACCEPTANCE_DB="$TEST_DB"
export BC_BOTCONNECTOR_DB_HOST="$ACCEPTANCE_IP"
export BC_BOTCONNECTOR_DB_PORT=5432
export BC_BOTCONNECTOR_DB_PASSWORD="$ACCEPTANCE_PASSWORD"
export PYTHONPATH=/opt

# --- Run each destructive suite ------------------------------
DESTRUCTIVE_SUITES=(
    "local_business/acceptance.py"
    "local_business/acceptance_expansion.py"
    "local_business/scenario.py"
)

overall=0
for suite in "${DESTRUCTIVE_SUITES[@]}"; do
    echo ""
    echo "===== RUNNING $suite (isolated) ====="
    out=$(cd "$REPO" && sudo -E "$VENV" "$suite" 2>&1)
    code=$?
    echo "$out" | tail -40
    if echo "$out" | grep -qE "PRODUCTION_DATABASE=YES|database=botconnector|TENANT=LOCAL-PILOT"; then
        echo "FATAL: $suite resolved to production. ABORT."
        overall=1
        break
    fi
    echo "----- $suite exit=$code -----"
    if [ "$code" -ne 0 ]; then
        overall=$code
    fi
done

echo ""
echo "======================================================"
echo " ISOLATED ACCEPTANCE RUN COMPLETE (overall=$overall)"
echo " test_db  : $TEST_DB (disposable; drop after review)"
echo " production: unchanged"
echo "======================================================"
exit $overall
