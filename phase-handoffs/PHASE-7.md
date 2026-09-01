# Phase 7: Preview Runtime

## Status

**PASS — READY TO COMMIT**

## Commits

- **BASE_COMMIT**: `b9947db5313e32963bc3ccb8b80cb3fa1520cdff` (Phase 6 final)
- **IMPLEMENTATION_HEAD**: (this is the uncommitted implementation)
- **FINAL_HEAD**: (pending owner approval)

## Files Changed

### New Files (8)

| File | Purpose |
|---|---|
| `apps/sandbox-manager/src/preview/manager.ts` | Preview lifecycle management with LKG + per-project networks |
| `apps/sandbox-manager/src/preview/proxy.ts` | HTTP reverse proxy with bearer auth + header sanitization |
| `apps/sandbox-manager/src/preview/routes.ts` | Internal API routes for preview CRUD operations |
| `apps/sandbox-manager/src/preview/stack-detector.ts` | Auto-detect project type from workspace files |
| `apps/control/src/preview/routes.ts` | Public API routes for preview management |
| `apps/control/src/authorization/project.ts` | Durable project/workspace authorization helpers |
| `apps/control/tests/setup.ts` | Test-only preview configuration |
| `apps/sandbox-manager/tests/phase7.test.ts` | 33 acceptance tests for Phase 7 |

### Modified Files

| File | Change |
|---|---|
| `apps/sandbox-manager/src/sandbox/profiles.ts` | Added `preview` profile (networkEnabled, 512MB, 128 pids, 1.0 CPU) |
| `apps/sandbox-manager/src/sandbox/provider.ts` | Added `networkName`, `createNetwork()`, `removeNetwork()`, `getContainerIp()`, **read-only workspace mount for preview containers** |
| `apps/sandbox-manager/src/config.ts` | Added `previewPort` config field |
| `apps/sandbox-manager/src/index.ts` | Integrated PreviewManager, PreviewProxy with secret, preview routes |
| `apps/sandbox-manager/src/workspace/manager.ts` | Added trusted metadata reload and `getWorkspaceRoot()` |
| `apps/control/src/sandbox-manager/client.ts` | Added preview client methods, made `request()` public |
| `apps/control/src/index.ts` | Registered preview routes with resolvePrincipal, **fail-closed secret** |
| `apps/control/src/sandbox/routes.ts` | Tenant/project authorization for sandbox operations |
| `apps/control/src/workspace/routes.ts` | Tenant/project authorization for workspace operations |
| `apps/control/vitest.config.ts` | Control test setup registration |
| `apps/control/tests/acceptance.test.ts` | Phase 7 health assertion and current-schema test default |
| `packages/database/tests/acceptance.mjs` | Current-schema test default |

## Test Results

| Suite | Tests | Status |
|---|---|---|
| Phase 7 (`phase7.test.ts`) | 33 | **PASS** |
| Phase 6 security (`security.test.ts`) | 61 | **PASS** |
| Phase 5 regression (`phase5.test.ts`) | 56 | **PASS** |
| Phase 6 regression (`phase6.test.ts`) | 11 | **PASS** |
| **Total (sandbox-manager)** | **105** | **ALL PASS** |
| Control regression (`acceptance`, `phase4`, `phase5`) | 151 | **PASS** |
| Database acceptance | 47 | **PASS** |
| Contracts | 42 | **PASS** |

## Typecheck

- `apps/sandbox-manager`: **PASS** (0 errors)
- `apps/control`: **PASS** (0 errors)

## Architecture

```
Browser → Control App (port 3100)
  ├─ /api/v1/previews/* (CRUD + tenant auth via resolvePrincipal)
  ├─ /api/v1/previews/:id/proxy/* (Browser Gateway — verifies ownership → proxies to PreviewProxy)
  ├─ /api/v1/projects/:id/workspaces/* (via SandboxManagerClient)
  └─ /api/v1/projects/:id/sandboxes/* (via SandboxManagerClient)

Control App → SandboxManagerClient → Sandbox Manager (internal, port random)
  ├─ /internal/v1/workspaces/* (workspace CRUD)
  ├─ /internal/v1/sandboxes/* (sandbox CRUD + exec)
  └─ /internal/v1/previews/* (preview CRUD)

Sandbox Manager → PreviewManager → ContainerProvider → Docker (per-project bridge network)
PreviewProxy (port 4100, Bearer auth) → Preview Containers (per-project isolated network)

Browser → Control App (port 3100) /api/v1/previews/:id/proxy/* → PreviewProxy → Container
```

### Preview Profile

