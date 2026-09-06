# Security Incident: Hardcoded SMTP Credential

Opened 2026-09-06. Account: `admin@botconnector.id` on `smtp.hostinger.com`.
No credential value appears anywhere in this document. No provider
password has been rotated — this incident is **not closed**; it is
blocked pending a decision described in Phase 5 below.

## Phase 0 — Mail dependency map (read-only)

Searched by account identity (`admin@botconnector.id`) and host
(`smtp.hostinger.com`) across `/etc/botconnector*`, relevant `/opt/botconnector-*`
trees, this canonical repo, systemd units, and all running Docker
containers' environment variable *names* (never values).

CONSUMER=apps/homepage-runtime (`app/support.py`) / live at `/opt/botconnector-platform-starter-v0.3/homepage`
PROTOCOL=SMTP
CONFIG_PATH=hardcoded literal in source (the actual incident); no `.env` override existed anywhere on the box
SECRET_SOURCE=hardcoded fallback in `app/support.py` line 30 (now fixed in both canonical and live source — see Phase 4)
HARDCODED=YES (this is the incident)
RESTART_REQUIRED=YES, but only after rotation (Phase 6) — restarting now would not change anything, the running container still has the old baked-in value regardless of the on-disk source fix
CUSTOMER_IMPACT=Support ticket email notifications (admin notification + user acknowledgement) silently fail-closed if this credential is ever invalidated; ticket creation itself is unaffected (confirmed in code: failures are caught and recorded in `support_email_outbox`, not raised)
CONFIDENCE=HIGH — hash-verified against the live image; this is the only place in the entire homepage runtime that calls `smtplib`

