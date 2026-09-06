# Homepage Runtime Canonical Cutover — 2026-09-06

Executed. Live `botconnector-platform-home` now runs from canonical
source. No other system touched.

```
CANONICAL_COMMIT=348f3f2c58daa7c563d38bac0f7299332acdf498
IMAGE_TAG=botconnector-platform-home:348f3f2-20260906T094839Z
IMAGE_DIGEST=sha256:9229019695e04184513350bd86750f90006949fd6cfcd66ccd81f107fce2a946

OLD_CONTAINER_ID=a55f9984898f188abe0a4e6ea5f83b907a59bfea7c78f01194b3bcc96b16863e
OLD_IMAGE=botconnector-platform-home:tenantization-v1-20260828 (sha256:80682abba1de7048751533291d6bb8f8c21d447ce9fed138b736af1b560f1f69) — RETAINED locally, not deleted

COMPOSE_CHANGE=one line (`image:`) in /opt/botconnector-platform-starter-v0.3/homepage/docker-compose.yml
COMPOSE_BACKUP=/home/botadmin/backups/security-incidents/smtp-credential-20260906/homepage-docker-compose.yml.pre-canonical-cutover-backup
```

## Acceptance (all PASS)

```
HEALTH=PASS ({"ok":true,"service":"botconnector-platform-home",...}, Docker healthcheck "healthy")
LOGIN=PASS (200)
REGISTER=PASS (200)
CATALOG=PASS (200, clean render, no errors)
GATEWAY=PASS (303 → /login for unauthenticated request, correct)
SUPPORT=PASS (200)
POSTGRES=PASS (inferred: clean catalog render, zero errors in logs since restart)
REDIS=PASS (inferred: zero errors in logs since restart)
SMTP=PASS (real production code path — EHLO+LOGIN+QUIT against smtp.hostinger.com inside the running container, no email sent)
LIVE_SOURCE_CANONICAL=YES (image built directly from apps/homepage-runtime, no /opt source in the build)
```

## Scope confirmation

```
NGINX_CHANGED=NO (config file hash unchanged, nginx ActiveEnterTimestamp unchanged — service not reloaded/restarted)
DATA_PRESERVED=YES (/var/lib/botconnector-platform/presentation-projects.sqlite3 and staging-control.json confirmed intact, unchanged timestamps)
BACKEND_CORE_TOUCHED=NO (botconnector-backend-api, botconnector-backend-worker: unaffected, multi-hour uptime confirmed)
POSTGRES_REDIS_RESTARTED=NO (botconnector-core-postgres, botconnector-core-redis, botconnector-parking-postgres: unaffected, multi-hour/day uptime confirmed)
ROLLBACK_EXECUTED=NO (not needed — all acceptance checks passed)
```

## Rollback (not used, documented for reference)

```
docker tag sha256:80682abba1de7048751533291d6bb8f8c21d447ce9fed138b736af1b560f1f69 botconnector-platform-home:tenantization-v1-20260828
# then revert the compose file's image: line (see COMPOSE_BACKUP above) and:
cd /opt/botconnector-platform-starter-v0.3/homepage && docker compose up -d --no-deps --no-build botconnector-home
```
