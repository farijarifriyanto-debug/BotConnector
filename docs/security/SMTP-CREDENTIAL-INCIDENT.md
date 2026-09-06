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
