# Rollback Plan

**PLANNING DOCUMENT ONLY. Nothing here has been executed.** Rollback must
be defined and understood BEFORE any real cutover happens, per your
instruction — this is that definition, not a drill.

General rule across every component: **the current live source/release is
never deleted until the new canonical deployment has run past its own
rollback window.** Old release directories, old images, and old flat
WorkingDirectory checkouts all stay in place through at least one full
business cycle after a successful cutover (exact window is an operator
decision at cutover time, not fixed here).

Schema per component:
```
ROLLBACK_SOURCE=
ROLLBACK_RELEASE=
ROLLBACK_COMMAND_CLASS=
DATA_COMPATIBILITY=
MAX_ROLLBACK_TIME=
ROLLBACK_HEALTH_CHECK=
```

---

### public-site
ROLLBACK_SOURCE=previous nginx location config (this is a first deploy, not a replace — "rollback" here just means removing the new location block)
ROLLBACK_RELEASE=N/A (no live equivalent exists to fall back to)
ROLLBACK_COMMAND_CLASS=nginx config revert + reload
DATA_COMPATIBILITY=N/A (stateless)
MAX_ROLLBACK_TIME=seconds (config reload only)
ROLLBACK_HEALTH_CHECK=confirm the route that was live before (the actual botconnector.id root) is unaffected

### store
ROLLBACK_SOURCE=`/opt/botconnector-store/releases/store-v6-20260812T071559Z` (the release currently live)
ROLLBACK_RELEASE=flip `current` symlink back to it
ROLLBACK_COMMAND_CLASS=SYSTEMD_RELEASE_SWITCH (symlink flip + `systemctl restart botconnector-store.service`)
DATA_COMPATIBILITY=YES — canonical source proven byte-identical to this release already; no schema change proposed
MAX_ROLLBACK_TIME=seconds (symlink flip + restart)
ROLLBACK_HEALTH_CHECK=`/store/` route serves; a product page renders

### business-suite
ROLLBACK_SOURCE=git revert of `apps/business-suite/app.py` + `run.sh` to the pre-cutover commit
ROLLBACK_RELEASE=N/A (flat WorkingDirectory, no dated releases) — the "release" here is the git commit currently checked out
ROLLBACK_COMMAND_CLASS=SHARED_RUNTIME_SWITCH (git revert + restart; if the shared multichannel venv changed, revert that too — see multichannel entry)
DATA_COMPATIBILITY=YES (no schema change proposed)
MAX_ROLLBACK_TIME=one restart, seconds
ROLLBACK_HEALTH_CHECK=`/health` → `database:connected`; a real read through `/bisnis/api/state` succeeds

### integrasi
ROLLBACK_SOURCE=git revert of `apps/integrasi/app.py` + `run.sh`
ROLLBACK_RELEASE=N/A (flat WorkingDirectory)
ROLLBACK_COMMAND_CLASS=SHARED_RUNTIME_SWITCH
DATA_COMPATIBILITY=YES (no state to be incompatible with)
MAX_ROLLBACK_TIME=seconds
ROLLBACK_HEALTH_CHECK=`/health` → `{"ok":true,...}`

### packages/multichannel (shared venv)
ROLLBACK_SOURCE=previous `requirements.lock.txt` + previous package source (git revert)
ROLLBACK_RELEASE=the venv itself — keep the pre-cutover venv directory until the rollback window passes, don't overwrite in place; build the new one alongside, switch, and only delete the old one after the window
ROLLBACK_COMMAND_CLASS=SHARED_RUNTIME_SWITCH — MUST restart business-suite AND integrasi together if this venv is what's reverted
DATA_COMPATIBILITY=YES
MAX_ROLLBACK_TIME=however long a `pip install` takes if the venv itself must be rebuilt (minutes) — this is the one component in this plan whose rollback isn't sub-minute if the venv itself is the thing being reverted, vs. seconds if only app code (business-suite/integrasi) changed and the venv is untouched
ROLLBACK_HEALTH_CHECK=both business-suite and integrasi health checks pass

### restaurant (Seller Control)
ROLLBACK_SOURCE=previous Docker image tag (production history shows versioned tags, e.g. `1.3.2-store-api-v2`)
ROLLBACK_RELEASE=the previous image, kept (never delete an image until past the rollback window)
ROLLBACK_COMMAND_CLASS=DOCKER_IMAGE_RECREATE (recreate container from the previous tag)
DATA_COMPATIBILITY=YES — `licenses.db` (SQLite) format unchanged by this plan
MAX_ROLLBACK_TIME=~10s (container recreate)
ROLLBACK_HEALTH_CHECK=HTTP 200 on its served route; a real license-status read succeeds

