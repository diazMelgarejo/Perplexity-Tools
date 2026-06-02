#!/usr/bin/env bash
# git filter-branch --msg-filter helper: drop banned Co-authored-by trailers only.
set -euo pipefail

REPO_ROOT="${REPO_ROOT:-$(git rev-parse --show-toplevel 2>/dev/null || pwd)}"
PT_GUARD="${PERPETUA_TOOLS_GUARD:-/agent/repos/Perpetua-Tools}"
if [[ -f "$REPO_ROOT/scripts/git/banned_attribution_lib.sh" ]]; then
  # shellcheck source=banned_attribution_lib.sh
  source "$REPO_ROOT/scripts/git/banned_attribution_lib.sh"
elif [[ -f "$PT_GUARD/scripts/git/banned_attribution_lib.sh" ]]; then
  # shellcheck source=banned_attribution_lib.sh
  source "$PT_GUARD/scripts/git/banned_attribution_lib.sh"
else
  echo "error: banned_attribution_lib.sh not found" >&2
  exit 1
fi

while IFS= read -r line || [[ -n "$line" ]]; do
  line_lc="$(printf '%s' "$line" | tr '[:upper:]' '[:lower:]')"
  case "$line_lc" in
    co-authored-by:*)
      if line_matches_banned_pattern "$line_lc" "$REPO_ROOT"; then
        continue
      fi
      ;;
  esac
  printf '%s\n' "$line"
done
