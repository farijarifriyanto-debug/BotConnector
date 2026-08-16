#!/usr/bin/env bash
set -Eeuo pipefail

echo "============================================================"
echo " BOTCONNECTOR DEV CONTAINER - POST CREATE V2"
echo "============================================================"

export PATH="$HOME/.local/bin:$PATH"
mkdir -p "$HOME/.local/bin"

echo
echo "===== UV ====="
if ! command -v uv >/dev/null 2>&1; then
    curl -LsSf https://astral.sh/uv/install.sh | sh
fi
export PATH="$HOME/.local/bin:$PATH"
uv --version

echo
echo "===== SERENA ====="
if ! command -v serena >/dev/null 2>&1; then
    uv tool install -p 3.13 "serena-agent==1.7.0"
fi
serena --version
serena init || true

echo
echo "===== SEMGREP ====="
if ! command -v semgrep >/dev/null 2>&1; then
    uv tool install "semgrep==1.173.0"
fi
semgrep --version

echo
echo "===== AST-GREP ====="
if ! command -v ast-grep >/dev/null 2>&1; then
    npm install -g --prefix "$HOME/.local" "@ast-grep/cli@0.45.1"
fi
ast-grep --version

echo
echo "===== PLAYWRIGHT CLI ====="
if ! command -v playwright-cli >/dev/null 2>&1; then
    npm install -g --prefix "$HOME/.local" "@playwright/cli@0.1.18"
fi
playwright-cli --version

echo
echo "===== RIPGREP ====="
rg --version | head -n 1

echo
echo "============================================================"
echo " POST_CREATE=PASS"
echo " NO_SUDO_USED=TRUE"
echo " NO_NEW_PRIVILEGES_PRESERVED=TRUE"
echo "============================================================"
