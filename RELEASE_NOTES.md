# BotConnector AI 0.5.0-beta1

First public npm beta candidate for BotConnector AI.

## Highlights

- Native `botconnector` CLI with a shared local model/runtime core.
- Local GGUF discovery, download, runtime management, chat, embeddings, and API access.
- Auto model/backend selection, with optional explicit cloud model routing.
- Interactive TUI commands for `/model`, `/skills`, `/mcp`, `/diff`, `/review`, and `/launch`.
- Local Web Agent Workspace via `botconnector ui` and headless `botconnector serve`.
- Launch adapters for Claude Code, Codex CLI, OpenCode, and supported editors when installed.
- Localhost-only defaults and explicit credential boundaries.

## Beta boundaries

- The npm package installs the CLI and Web Agent Workspace; model weights and managed runtimes are downloaded separately into the user's existing BotConnector data locations.
- Cloud routing is an opt-in private-preview path. There is no public billing plan in this beta.
- Integration availability depends on the target tool being installed and discoverable on `PATH`.
- The executable remains `botconnector` even though the npm package is published as `botconnector-ai`.

## Install

```bash
npm install --global botconnector-ai@0.5.0-beta1
botconnector --version
```

The final release command is intentionally not included here until the npm account and publisher ownership gate is complete.
