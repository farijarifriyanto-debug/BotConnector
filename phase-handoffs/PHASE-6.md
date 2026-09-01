# Phase 6: Git Workspace & Sandbox

## Status

**PASS / COMMITTED**

## Commits

- **BASE_COMMIT**: `6429f9573225c5628e367c636a823ea84fe96029` (Phase 5 final checkpoint)
- **IMPLEMENTATION_HEAD**: `85f23c136e477e7546e2239d4cc0f2f2d1abc1f9` (Phase 6 implementation)
- **FINAL_HEAD**: (this commit)

## Source Provider / Workspace Model

- **SOURCE_PROVIDER**: PASS
- **EXECUTION_WORKSPACE**: Ephemeral detached Git worktree
- **BASE_REVISION**: Exact immutable full commit SHA
- **TEST_SOURCE_REPOSITORY**: Disposable fixture repository (`/tmp/botconnector-phase6-security/fixture-repo`)
- **CANONICAL_BOTCONNECTOR_USED_AS_MUTABLE_FIXTURE**: NO
- **CANONICAL_SOURCE_UNCHANGED**: PASS
- **SIBLING_WORKSPACE_ISOLATION**: PASS
- **NO_IMPLICIT_COMMIT**: PASS
- **NO_IMPLICIT_MERGE**: PASS
- **NO_GIT_PUSH**: PASS
- **WORKSPACE_DESTROY_IDEMPOTENT**: PASS

### Path Security

- **PATH_TRAVERSAL_BLOCKED**: PASS
- **ABSOLUTE_PATH_ESCAPE_BLOCKED**: PASS
- **SYMLINK_HOST_ESCAPE_BLOCKED**: PASS

## Sandbox Manager Model

### Architecture

```
apps/control
  → trusted internal Sandbox Manager client (HTTP, Bearer token)
    → sandbox-manager (127.0.0.1, authenticated)
      → ContainerProvider (execFile, structured argv)
        → Docker
```

- **CONTROL_DOCKER_ACCESS**: NO
- **SANDBOX_MANAGER_BIND**: 127.0.0.1
- **SANDBOX_MANAGER_PUBLICLY_REACHABLE**: NO
- **SANDBOX_MANAGER_AUTH**: Bearer service token
- **SANDBOX_MANAGER_TOKEN_HARDCODED**: NO
- **SANDBOX_MANAGER_TOKEN_LOGGED**: NO

### Production Token Requirement

Production deployment requires explicit configuration of `SANDBOX_MANAGER_SECRET` environment variable shared between the trusted Control client and the Sandbox Manager. The random fallback (`randomBytes(32)`) is not a production configuration mechanism — it provides fail-closed behavior: an independently started client cannot know the manager token.

**PRODUCTION_SANDBOX_MANAGER_SECRET**: EXPLICIT_CONFIGURATION_REQUIRED
**HARDCODED_SECRET**: NO
**PUBLIC_UNAUTHENTICATED_MANAGER**: NO

## Container Provider

- **DOCKER_INVOCATION**: Structured argv via `execFile` (node:child_process)
- **HOST_SHELL_INTERPOLATION**: NO
- **SUDOERS_CHANGED**: NO

Docker operations limited to: `create`, `start`, `inspect`, `exec`, `stop`, `rm`, `ps`. Docker access is deliberately treated as a highly privileged trusted boundary.

## Sandbox Security Profile

- **PRIVILEGED**: false
- **CAP_DROP_ALL**: PASS
- **NO_NEW_PRIVILEGES**: true
- **HOST_NETWORK**: false
- **HOST_PID**: false
- **HOST_IPC**: false
- **NETWORK_MODE**: none
- **RUN_AS_ROOT**: false
- **READ_ONLY_ROOTFS**: true
- **CPU_LIMIT**: 0.5
- **MEMORY_LIMIT**: 256m
- **PIDS_LIMIT**: 64
- **DOCKER_SOCKET_MOUNTED**: false
- **SANDBOX_MOUNTS_ONLY_APPROVED_PATHS**: PASS
- **HOST_ENV_INHERITED**: NO
- **HOST_SECRET_CANARY_VISIBLE**: NO

### Image

- **SANDBOX_TEST_IMAGE**: python:3.12-slim
- **IMAGE_WAS_ALREADY_LOCAL**: YES
- **IMAGE_PULLED_DURING_PHASE6**: NO
- **IMAGE_BUILT_DURING_PHASE6**: NO

