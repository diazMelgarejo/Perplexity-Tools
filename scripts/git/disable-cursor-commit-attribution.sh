#!/usr/bin/env bash
# Disable Cursor cloud-agent automatic Co-authored-by injection for one git repo.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=cursor-hooks-id.sh
source "$SCRIPT_DIR/cursor-hooks-id.sh"

repo="${1:-.}"
repo="$(cd "$repo" && pwd)"

if ! git -C "$repo" rev-parse --git-dir >/dev/null 2>&1; then
  echo "skip: not a git repo: $repo" >&2
  exit 0
fi

git_dir="$(git -C "$repo" rev-parse --git-dir)"
hooks_dir="$(cd "$git_dir" && pwd)/hooks"
mkdir -p "$hooks_dir"

# 1) Disable Cursor-managed co-author hook (keeps other Cursor commit-msg hooks).
ws_id="$(cursor_hooks_id "$repo")"
coauthor_hook="${HOME}/.cursor/agent-hooks/${ws_id}/commit-msg.cursor.co-author"
if [[ -f "$coauthor_hook" ]]; then
  chmod -x "$coauthor_hook" 2>/dev/null || true
  echo "disabled: $coauthor_hook"
fi

# 2) Keep mandatory hooks on .githooks (strip runs inside .githooks/commit-msg).
git -C "$repo" config --local core.hooksPath .githooks

# 3) Prefer approved cyre identity when unset locally.
if [[ -z "$(git -C "$repo" config --local user.name 2>/dev/null || true)" ]]; then
  git -C "$repo" config --local user.name "cyre"
fi
if [[ -z "$(git -C "$repo" config --local user.email 2>/dev/null || true)" ]]; then
  git -C "$repo" config --local user.email "diazMelgarejo@gmail.com"
fi

echo "OK: attribution guards applied in $repo"
