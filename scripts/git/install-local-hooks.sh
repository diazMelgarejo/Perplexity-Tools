#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

cd "$REPO_ROOT"

if ! git rev-parse --git-dir >/dev/null 2>&1; then
  echo "ERROR: not a git repository: $REPO_ROOT" >&2
  exit 1
fi

hooks_dir="$REPO_ROOT/.githooks"
mkdir -p "$hooks_dir"

for hook in pre-commit commit-msg; do
  src="$hooks_dir/$hook"
  if [[ ! -f "$src" ]]; then
    echo "ERROR: missing $src (expected tracked hook in .githooks/)" >&2
    exit 1
  fi
  chmod +x "$src"
done

chmod +x "$REPO_ROOT/scripts/git/check_identity.sh" 2>/dev/null || true
chmod +x "$REPO_ROOT/scripts/git/check_commit_message.sh" 2>/dev/null || true

git config --local core.hooksPath .githooks
echo "OK: core.hooksPath=$(git config --local --get core.hooksPath)"
echo "Run: git config --local user.name && git config --local user.email"
echo "Hooks: pre-commit (identity), commit-msg (forbidden Co-authored-by)"
