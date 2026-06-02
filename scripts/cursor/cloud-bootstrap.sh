#!/usr/bin/env bash
# Cursor Cloud Agent install hook (see .cursor/environment.json).
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$REPO_ROOT"

printf '>>> [cloud-bootstrap] Perpetua-Tools %s\n' "$(git rev-parse --short HEAD 2>/dev/null || echo unknown)"

export PERPETUA_TOOLS_PATH="${PERPETUA_TOOLS_PATH:-$REPO_ROOT}"
export REPO_ROOT="$REPO_ROOT"
export ORAMA_SYSTEM_PATH="${ORAMA_SYSTEM_PATH:-$REPO_ROOT/../orama-system}"

if [[ -x scripts/cursor/ci-bootstrap-private-attribution.sh ]]; then
  bash scripts/cursor/ci-bootstrap-private-attribution.sh
fi

if [[ -x scripts/cursor/install-user-git-environment.sh ]]; then
  bash scripts/cursor/install-user-git-environment.sh
fi

if [[ -x scripts/git/neutralize-cursor-coauthor-hook.sh ]]; then
  bash scripts/git/neutralize-cursor-coauthor-hook.sh --all-agent-hooks
fi

# Do not run daily-attribution-guard here: it scans full history and may rewrite repos.
# verify-git-guards + neutralize hooks are sufficient for cloud VM bootstrap.

git config --local user.name "cyre" 2>/dev/null || true
git config --local user.email "Lawrence@cyre.me" 2>/dev/null || true

if [[ -x scripts/git/install-local-hooks.sh ]]; then
  bash scripts/git/install-local-hooks.sh
fi

if [[ -x scripts/git/verify-git-guards.sh ]]; then
  bash scripts/git/verify-git-guards.sh
fi

if [[ -x scripts/git/scan-tracked-banned-tokens.sh ]]; then
  bash scripts/git/scan-tracked-banned-tokens.sh
fi

printf '>>> [cloud-bootstrap] complete\n'