## Execution Model

- **EXEC_USES_STRUCTURED_ARGV**: PASS
- **EXEC_CWD_TRAVERSAL_BLOCKED**: PASS
- **EXEC_ABSOLUTE_HOST_CWD_BLOCKED**: PASS
- **EXEC_TIMEOUT**: PASS
- **BACKGROUND_PROCESS_AFTER_TIMEOUT**: NO
- **OUTPUT_BOUND**: PASS
- **OUTPUT_TRUNCATED_FLAG**: PASS
- **STRUCTURED_EXEC_RESULT**: PASS

Result includes deterministic equivalents of: `exitCode`, `stdout`, `stderr`, `timedOut`, `durationMs`.

## Resource Ownership / Reconciliation

- **PHASE6_CONTAINER_LABELS**: PASS (`botconnector.sandbox=true`, plus `id`, `workspace_id`, `project_id`, `task_id`)
- **UNLABELED_CONTAINER_MUTATED**: NO
- **FOREIGN_LABELED_CONTAINER_MUTATED**: NO
- **PREEXISTING_DOCKER_CONTAINERS_MUTATED**: NO
- **botconnector-core-redis**: Untouched (pre-existing unrelated stack)
- **SANDBOX_DESTROY_IDEMPOTENT**: PASS

### Cleanup

- **PHASE6_TEST_CONTAINERS_LEFT**: 0
- **PHASE6_TEST_WORKTREES_LEFT**: 0
- **PHASE6_TEST_PROCESSES_LEFT**: 0

## Tenant / Task Security

- **CROSS_TENANT_SANDBOX_PROVISION_BLOCKED**: PASS
- **CROSS_PROJECT_TASK_SOURCE_BLOCKED**: PASS
- **CALLER_CANNOT_OVERRIDE_TENANT_ID**: PASS
- **CALLER_CANNOT_OVERRIDE_SOURCE_REPO_PATH**: PASS

Authorization derives through trusted: Principal → Tenant Workspace → Project → Task → ExecutionWorkspace → Sandbox. Docker labels are NOT the authorization boundary.

## Phase-5 State Boundary

- **SANDBOX_CREATE_MUTATES_TASK_STATE**: NO
- **SANDBOX_EXEC_AUTO_COMPLETES_TASK**: NO
- **SANDBOX_CREATE_STARTS_GENERATION_RUN**: NO
- **PHASE5_EXECUTOR_ACK_AUTO_CALLED**: NO

Phase 6 provides execution infrastructure only. No fake orchestration progress.

## Persistence Model

- **EXECUTION_WORKSPACE_PERSISTENCE**: Ephemeral filesystem git worktree
- **SANDBOX_PERSISTENCE**: Ephemeral runtime + Docker ownership labels
- **TASK_RUNTIME_ASSOCIATION**: Ephemeral Phase-6 metadata/label association
- **RECONSTRUCTION_MODEL**: Trusted source repository + exact base commit + trusted task/project/tenant identifiers
- **PHASE6_SCHEMA_CONTRACT_GAP**: NO (ephemeral/reconstructable by design)

Phase 6 intentionally does NOT add durable orchestration tables. ExecutionWorkspace and Sandbox are ephemeral/reconstructable execution resources. If a later phase requires durable runtime-resource bookkeeping beyond this model, it requires its own explicit architecture review.

## Test Results

- **PHASE6_TESTS**: 71/71 PASS (10 original + 61 security)
- **PHASE5_REGRESSION**: 56/56 PASS
- **TYPECHECK_SANDBOX_MANAGER**: PASS
- **TYPECHECK_CONTROL**: PASS
- **DIFF_CHECK**: PASS

No contract migrations were needed.

## Boundaries

- **PREVIEW_IMPLEMENTED**: NO
- **CANVAS_IMPLEMENTED**: NO
- **AI_PROVIDER_IMPLEMENTED**: NO
- **PHASE7_STARTED**: NO

## Known Existing Gaps

- **PROJECT_DELETE**: DEFERRED_SCHEMA_CONTRACT_GAP
- PostgreSQL target: 18+; current runtime may remain 16.15
- Phase-0 CSS backlog: `/static/privacy.css`, `/static/security.css`
- Pre-existing `botconnector-core-redis` belongs to another stack and remains untouched

## Next Phase

**NEXT_PHASE**: PHASE_7_PREVIEW_RUNTIME_BRIDGE

Phase 7 is NOT implicitly authorized.