### parking
ROLLBACK_SOURCE=git revert to the pre-cutover commit, same directory (no release-dir pattern exists — see CUTOVER-PLAN.md Section 3 caveat)
ROLLBACK_RELEASE=N/A
ROLLBACK_COMMAND_CLASS=restart against reverted source, in place
DATA_COMPATIBILITY=YES — no new migrations proposed by this plan; if a future cutover DOES add a migration, `alembic downgrade` must be scoped as its own separate, explicit step, never silently bundled into a code rollback
MAX_ROLLBACK_TIME=seconds
ROLLBACK_HEALTH_CHECK=`/parking/api/health` → `{"status":"ok",...}`; a real authenticated read succeeds against the real production Postgres (not the ephemeral one used in this session's proof)

### drive
ROLLBACK_SOURCE=previous Docker image tag (`botconnector-drive:0.2.0` is current; keep it tagged and untouched)
ROLLBACK_RELEASE=the previous image
ROLLBACK_COMMAND_CLASS=DOCKER_IMAGE_RECREATE via `docker compose up` with the previous tag
DATA_COMPATIBILITY=YES — bind-mounted storage/meta paths unchanged
MAX_ROLLBACK_TIME=~10s
ROLLBACK_HEALTH_CHECK=`/health` → `{"status":"ok",...}`; a real file listing succeeds

### ai-chat-preview
ROLLBACK_SOURCE=the previous dated `releases/ai-chat-core-<ts>` directory (kept, not deleted)
ROLLBACK_RELEASE=point systemd `WorkingDirectory=`/`ExecStart=` back at it (no `current` symlink layer exists today — see CUTOVER-PLAN.md note)
ROLLBACK_COMMAND_CLASS=SYSTEMD_RELEASE_SWITCH (unit file edit + `daemon-reload` + restart)
DATA_COMPATIBILITY=YES
MAX_ROLLBACK_TIME=seconds to ~1 minute (unit reload)
ROLLBACK_HEALTH_CHECK=liveness signal; a real session round-trip through the internal orchestrator succeeds

### ai-workspace
ROLLBACK_SOURCE=git revert
ROLLBACK_RELEASE=N/A (flat WorkingDirectory)
ROLLBACK_COMMAND_CLASS=restart against reverted source
DATA_COMPATIBILITY=YES (no persistent data path identified)
MAX_ROLLBACK_TIME=seconds
ROLLBACK_HEALTH_CHECK=liveness signal

### admin-gate
ROLLBACK_SOURCE=git revert
ROLLBACK_RELEASE=N/A (flat WorkingDirectory)
ROLLBACK_COMMAND_CLASS=restart against reverted source — treat as the single fastest, highest-priority rollback in the whole plan given its blast radius
DATA_COMPATIBILITY=YES
MAX_ROLLBACK_TIME=seconds — this is the one component where "roll back immediately, ask questions after" is the correct default, not a last resort
ROLLBACK_HEALTH_CHECK=a real `auth_request` round-trip against at least 2-3 different panel routes returns expected 2xx/401 (not 5xx)

### services/connector-core (shared venv) + 6 shipping services
ROLLBACK_SOURCE=previous `current` symlink target (public-gateway, location-public-gateway) or previous dated release dir (integration, location-resolver, router, rajaongkir-cost, connector-core itself)
ROLLBACK_RELEASE=kept, not deleted, until the window passes
ROLLBACK_COMMAND_CLASS=SYSTEMD_RELEASE_SWITCH per component; SHARED_RUNTIME_SWITCH for all 7 together only if the shared venv itself was reverted
DATA_COMPATIBILITY=YES — per-service SQLite ledgers unaffected by a code-only rollback
MAX_ROLLBACK_TIME=seconds per component if only that component's release reverts; minutes if the shared venv must be rebuilt
ROLLBACK_HEALTH_CHECK=each service's own health route; **and** the real end-to-end RajaOngkir chain call (public-gateway → integration → RajaOngkir) must succeed post-rollback — this is the one rollback in the whole plan with an external, real-world confirmation step, not just an internal health check

### finance-core
ROLLBACK_SOURCE=previous dated `releases/finance-core-<ts>` directory (kept)
ROLLBACK_RELEASE=point `run-finance-core.sh`'s resolution (or the systemd unit, if it doesn't use the script directly) back at it
ROLLBACK_COMMAND_CLASS=SYSTEMD_RELEASE_SWITCH
DATA_COMPATIBILITY=YES
MAX_ROLLBACK_TIME=seconds to ~1 minute
ROLLBACK_HEALTH_CHECK=`/openapi.json` → 200; **and** confirm business-suite/integrasi (hard `Requires=` dependents) remain healthy after finance-core's rollback — cheapest, most important cross-check in this entire plan

---

```
ROLLBACK_PLAN_COMPLETE=YES
```