| Property | Value |
|---|---|
| Image | Auto-detected (node:20-slim, python:3.12-slim, golang:1.22-slim, rust:slim) |
| Network | `botconnector-preview-{projectId}` (per-project bridge, isolated) |
| CPU | 1.0 |
| Memory | 512MB |
| PIDs | 128 |
| Read-only rootfs | Yes |
| Read-only workspace mount | Yes (`:ro`) |
| Timeout | 300s |

### Stack Detection

| Marker File | Stack | Image | Default Command |
|---|---|---|---|
| `package.json` | node | `node:20-slim` | `npm install && npm run dev` |
| `requirements.txt` | python | `python:3.12-slim` | `pip install -r requirements.txt && python -m http.server $PORT` |
| `pyproject.toml` | python | `python:3.12-slim` | `pip install -e . && python -m http.server $PORT` |
| `go.mod` | go | `golang:1.22-slim` | `go mod download && go run .` |
| `Cargo.toml` | rust | `rust:slim` | `cargo run` |
| `index.html` | static | `python:3.12-slim` | `python3 -m http.server 3000` |
| (none) | static | `python:3.12-slim` | `python3 -m http.server 3000` |

### Security Model

- **NETWORK_ISOLATION**: Each project gets its own Docker bridge network (`botconnector-preview-{projectId}`)
- **CROSS_PROJECT_ISOLATION**: Preview containers from different projects cannot communicate
- **NO_HOST_NETWORK**: Preview containers cannot access host network
- **CAP_DROP_ALL**: All Linux capabilities dropped
- **NO_NEW_PRIVILEGES**: Process escalation prevented
- **READ_ONLY_ROOTFS**: Filesystem immutable except `/workspace` mount and `/tmp`
- **READ_ONLY_WORKSPACE**: Workspace mounted read-only (`:ro`) for preview containers
- **RESOURCE_LIMITS**: CPU, memory, and PID limits enforced
- **BEARER_TOKEN_AUTH**: All API calls authenticated (both control routes and proxy)
- **TENANT_ISOLATION**: Control routes use `resolvePrincipal` — caller can only access their own workspace's previews
- **PATH_TRAVERSAL_GUARD**: Workspace ID validated against `..` and absolute paths; resolved path checked against workspace root
- **SOURCE_REPO_ALLOWLIST**: Repository paths are resolved and must remain under explicit `SOURCE_REPO_ROOT`; no caller can select an arbitrary host repository
- **FAIL_CLOSED_SECRET**: `SANDBOX_MANAGER_SECRET` required — no hardcoded fallback (Lock 6 compliant)
- **SOURCE_REPO_ROOT_REQUIRED**: Explicit allowlist root required for all source repository paths
- **FAIL_CLOSED**: Unknown/unauthorized requests rejected
- **HEADER_SANITIZATION**: Auth, cookie, x-forwarded-* headers stripped from proxied requests
- **RESPONSE_HEADER_SANITIZATION**: Cookie-setting and hop-by-hop response headers stripped from proxied responses
- **PROXY_TIMEOUT**: 30s timeout on proxied requests to prevent hung connections
- **PROXY_BIND_FAIL_CLOSED**: Preview proxy startup rejects bind errors instead of leaving startup pending
- **TRANSACTIONAL_STARTUP**: Main HTTP listener is closed if proxy startup or initial reconciliation fails
- **DISCONNECT_CLEANUP**: Client disconnects abort in-flight preview gateway requests and upstream streams
- **EXECUTABLE_BUILD_TMP**: Build-capable stacks use a scoped executable tmpfs while the general `/tmp` remains `noexec`

### Last Known Good (LKG)

- When a preview reaches `running` state, it becomes the LKG for its project
- LKG tracks: previewId, containerId, image, command, detectedStack, snapshotAt
- LKG is cleared when preview is destroyed or stopped
- LKG reference survives in-memory (not persisted to disk — Phase 11 scope)
- If new candidate fails, previous LKG container reference is available for rollback

### Preview Lifecycle

1. **Create**: `POST /api/v1/previews` → verify tenant → detect stack → create per-project network → create Docker container → wait for IP → set as LKG
2. **Browser Access**: `GET /api/v1/previews/:previewId/proxy/*` → verify tenant + ownership → proxy to PreviewProxy → stream response to browser
3. **API Access**: `GET /api/v1/previews/:previewId` → verify tenant → return preview metadata
4. **Stop**: `POST /api/v1/previews/:previewId/stop` → verify ownership → stops and destroys container → clears LKG
5. **Destroy**: `DELETE /api/v1/previews/:previewId` → verify ownership → destroys container → removes from map → clears LKG
6. **Reconcile**: Periodic scan for orphaned preview containers → destroys orphans

