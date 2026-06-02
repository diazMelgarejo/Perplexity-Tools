#!/usr/bin/env bash
# Run at session start (and optionally cron): neutralize injection, scan, expunge if needed, verify hooks.
# Idempotent: expunge runs only when banned co-author hits > 0.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
WORKSPACE_ROOT="${WORKSPACE_ROOT:-/agent/repos}"
LOG="${HOME:-}/.cursor/openclaw/attribution-guard.log"

mkdir -p "${HOME:-}/.cursor/openclaw"
{
  echo "=== $(date -u +%Y-%m-%dT%H:%M:%SZ) daily-attribution-guard ==="
} >>"$LOG"

if [[ -x "$PT_ROOT/scripts/cursor/install-user-git-environment.sh" ]]; then
  bash "$PT_ROOT/scripts/cursor/install-user-git-environment.sh" >>"$LOG" 2>&1 || true
fi

if [[ -x "$SCRIPT_DIR/neutralize-cursor-coauthor-hook.sh" ]]; then
  bash "$SCRIPT_DIR/neutralize-cursor-coauthor-hook.sh" --all-agent-hooks >>"$LOG" 2>&1 || true
fi

# shellcheck source=banned_attribution_lib.sh
source "$PT_ROOT/scripts/git/banned_attribution_lib.sh"
total_hits=0
for repo in "$WORKSPACE_ROOT"/*; do
  [[ -d "$repo/.git" ]] || continue
  bash "$SCRIPT_DIR/sync-banned-patterns-to-repo.sh" "$repo" >>"$LOG" 2>&1 || true
  if [[ -x "$repo/scripts/git/install-local-hooks.sh" ]]; then
    bash "$repo/scripts/git/install-local-hooks.sh" >>"$LOG" 2>&1 || true
  elif [[ "$repo" != "$PT_ROOT" && -x "$PT_ROOT/scripts/git/install-local-hooks.sh" ]]; then
    (cd "$repo" && git config --local core.hooksPath .githooks 2>/dev/null) || true
  fi
  hits=0
  h_line=""
  while IFS= read -r h; do
    while IFS= read -r line; do
      line_lc="$(printf '%s' "$line" | tr '[:upper:]' '[:lower:]')"
      case "$line_lc" in
        co-authored-by:*)
          if line_matches_banned_pattern "$line_lc" "$repo"; then
            hits=$((hits + 1))
          fi
          ;;
      esac
    done < <(git -C "$repo" log -1 --format=%B "$h" 2>/dev/null)
  done < <(git -C "$repo" rev-list --all 2>/dev/null)
  total_hits=$((total_hits + hits))
  echo "scan $(basename "$repo") hits=$hits" >>"$LOG"
done

if [[ "$total_hits" -gt 0 ]]; then
  echo "ALERT: banned co-author hits=$total_hits — running workspace expunge" >>"$LOG"
  bash "$SCRIPT_DIR/expunge-all-workspace-repos.sh" >>"$LOG" 2>&1
else
  echo "scan clean — no expunge required" >>"$LOG"
fi

if [[ -x "$PT_ROOT/scripts/git/verify-git-guards.sh" ]]; then
  bash "$PT_ROOT/scripts/git/verify-git-guards.sh" >>"$LOG" 2>&1 || true
fi

echo "daily-attribution-guard complete (log: $LOG)"
