#!/usr/bin/env bash
# Rewrite all refs to remove banned Co-authored-by lines from commit messages (history expunge).
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
if [[ -n "${1:-}" && -d "${1}/.git" ]]; then
  REPO_ROOT="$(cd "$1" && pwd)"
else
  REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
fi
FILTER="$SCRIPT_DIR/filter-msg-strip-banned.sh"
# shellcheck source=banned_attribution_lib.sh
source "$SCRIPT_DIR/banned_attribution_lib.sh"

cd "$REPO_ROOT"

if [[ -x scripts/cursor/sync-private-attribution-from-home.sh ]]; then
  bash scripts/cursor/sync-private-attribution-from-home.sh
fi

if ! banned_patterns_ready "$REPO_ROOT"; then
  echo "ERROR: .cursor/private/banned-attribution-patterns missing" >&2
  exit 1
fi

chmod +x "$FILTER"

echo "Rewriting commit messages (all refs) to strip banned Co-authored-by trailers…"
export FILTER_BRANCH_SQUELCH_WARNING=1
git filter-branch -f --msg-filter "REPO_ROOT='$REPO_ROOT' bash '$FILTER'" --tag-name-filter cat -- --all

git for-each-ref --format='%(refname)' refs/original/ 2>/dev/null | while read -r ref; do
  git update-ref -d "$ref" 2>/dev/null || true
done

git reflog expire --expire=now --all
git gc --prune=now --aggressive

while IFS= read -r h; do
  while IFS= read -r line; do
    line_lc="$(printf '%s' "$line" | tr '[:upper:]' '[:lower:]')"
    case "$line_lc" in
      co-authored-by:*)
        if line_matches_banned_pattern "$line_lc" "$REPO_ROOT"; then
          echo "FAIL: banned Co-authored-by still on $h" >&2
          exit 1
        fi
        ;;
    esac
  done < <(git log -1 --format=%B "$h")
done < <(git rev-list --all)
echo "OK: no banned Co-authored-by trailers remain in any reachable commit message"