### Safety Guarantees

- **LAST_KNOWN_GOOD**: Running preview automatically becomes LKG for project
- **LAST_VALID_STATE_PRESERVED**: State saved before stop/destroy
- **IDEMPOTENT_CLEANUP**: Destroy/stop can be called multiple times safely
- **ORPHAN_RECONCILIATION**: Preview manager scans for containers with preview labels not in its map
- **NO_RESOURCE_LEAKS**: Containers destroyed on preview destroy

## Security Fixes (Applied After Review)

Six critical issues identified by two external AI reviews (Claude Code + DeepSeek V4 Pro) were fixed:

### C4: Hardcoded Secret Fallback (Lock 6 violation)
- **Before**: `process.env.SANDBOX_MANAGER_SECRET || 'dev-secret'`
- **After**: Throws error if `SANDBOX_MANAGER_SECRET` not set
- **File**: `apps/control/src/index.ts`

### C5: Missing Tenant Auth (§22 Tenancy violation)
- **Before**: Preview routes accepted arbitrary project/workspace/task identifiers from request body
- **After**: Control verifies durable project ownership and workspace/project/task metadata; Sandbox Manager resolves and validates the trusted workspace before mounting it
- **File**: `apps/control/src/preview/routes.ts`

### C6: Path Traversal Risk
- **Before**: String concatenation `getWorkspaceRoot() + '/' + workspace_id`
- **After**: Validates no `..`, not absolute, resolved path within root
- **File**: `apps/sandbox-manager/src/preview/routes.ts`

### D1: No Browser-Reachable Preview Gateway (§14 violation)
- **Before**: PreviewProxy was internal-only (port 4100, required Bearer auth). Browser couldn't access preview.
- **After**: Added `GET/POST/... /api/v1/previews/:previewId/proxy/*` route in control app. Browser sends to control (port 3100), control verifies ownership, proxies to PreviewProxy with internal secret, streams response back.
- **Env var**: `SANDBOX_PREVIEW_URL` required (e.g. `http://127.0.0.1:4100`)
- **File**: `apps/control/src/preview/routes.ts`, `apps/control/src/index.ts`

### D2: Proxy Port Hardcoded 3000
- **Before**: `PreviewProxy.DEFAULT_DEV_PORT = 3000`, `dev_port` parameter ignored by proxy
- **After**: `Preview` interface now includes `devPort` field. Proxy uses `preview.devPort` instead of hardcoded value.
- **Files**: `apps/sandbox-manager/src/preview/manager.ts`, `apps/sandbox-manager/src/preview/proxy.ts`

### D3: Dead Code — Sandbox/Workspace Routes Never Registered
- **Before**: `registerSandboxRoutes` and `registerWorkspaceRoutes` existed but were never called in control `index.ts`
- **After**: Both routes registered with `sandboxManagerClient` and `resolvePrincipal`
- **File**: `apps/control/src/index.ts`

### D4: Config Secret Random Fallback (Lock 6 weak violation)
- **Before**: `requireEnv('SANDBOX_MANAGER_SECRET', randomBytes(32).toString('hex'))` — silently generated random secret
- **After**: Fail-closed — throws if `SANDBOX_MANAGER_SECRET` not set (env var or override)
- **File**: `apps/sandbox-manager/src/config.ts`

### Final Review Hardening
- Preview creation is serialized per project so concurrent candidates cannot orphan a superseded container.
- Container removal failures are surfaced; preview state is not deleted from memory until removal succeeds.
- Worktree creation is rolled back if metadata persistence fails.
- Preview reconciliation runs at startup and periodically while the manager is running.
- `SOURCE_REPO_ROOT` is required in Sandbox Manager configuration and is enforced after symlink resolution.
- Control-to-Sandbox Manager workspace and sandbox payloads are translated to the internal snake_case API contract.

## Known Limitations

1. **LKG persistence**: LKG is in-memory only. Server restart loses LKG references. Full persistence deferred to Phase 11.
2. **HTTPS**: Preview proxy is HTTP only. Production should add TLS termination.
3. **Rate limiting**: No rate limiting on preview creation. Production should add limits per project/tenant.
4. **Zero-downtime swap**: A new preview supersedes the prior preview after it is running; true zero-downtime traffic handoff is deferred.
5. **Preview health check**: No monitoring if container crashes after start. Deferred.
6. **WebSocket in preview**: PreviewProxy doesn't support HTTP upgrade/WebSocket. Live-reload won't work through proxy. Deferred to Phase 8.

## Next Phase

**Phase 8: Canvas / Visual Editor** — DO NOT START until owner approves Phase 7.