CONSUMER=`botconnector-backend-worker` and `botconnector-backend-api` (Docker containers, project `botconnector-backend-core`, compose file `/opt/botconnector-backend-core/docker-compose.yml`)
PROTOCOL=SMTP
CONFIG_PATH=`/opt/botconnector-backend-core/docker-compose.yml` (env injection point — not individually opened, per the standing DO_NOT_TOUCH rule on unresolved external runtime)
SECRET_SOURCE=environment variable (name confirmed present: `SMTP_PASSWORD`; not hardcoded in an image layer as far as env-var-name inspection can tell — this is a materially safer pattern than the homepage's, though not independently verified further)
HARDCODED=UNKNOWN (env var is properly used, not read from source; whether the compose file or an `.env` beside it embeds the literal was not checked, out of respect for the DO_NOT_TOUCH boundary)
RESTART_REQUIRED=YES if this credential is ever rotated
CUSTOMER_IMPACT=UNKNOWN — this system ("smartbiz-ai-studio"/"smartbiz-internal-actions", image `botconnector-backend-core`) is entirely outside this consolidation's 21-component canonical scope and was never audited
CONFIDENCE=HIGH that it exists and uses the same mailbox account; **CRITICAL FINDING: hash-compared its `SMTP_PASSWORD` against the homepage's leaked literal — they are DIFFERENT values.** Same `SMTP_USERNAME`/`SMTP_HOST` (confirmed: `admin@botconnector.id` / `smtp.hostinger.com`), different password. This means either (a) this account currently has multiple valid app-passwords if Hostinger supports that, or (b) one of the two systems is currently authenticating with an already-stale credential, or (c) the mailbox provider is lenient about concurrent sessions. Not resolved — flagging for you, not guessing.

CONSUMER=`/opt/botconnector-core/.env` (legacy, no active systemd unit or container — confirmed dormant)
PROTOCOL=SMTP (config present)
CONFIG_PATH=`/opt/botconnector-core/.env`
SECRET_SOURCE=plaintext `.env` file on disk
HARDCODED=NO (env file, not source code) but still a plaintext secret at rest
HARDCODED_VALUE_MATCHES_LEAK=NO — hash-compared, this is a third, different value
RESTART_REQUIRED=N/A — nothing currently reads this file (no systemd unit or container found referencing `/opt/botconnector-core`)
CUSTOMER_IMPACT=NONE currently (dormant service) — but the secret itself is real and sits in a world of its own; not part of this incident's active-credential scope, noted for completeness only
CONFIDENCE=MEDIUM (confirmed dormant via `systemctl` and `docker ps`, not exhaustively via process `cwd` inspection)

CONSUMER=three other `.env` files matching `smtp.hostinger.com` (`/opt/botconnector-backups/ea-website-20260811T134858Z/.env`, `/opt/botconnector-backups/panel-support-monitor-20260811T150932Z/connect/.env`, `/opt/botconnector-v2-candidate/.env`)
PROTOCOL=SMTP (host configured)
HARDCODED=N/A — hash-compared, all three have an **empty** `SMTP_PASSWORD` value (no credential set at all)
CUSTOMER_IMPACT=NONE — not consumers of the actual secret
CONFIDENCE=HIGH

```
MAIL_CONSUMERS_FOUND=2 active (homepage-runtime; botconnector-backend-core's worker+api sharing one config) + 1 dormant (legacy botconnector-core, separate credential, no impact)
UNKNOWN_MAIL_CONSUMERS=0 by identity (all found), but botconnector-backend-core's exact secret-storage mechanism (compose env vs. its own `.env` file) was not opened, per the standing DO_NOT_TOUCH boundary on that system
IMAP_USAGE_FOUND=NO
CRON_TIMER_USAGE_FOUND=NO
SAME_PASSWORD_ACROSS_CONSUMERS=NO — three distinct values found across homepage-runtime, botconnector-backend-core, and the dormant legacy botconnector-core; none match each other
```

## Phase 1 — Confirm active use

```
SMTP_FUNCTION_USED_BY=apps/homepage-runtime / app/support.py, functions send_admin_notification() and send_user_acknowledgement()
SMTP_SEND_PATH=support ticket creation (POST /support, POST /api/support/tickets) → SupportTicketManager writes to Postgres → inline call to send email via smtplib, failure recorded in support_email_outbox without failing the ticket
SMTP_REQUIRED_FOR_SUPPORT_TICKET=NO — ticket creation succeeds even if email sending fails (confirmed in code, not assumed)
SMTP_REQUIRED_FOR_OTHER_FUNCTIONS=none identified — this is the only SMTP call site in the entire homepage runtime
CURRENT_CREDENTIAL_ACTIVE=YES — confirmed no `.env` on the box ever overrode `SMTP_PASSWORD` for the homepage runtime, meaning the hardcoded literal was the value actually used by every live send attempt until this patch
```

## Phase 2 — Targeted secret occurrence search

Searched only the paths the incident scope named: this canonical repo,
`/opt/botconnector-platform-starter-v0.3/homepage`, `/etc/botconnector`,
relevant systemd/Docker config, and — once discovered as a consumer —
`botconnector-backend-core`'s container environment (names only). No
whole-filesystem scan was performed.

```
OLD_SMTP_SECRET_IN_SOURCE=YES (was — live source patched this session; canonical repo never had the real value beyond the one commit before this incident's fix, and that commit is being amended/followed up per Phase 11 below)
OLD_SMTP_SECRET_IN_ACTIVE_CONFIG=NO (no .env anywhere sets this value; the literal lived only in source)
OLD_SMTP_SECRET_IN_RUNTIME_ENV=NO (not present as an env var anywhere — it was a Python source default, not an environment value)
OLD_SMTP_SECRET_IN_LOGS=NOT CHECKED this pass — `journalctl`/auth logs for the homepage service were not searched for the literal; recommend a follow-up grep of the systemd journal for this service if you want that closed out explicitly
OLD_SMTP_SECRET_IN_GIT=YES, in this repo's history up to and including commit b662c81 (the initial homepage-runtime import already had the empty-string fix applied at commit time — see docs/provenance/SOURCE-MAP.md — so the raw literal itself was never actually committed to this repo's git history; only referenced in prose in `EXTERNAL-PROVIDERS.md` and this incident doc, both of which describe the finding without ever printing the value)
```

## Phase 3 — Canonical secret mechanism

```
CANONICAL_SECRET_MECHANISM=/etc/botconnector/credentials/homepage-smtp-password (path convention only — file does not exist yet; creating it now would mean writing either the OLD compromised value, which defeats the point, or a value that isn't the real rotated password yet. It should be created at Phase 6, with the NEW password, by whoever performs the Hostinger rotation.)
SMTP_PASSWORD_FILE_SUPPORT=YES — both apps/homepage-runtime/app/support.py (canonical) and /opt/botconnector-platform-starter-v0.3/homepage/app/support.py (live source, not yet running) now implement `_read_smtp_password()`, matching the existing `_read_pg_password()`/`_read_redis_password()` pattern exactly: prefers `SMTP_PASSWORD_FILE`, falls back to `SMTP_PASSWORD` env var, raises if neither is set.
FAIL_CLOSED_BEHAVIOR=CONFIRMED — the raise is caught by the existing outer exception handler, which records the failure in `support_email_outbox` and returns False without affecting ticket creation or any other homepage function. Verified by reading the code, not assumed.
```

## Phase 4 — Patch canonical + live source

```
CANONICAL_PATCHED=YES (apps/homepage-runtime/app/support.py)
LIVE_SOURCE_PATCHED=YES (/opt/botconnector-platform-starter-v0.3/homepage/app/support.py)
LIVE_SOURCE_BACKUP=/home/botadmin/backups/security-incidents/smtp-credential-20260906/support.py.pre-fix-backup
LIVE_SOURCE_BACKUP_SHA256=48b1b9eb3ea856aee00ef47446cee43d396f3cfe2ab39e08c8d71bd66593663c (matches the hash independently captured from the running container's image earlier this session — confirms the backup is byte-identical to what's actually live)
LIVE_SOURCE_PATCHED_SHA256=43219b8716cc1c89754c9d0f7e2a6ecf699678fcb0a8c165c1dbaca2219498b9
ROLLBACK_COMMAND=sudo cp /home/botadmin/backups/security-incidents/smtp-credential-20260906/support.py.pre-fix-backup /opt/botconnector-platform-starter-v0.3/homepage/app/support.py
STALE_BYTECODE_CLEARED=YES (removed the host-side `__pycache__/support.cpython-312.pyc` that could otherwise retain the compiled literal; the running container's own filesystem layer was not touched)
CONTAINER_RESTARTED=NO — the running `botconnector-platform-home` container still runs the OLD baked image (still has the old literal in that image's layer) and has NOT been restarted. This patch only changes what's on disk for the NEXT build; production behavior is unchanged until Phase 7.
```

## Phase 5 — Provider password rotation plan: STOPPED HERE

```
ALL_MAIL_CONSUMERS_FOUND=YES (by identity)
READY_FOR_PROVIDER_PASSWORD_ROTATION=NO
```

**Blocker, not a simple go/no-go**: rotating the Hostinger password for
`admin@botconnector.id` will very likely break `botconnector-backend-core`
(containers `botconnector-backend-worker` and `botconnector-backend-api`),
which currently authenticates to the *same mailbox* with a *different*
password than the one being retired. That system is entirely outside this
consolidation's 21-component canonical scope, was explicitly classified
`UNRESOLVED_EXTERNAL_RUNTIME` / `DO_NOT_TOUCH` in an earlier phase, and
its actual secret-storage mechanism was deliberately not opened this
session out of respect for that boundary.

Two things need to happen, neither performed here, before rotation is
safe:
1. **A human action on the Hostinger dashboard** — logging in and changing
   the mailbox password for `admin@botconnector.id`. This is exactly the
   kind of provider-side action the task instructions say I should not
   automate or invent credentials for.
2. **Coordination with whoever owns `botconnector-backend-core`** — either
   that system's config needs to be updated to the same new password in
   the same rotation window, or a decision needs to be made that these are
   deliberately meant to be independent app-specific credentials (in which
   case only the homepage's should rotate, and `botconnector-backend-core`
   keeps its existing, apparently-already-different one — Hostinger's
   mailbox product would need to actually support that for both to keep
   working simultaneously, which was not verified this session).

Until you tell me which of those two paths you want, Phases 6–9 (rotate,
activate, verify, regression-test) cannot proceed.

## Phase 10 — Secret safety (partial, as far as Phases 0–4 allow)

```
HARDCODED_SMTP_SECRET_REMOVED=YES (both canonical and live source)
OLD_SMTP_SECRET_IN_ACTIVE_CONFIG=NO
NEW_SMTP_SECRET_IN_SOURCE=NO (no new secret has been created yet — rotation hasn't happened)
NEW_SMTP_SECRET_IN_ARGV=N/A
NEW_SMTP_SECRET_IN_GIT=N/A
NEW_SMTP_SECRET_IN_LOG=N/A
```

No audit log was purged or altered.

## Credential Truth Gate (2026-09-06, follow-up) — CORRECTS the finding above

**Correction, not a new finding layered on top of a wrong one**: the
"three distinct values found across homepage-runtime, botconnector-backend-core,
and the dormant legacy botconnector-core" claim in Phase 0/2 above is
**wrong** for backend-core specifically, and is superseded by this
section. The earlier hash comparison of `botconnector-backend-api`'s
`SMTP_PASSWORD` was an extraction error on my part (a shell/template
issue, not re-diagnosed further since it doesn't matter — what matters is
the corrected result, verified three independent ways this turn: Go
template `docker inspect`, Python JSON parsing of the same `docker
inspect` output, and `docker exec ... printenv` run directly inside both
`botconnector-backend-api` and `botconnector-backend-worker`). All three
methods agree.

### 1. Active-runtime status (re-confirmed)

```
ACTIVE_CONTAINER_CONTAINS_OLD_SMTP_LITERAL=YES — the running botconnector-platform-home container (image tenantization-v1-20260828, started 2026-09-06T03:34:12Z, unchanged since) still has the old hardcoded literal baked into its filesystem layer. It has not been rebuilt or recreated.
ACTIVE_CONTAINER_USES_OLD_SMTP_CREDENTIAL=YES — confirmed no SMTP_PASSWORD or SMTP_PASSWORD_FILE environment override exists on the running container, so it falls through to the hardcoded literal on every send attempt.
```

### 2. Which credentials are valid (SMTP AUTH-only, no email sent)

Extracted each credential and used it entirely within a throwaway/inline
process — never written to a file, never passed as a CLI argument, never
echoed to a terminal on its own, never persisted to shell history (each
extraction used command substitution, not literal typing). No MAIL/RCPT/DATA
was issued — only `EHLO` + `AUTH LOGIN` + `QUIT`.

```
HOMEPAGE_CURRENT_CREDENTIAL_AUTH=PASS (extracted from the running image's baked-in source, used inline inside a throwaway container run of that same image — nothing else touched)
BACKEND_CORE_CURRENT_CREDENTIAL_AUTH=PASS (extracted from the running container's environment, piped via stdin into a disposable, unrelated python:3.12-slim container for the AUTH attempt — botconnector-backend-api/-worker themselves were never executed into for this specific test, only inspected)
```

### 3. Backend-core credential source (read-only, corrected)

```
BACKEND_CORE_SMTP_ACCOUNT=admin@botconnector.id (same account as homepage — confirmed via SMTP_USERNAME/SMTP_HOST env vars, unchanged from the original Phase 0 finding)
BACKEND_CORE_SECRET_SOURCE=/opt/botconnector-core/.env, loaded via `env_file:` in /opt/botconnector-backend-core/docker-compose.yml (both the `api` and `worker` services reference this same file)
API_AND_WORKER_SHARE_SAME_SECRET=YES (confirmed via docker exec inside both — identical hash)
HARDCODED=NO — not a literal in the compose YAML (checked structurally: only `SERVICE_ROLE` is set inline under `environment:`; `SMTP_PASSWORD` comes exclusively from the `env_file`)
ENV_BASED=YES
FILE_BASED=YES (the env_file itself, /opt/botconnector-core/.env, is a plaintext file at rest — better than a source-code hardcode, but still a plaintext secret on disk, same class of exposure as any other .env)
BACKEND_CORE_CHANGE_ACTIVATION=CONTAINER_RECREATE — env_file contents are read at container creation time in Docker Compose, not hot-reloaded by a plain restart. Changing /opt/botconnector-core/.env would require `docker compose up` (recreate), not just `docker restart`. NOT PERFORMED.
```

**Important correction to the earlier "dormant, no impact" classification** of `/opt/botconnector-core/.env` in Phase 0 above: that file is NOT dormant. It is the live, active `env_file` source for `botconnector-backend-api` and `botconnector-backend-worker`. The earlier "no active systemd unit or container references /opt/botconnector-core" check was true only in the narrow sense that nothing is named exactly `botconnector-core` — it missed that `botconnector-backend-core`'s compose file points AT that same `/opt/botconnector-core/.env` path. `docs/migration/RETIREMENT-MAP.md`'s classification of `/opt/botconnector-core` as `DELETE_AFTER_CUTOVER` (a legacy, unreferenced connector-core-shaped directory) needs re-examination — the directory may hold unrelated legacy connector-core source AND be the live secret store for an unrelated, currently-active system. Flagging for a follow-up correction to that document; not corrected in this turn since it's outside this incident's immediate scope.

### 4. Interpretation

```
CREDENTIAL_CASE=NONE OF A/B/C/D AS DEFINED — all four presuppose the two sides hold different credential values. They don't. Homepage (hardcoded literal) and backend-core (/opt/botconnector-core/.env) hold the IDENTICAL credential value, verified byte-for-byte via hash. Both authenticate because it's the same secret, not because Hostinger independently accepts two different app-passwords. The original premise stated at the top of this turn's instructions ("Homepage and backend-core currently reference DIFFERENT credential values") was based on my own earlier incorrect measurement and is corrected here.
```

This is actually the SIMPLEST possible outcome, not a more complicated
one: there is exactly ONE credential, in active use by exactly two
storage locations (a source-code hardcode, and a plaintext `.env` file),
consumed by exactly three processes (`botconnector-platform-home`,
`botconnector-backend-api`, `botconnector-backend-worker`).

### 5. Rotation strategy (choreography only — nothing implemented this turn)

Since all three consumers share one identical credential, the "rotate as
ONE coordinated boundary" default rule isn't a cautious fallback here —
it's the only correct option, now proven rather than assumed.

```
1. provision new protected credential mechanism for homepage — /etc/botconnector/credentials/homepage-smtp-password (path defined, Phase 3 above; not created yet)
2. prepare backend-core protected credential mechanism — NOT DESIGNED THIS TURN (backend-core is out of scope to modify; if the same rotated value is meant to serve both, a decision is needed on whether backend-core keeps reading from a plaintext `/opt/botconnector-core/.env` or is migrated to a protected-file mechanism matching the rest of the platform's pattern — that migration is itself a change to an out-of-scope system and needs explicit authorization)
3. human rotates provider credential — Hostinger dashboard, not automatable from here
4. update all affected protected secret files — homepage's new file, AND /opt/botconnector-core/.env (both need the SAME new value, since both processes share one mailbox)
5. activate exact affected runtimes only — recreate botconnector-platform-home (image rebuild + container recreate) AND recreate botconnector-backend-api + botconnector-backend-worker (env_file re-read requires recreate, not restart) — recreating backend-core is itself a "modify," so this step requires your explicit go-ahead when the time comes, separate from homepage's own recreate
6. SMTP AUTH verification — same technique used in this turn, repeated against the new credential, for all three consumers
7. controlled internal send — one test email, internal recipient only, not a customer
8. prove old credential rejected — attempt AUTH with the old value post-rotation, expect FAIL
9. regression checks — homepage health/auth/catalog/gateway/support routes; backend-core's own health, if you authorize checking it
10. STOP
```

```
ALL_ACTIVE_MAIL_CONSUMERS_KNOWN=YES
COORDINATED_ROTATION_REQUIRED=YES (proven, not assumed)
READY_FOR_HUMAN_PROVIDER_ROTATION=YES for the Hostinger dashboard action itself; NO for proceeding further until you decide how step 2 above (backend-core's credential mechanism) should be handled, since I can't modify that system without your explicit authorization
```

## Coordinated Rotation Preparation (2026-09-06, authorized follow-up)

Authorization received to modify `botconnector-backend-core` ONLY as
required for this SMTP migration. No other backend-core behavior was
touched. No container was recreated or restarted. No provider password
was changed.

### Backend-core SMTP path audit (read-only, before any change)

```
SMTP_CONFIG_MODULE=/opt/botconnector-backend-core/app/config.py (pydantic-settings Settings class), consumed by /opt/botconnector-backend-core/app/mailer.py
SMTP_PASSWORD_ENV_NAME=SMTP_PASSWORD (field on Settings, sourced from the shared env_file /opt/botconnector-core/.env)
READ_AT_IMPORT=YES, effectively — get_settings() is @lru_cache'd, so Settings() is built once per process lifetime and reused; not literally read at Python `import` time but read once and cached, same practical effect
READ_PER_SEND=NO — mailer.send_email() calls get_settings() but receives the cached instance
API_SMTP_USAGE=REAL — app/account.py and app/account_service.py call into mailer.py for email verification, password reset, and new-login security notifications (all real, account-security-relevant email, not just support tickets)
WORKER_SMTP_USAGE=NONE — worker.py never imports mailer or references SMTP; it inherits SMTP_PASSWORD via the shared env_file purely because api and worker happen to load the same .env, not because it sends mail
```

This also resolves an open question from the earlier Duplication Check in
`docs/provenance/HOMEPAGE-CONVERGENCE.md`: `botconnector-backend-core`
contains `drive_public_share.py`, `drive_share.py`, `drive_file_request.py`,
`drive_bridge.py`, `drive_admin_quota.py`, `drive_quota_policy.py`,
`google_drive_*.py`, and `smartbiz_*.py` — the same names as the
"UNKNOWN backend" modules in `apps/homepage-runtime`. Strong circumstantial
evidence that `botconnector-backend-core` is that backend, though this
was not exhaustively confirmed (no call graph trace was done) and is
noted here only because it surfaced naturally, not chased further —
unrelated to this SMTP incident and outside this turn's authorization.

### Implementation (minimum change, matching backend-core's own existing pattern)

`config.py` already had a precedent for exactly this ("Phase 4B" in its
own comments, for `REDIS_PASSWORD_FILE`). Added `SMTP_PASSWORD_FILE`
using the identical pattern — a few lines inside `get_settings()`, no
other function touched, no DB/Redis/auth/queue/route code changed.

```
BACKEND_CORE_PATCHED=YES (/opt/botconnector-backend-core/app/config.py)
BACKEND_CORE_BACKUP=/home/botadmin/backups/security-incidents/smtp-credential-20260906/backend-core-config.py.pre-fix-backup
BACKEND_CORE_BACKUP_SHA256=38285bf216d397f7efc338102ce949fb3b8496d63d3535fe39342e769f671e24
BACKEND_CORE_PATCHED_SHA256=d33516b01ea9a31a9bf84675256b4ca94dfb9784d569999082b8b697378d2dda
BACKEND_CORE_ROLLBACK_COMMAND=sudo cp /home/botadmin/backups/security-incidents/smtp-credential-20260906/backend-core-config.py.pre-fix-backup /opt/botconnector-backend-core/app/config.py
```

Behavior: `SMTP_PASSWORD` stays an optional field (unlike the required
`POSTGRES_PASSWORD`/`REDIS_PASSWORD`) — a missing/absent
`SMTP_PASSWORD_FILE` silently falls through to the existing plaintext
`SMTP_PASSWORD` env behavior (backward compatible, nothing breaks today).
Once the file is populated (Phase 6, not yet done), it takes precedence.
No logging of the value anywhere in this code path; exceptions from a
missing file (`FileNotFoundError`) would surface the file *path*, never
its contents.

### Protected secret paths (created empty — no credential written)

```
HOMEPAGE_SECRET_FILE_PATH=/etc/botconnector/credentials/homepage-smtp-password (root:root, mode 600 — matches homepage's Dockerfile running as root, same as the existing homepage-db-password file)
BACKEND_CORE_SECRET_FILE_PATH=/etc/botconnector/credentials/backend-core-smtp-password (10001:10001, mode 400 — matches backend-core's Dockerfile `USER 10001:10001`, same as the existing backend-core-db-password/backend-core-redis-password files)
```

Both currently contain zero bytes. Neither the old (compromised) value nor
a fabricated one was written to either file.

**Self-caught mistake, corrected before it mattered**: `backend-core-smtp-password`
was initially created `root:root, 600` (copying the homepage convention
without checking backend-core's actual container user first) — would
have been unreadable by the container's actual UID 10001 process at
activation time. Caught by checking the Dockerfile's `USER 10001:10001`
directive before any container touched this file, and corrected to
`10001:10001, 400` to match the existing sibling secret files for the
same service.

### Compose preparation (staged only — no recreate)

`/opt/botconnector-backend-core/docker-compose.yml` was updated to add,
for both `api` and `worker` services: a read-only bind mount of
`backend-core-smtp-password` to `/run/secrets/smtp_password`, and
`SMTP_PASSWORD_FILE: /run/secrets/smtp_password` under `environment:` —
the same shape already used for `postgres_password`/`redis_password` in
this same file.

```
BACKEND_CORE_COMPOSE_PREPARED=YES
BACKEND_CORE_COMPOSE_BACKUP=/home/botadmin/backups/security-incidents/smtp-credential-20260906/backend-core-docker-compose.yml.pre-fix-backup
BACKEND_CORE_COMPOSE_BACKUP_SHA256=f6be756a64cb673a81e7ffb51c5d02c6dd235013b65214ff298a12fe8b521983
BACKEND_CORE_COMPOSE_ROLLBACK_COMMAND=sudo cp /home/botadmin/backups/security-incidents/smtp-credential-20260906/backend-core-docker-compose.yml.pre-fix-backup /opt/botconnector-backend-core/docker-compose.yml
```

**Critical activation-order warning, not yet a problem because nothing
has been recreated**: the new secret file is currently EMPTY. If
`botconnector-backend-api`/`-worker` were recreated right now with this
compose file, the `SMTP_PASSWORD_FILE` mount would take precedence and
resolve to an empty string, actively breaking email verification/password
reset/security-login notifications that currently work — worse than doing
nothing. **The secret file must be populated with the real, newly-rotated
password BEFORE any recreate, never after.** Same warning applies
symmetrically to homepage's file.

### Pre-rotation functional proof (isolated, dummy values only, cleaned up after)

Neither test touched a real container, a real credential, or sent an
email. Both venvs/temp files were removed after.

```
HOMEPAGE_SMTP_FILE_SUPPORT=PASS — the exact `_read_smtp_password()` function (copy-pasted from the patched source, not reimplemented) correctly read a dummy value from a temp file, and correctly raised RuntimeError when unset (fail-closed confirmed)
BACKEND_CORE_SMTP_FILE_SUPPORT=PASS — imported the ACTUAL patched app/config.py module in a disposable venv with fake required Postgres/Redis/secret fields, confirmed SMTP_PASSWORD_FILE is preferred when set, AND confirmed backward compatibility (plain SMTP_PASSWORD env var still works when no file is set)
```

### Rollback definitions

```
HOMEPAGE:
  ROLLBACK_SOURCE=/opt/botconnector-platform-starter-v0.3/homepage/app/support.py already reverted-ready via support.py.pre-fix-backup (sha256 48b1b9eb...)
  If a future container recreate needs rollback: recreate again from the
  previous image tag (botconnector-platform-home:tenantization-v1-20260828),
  which still exists and was never removed.
  Does not require guessing the old credential — the old image already has it baked in.

BACKEND_API:
  Revert /opt/botconnector-backend-core/app/config.py and docker-compose.yml
  from their pre-fix backups (commands above), then `docker compose up`
  to recreate against the reverted compose file. The current running
  container (image botconnector-backend-core:0.5.8-smartbiz-internal-actions-20260805t075831z)
  is untouched and still running — rollback of the STAGED files requires
  no container action at all unless a recreate already happened.

BACKEND_WORKER:
  Same as BACKEND_API — same compose file, same config.py, same backups.
```

```
ROLLBACK_READY=YES
```

### Human rotation handoff

```
READY_FOR_HOSTINGER_PASSWORD_CHANGE=YES (VPS-side preparation only — this itself is not the rotation)
```

**Exact human action required**: log into the Hostinger control panel
(hPanel) → Email accounts → `admin@botconnector.id` → change password.
Generate or choose a new strong password there; do not reuse the old one
(it is considered permanently compromised).

**Do not paste the new password into this chat.** Safe VPS-side entry
pattern, to be run by you (or with you present) directly on the VPS
terminal — never through a channel that logs or echoes it:

```bash
# For the homepage secret:
sudo bash -c 'read -s -p "New SMTP password: " PW && printf "%s" "$PW" > /etc/botconnector/credentials/homepage-smtp-password && unset PW' 
sudo chown root:root /etc/botconnector/credentials/homepage-smtp-password
sudo chmod 600 /etc/botconnector/credentials/homepage-smtp-password

# For backend-core's secret (same value, same mailbox):
sudo bash -c 'read -s -p "New SMTP password: " PW && printf "%s" "$PW" > /etc/botconnector/credentials/backend-core-smtp-password && unset PW'
sudo chown 10001:10001 /etc/botconnector/credentials/backend-core-smtp-password
sudo chmod 400 /etc/botconnector/credentials/backend-core-smtp-password
```

`read -s` never echoes to the terminal, the value never appears as a
command argument (it's typed interactively into a variable), and
`unset PW` clears it from the shell's memory immediately after. Nothing
here goes into shell history (interactive `read` input isn't recorded the
way a typed command is) or any log.

### Exact activation order (once the password files above are populated)

```
1. Populate BOTH secret files with the SAME new password (commands above) — do this first, always
2. Rebuild apps/homepage-runtime's image from canonical source (already proven this session) and recreate ONLY botconnector-platform-home:
     docker compose -f /opt/botconnector-platform-starter-v0.3/homepage/docker-compose.yml up -d --no-deps botconnector-home
3. Recreate ONLY the backend-core services (exact service names, not the whole stack blindly):
     docker compose -f /opt/botconnector-backend-core/docker-compose.yml up -d --no-deps api worker
4. SMTP AUTH verification against the NEW password for all three consumers (same isolated technique used in the Credential Truth Gate)
5. One controlled internal test send (not a customer)
6. Attempt AUTH with the OLD credential, confirm it's rejected
7. Homepage regression: health, login, register, catalog, application gateway, support route
8. Backend-core regression: /health, and (with your authorization) one real verification/reset-email code path
9. Remove the plaintext SMTP_PASSWORD value from /opt/botconnector-core/.env (keep every other line in that file untouched), then confirm no process needs a recreate to pick up its absence (both api/worker will already be running on the file-based value from step 1)
10. STOP
```

None of the above was executed. `docker compose ... up` was never run.

## Incident reclassification (2026-09-06, final)

**User decision: no password rotation.** This incident is closed as a
**HARDCODED_CREDENTIAL_REMOVAL**, not a **CONFIRMED_ACCOUNT_COMPROMISE**.

```
NO_EVIDENCE_OF_EXTERNAL_COMPROMISE=TRUE — nothing found this session indicates the credential was accessed by anyone outside this box; the exposure was source-code hygiene (a hardcoded fallback readable by anyone with source access), not a detected breach
PASSWORD_ROTATION_DECLINED_BY_USER=TRUE
ACTIVE_HARDCODE_REMOVED=TRUE
SMTP_PASSWORD_ROTATED=NO — the credential value is unchanged throughout this entire incident
```

## Homepage activation (executed, 2026-09-06)

Per explicit authorization to remove the hardcode and activate the fix
without rotating the password.

### Secret extraction — one real correction made mid-task

Initially wrote `/etc/botconnector/credentials/homepage-smtp-password`
from `/opt/botconnector-core/.env`'s `SMTP_PASSWORD` line, per the
instruction to source it from "the already-known active backend-core
configuration." **Hash-verified against the previously-proven-authenticating
value and it did NOT match.** Investigated: only one `SMTP_PASSWORD` line
exists in that file, so this isn't a duplicate-key issue — the file's
current on-disk content has apparently drifted from what the running
`botconnector-backend-api`/`-worker` containers actually loaded at their
last creation (containers cache env at creation time; a later edit to the
`.env` file doesn't reach an already-running container). **Corrected by
re-extracting directly from the live `botconnector-backend-api`
container's actual process environment** (`docker exec ... printf
"$SMTP_PASSWORD"`, read-only, no modification to backend-core), which
hash-matched the proven-good value exactly. The file now holds the
correct, verified-working credential.

**Follow-up finding, not yet resolved**: `/opt/botconnector-core/.env`'s
`SMTP_PASSWORD` value differs from what the running backend-core
containers actually use. Either the file was edited after the containers'
last start (most likely), or there's a config-precedence mechanism not
yet identified. This means if `botconnector-backend-api`/`-worker` are
ever recreated (for any reason, unrelated to this incident) WITHOUT
first fixing the file, they would silently pick up this different,
unverified value and could break. Flagging for you — not fixed here,
`/opt/botconnector-core/.env` was explicitly off-limits this turn.

```
HOMEPAGE_SMTP_SECRET_FILE=PASS (root:root, mode 600, 25 bytes, hash-verified against the proven-authenticating credential)
```

### Clean image build and verification

```
NEW_IMAGE_TAG=botconnector-platform-home:tenantization-v1-20260828 (same tag as before — this compose file's own convention is a mutable working tag, not per-build unique tags; the OLD image content is still retrievable by its content ID, sha256:89cfee8f5c9d542ba709c5501ffcbbab5ac5705e886ab9df5086530483b7df76, recorded below for rollback)
HARDCODED_SMTP_LITERAL_IN_NEW_IMAGE=NO — verified two ways without printing the value: (1) regex-extracted the exact default-value pattern from the new image's support.py and confirmed it's an empty string, not a literal; (2) hashed the new image's support.py and confirmed it exactly matches the already-known-clean patched source hash (43219b8716cc1c89754c9d0f7e2a6ecf699678fcb0a8c165c1dbaca2219498b9)
```

### Activation

```
OLD_CONTAINER_ID=ba22df6f6a356e023e2c953837df4b2ac1d89f53d6bc7460bfbb557be338505f
OLD_IMAGE_ID=sha256:89cfee8f5c9d542ba709c5501ffcbbab5ac5705e886ab9df5086530483b7df76 (retained, untagged but recoverable — `docker tag <id> botconnector-platform-home:tenantization-v1-20260828` restores the tag)
ACTIVATION_COMMAND=cd /opt/botconnector-platform-starter-v0.3/homepage && docker compose build botconnector-home && docker compose up -d --no-deps botconnector-home
ROLLBACK_COMMAND=docker tag sha256:89cfee8f5c9d542ba709c5501ffcbbab5ac5705e886ab9df5086530483b7df76 botconnector-platform-home:tenantization-v1-20260828 && cd /opt/botconnector-platform-starter-v0.3/homepage && docker compose up -d --no-deps botconnector-home (plus revert docker-compose.yml from homepage-docker-compose.yml.pre-fix-backup if the mount itself needs undoing)
```

### Post-activation verification (all PASS)

```
HOMEPAGE_HEALTH=PASS ({"ok":true,"service":"botconnector-platform-home",...}, Docker healthcheck reports "healthy")
LOGIN_ROUTE=PASS (200)
REGISTER_ROUTE=PASS (200)
CATALOG=PASS (200, clean render, no error strings)
APPLICATION_GATEWAY=PASS (303 redirect to /login for unauthenticated request — correct behavior, matches pre-activation proof)
SUPPORT_ROUTE=PASS (200)
POSTGRES=PASS (inferred: /api/status and /products both return real, non-error data; "Akun & Autentikasi (Core API)" reports OPERASIONAL; zero errors in container logs since startup)
REDIS=PASS (inferred: zero connection errors in logs since startup; not directly exercised via a real support-ticket POST, since Redis rate-limiting is only touched on ticket creation and no ticket was created)
SMTP_AUTH=PASS — ran the ACTUAL production code path (`_read_smtp_password()` from `app.support`, imported live inside the running container) end-to-end: EHLO + LOGIN + QUIT against smtp.hostinger.com, succeeded, no MAIL/RCPT/DATA issued, no email sent
```

Incidentally, `/api/status` surfaced that "BotConnector Connect" (the
webhook/TradingView bridge) currently reports `GANGGUAN` (disrupted) —
this is pre-existing status data about the explicitly-excluded Connect
ecosystem, unrelated to and unaffected by this activation. Not
investigated, per the standing exclusion.

### Active runtime secret check

```
ACTIVE_HOMEPAGE_CONTAINS_HARDCODED_SMTP_LITERAL=NO
ACTIVE_HOMEPAGE_USES_SMTP_PASSWORD_FILE=YES (confirmed: `docker exec ... env` shows only SMTP_PASSWORD_FILE, no plaintext SMTP_PASSWORD var at all)
NEW_SECRET_IN_IMAGE=NO (mounted at runtime via compose volumes, never COPYed into the Docker build)
NEW_SECRET_IN_SOURCE=NO
NEW_SECRET_IN_ARGV=NO
NEW_SECRET_IN_GIT=NO
NEW_SECRET_IN_LOG=NO (checked container logs since startup — clean)
```

### Scope confirmation

```
BACKEND_CORE_TOUCHED=NO (this turn — no file, container, or config under /opt/botconnector-backend-core or /opt/botconnector-core was modified; only read via docker exec for the corrected extraction above)
UNRELATED_SERVICE_RESTARTED=NO (confirmed: botconnector-backend-api, botconnector-backend-worker, botconnector-core-postgres, botconnector-core-redis, botconnector-parking-postgres all show multi-hour/multi-day uptimes, unaffected)
PRODUCTION_DATA_CHANGED=NO
USER_ACCEPTED_EXISTING_PASSWORD=YES
PASSWORD_ROTATION_REQUIRED_FOR_THIS_SCOPE=NO — the backend-core plaintext `.env` storage (and the file/runtime drift discovered above) remain a separate hardening backlog item, explicitly not a blocker for this incident's closure
```

