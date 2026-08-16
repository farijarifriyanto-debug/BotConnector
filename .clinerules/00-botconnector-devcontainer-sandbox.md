# BotConnector Dev Container Sandbox

## Scope
- Treat this Linux Dev Container as the default sandbox for code search, repository analysis, Node/web work, cross-platform tests, static analysis, and ordinary terminal commands.
- Keep all repository edits inside the currently opened BotConnector workspace.
- Do not mount or request the Docker daemon socket from this container.
- Do not read or modify Windows host paths outside the mounted workspace unless the user explicitly approves that specific action.
- Never place API keys, credentials, SSH private keys, or provider secrets in repository files.

## Tool routing
- Exact text/regex search: `rg`.
- Structural syntax search/rewrite: `ast-grep`.
- Symbol/reference intelligence: Serena.
- Current library documentation: Context7 MCP.
- Static/security verification: Semgrep.
- Browser/UI verification: `playwright-cli` when a browser is installed for the task.

## Windows desktop boundary
- The repository contains Windows-targeted WPF code.
- The Linux Dev Container may be used for source analysis and cross-platform checks, but do not claim a final WPF build/runtime acceptance from Linux.
- Final WPF build, Windows integration, installer, registry-sensitive behavior, Windows UI behavior, and Windows security checks must run on the Windows host through the approved BotConnector Windows execution policy.

## Change discipline
- Before broad edits, inspect the repository and current Git status.
- Prefer narrow changes.
- Run the narrowest relevant tests first.
- Review `git diff` before declaring a change complete.
- For security-sensitive or broad edits, run Semgrep when relevant.
- Do not alter production/VPS services as part of a local repository task unless the user explicitly requests it.