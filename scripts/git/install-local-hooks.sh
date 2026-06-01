#!/usr/bin/env bash
# Install mandatory repo-local git hooks (non-negotiable for all commits in this repo).
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

if [[ -n "${1:-}" && -d "${1}/.git" ]]; then
  REPO_ROOT="$(cd "$1" && pwd)"
fi

cd "$REPO_ROOT"

if ! git rev-parse --git-dir >/dev/null 2>&1; then
  echo "ERROR: not a git repository: $REPO_ROOT" >&2
  exit 1
fi

hooks_dir="$REPO_ROOT/.githooks"
mkdir -p "$hooks_dir" "$REPO_ROOT/scripts/git/hooks"

for hook in pre-commit commit-msg pre-push; do
  src="$hooks_dir/$hook"
  if [[ ! -f "$src" ]]; then
    echo "ERROR: missing $src (expected tracked hook in .githooks/)" >&2
    exit 1
  fi
  chmod +x "$src"
done

chmod +x "$REPO_ROOT/scripts/git/check_identity.sh" 2>/dev/null || true
chmod +x "$REPO_ROOT/scripts/git/check_commit_message.sh" 2>/dev/null || true
chmod +x "$REPO_ROOT/scripts/git/ensure_hooks_installed.sh" 2>/dev/null || true
chmod +x "$REPO_ROOT/scripts/git/verify-git-guards.sh" 2>/dev/null || true
chmod +x "$REPO_ROOT/scripts/git/hooks/commit-msg.strip-coauthor" 2>/dev/null || true

# Disable Cursor cloud co-author injection; keep core.hooksPath on .githooks.
if [[ -x "$SCRIPT_DIR/disable-cursor-commit-attribution.sh" ]]; then
  bash "$SCRIPT_DIR/disable-cursor-commit-attribution.sh" "$REPO_ROOT"
fi

git config --local core.hooksPath .githooks

if ! bash "$REPO_ROOT/scripts/git/ensure_hooks_installed.sh"; then
  echo "ERROR: hook installation verification failed" >&2
  exit 1
fi

echo "OK: mandatory hooks active — core.hooksPath=$(git config --local --get core.hooksPath)"
echo "Approved authors: cyre <Lawrence@cyre.me|diazMelgarejo@gmail.com>, Codex <codex@openai.com>"
echo "Hooks: pre-commit (identity), commit-msg (strip + policy), pre-push (block banned trailers on push)"
echo "Verify: bash scripts/git/verify-git-guards.sh"
