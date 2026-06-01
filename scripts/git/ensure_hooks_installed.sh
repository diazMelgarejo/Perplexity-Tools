#!/usr/bin/env bash
# Non-negotiable: repo-local hooks must be active before any commit.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

cd "$REPO_ROOT"

if ! git rev-parse --git-dir >/dev/null 2>&1; then
  echo "ERROR: not a git repository: $REPO_ROOT" >&2
  exit 1
fi

hooks_path="$(git config --local --get core.hooksPath 2>/dev/null || true)"
if [[ "$hooks_path" != ".githooks" ]]; then
  echo "ERROR: core.hooksPath=${hooks_path:-<unset>} — expected .githooks" >&2
  echo "Run: bash scripts/git/install-local-hooks.sh" >&2
  exit 1
fi

for hook in pre-commit commit-msg; do
  path="$REPO_ROOT/.githooks/$hook"
  if [[ ! -f "$path" || ! -x "$path" ]]; then
    echo "ERROR: missing or non-executable $path" >&2
    echo "Run: bash scripts/git/install-local-hooks.sh" >&2
    exit 1
  fi
done

exit 0
