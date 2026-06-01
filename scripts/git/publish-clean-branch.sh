#!/usr/bin/env bash
# Verify branch attribution/hygiene, then force-publish to origin (clean history only).
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
# shellcheck source=banned_attribution_lib.sh
source "$SCRIPT_DIR/banned_attribution_lib.sh"

cd "$REPO_ROOT"

branch="${1:-$(git branch --show-current)}"
base="${2:-main}"
remote="${3:-origin}"

if ! git rev-parse --verify "$branch" >/dev/null 2>&1; then
  echo "ERROR: branch not found: $branch" >&2
  exit 1
fi

git fetch "$remote" "$base" "$branch" 2>/dev/null || git fetch "$remote"

if ! git config --local user.email >/dev/null; then
  git config --local user.name "cyre"
  git config --local user.email "Lawrence@cyre.me"
fi

if [[ -x scripts/cursor/write-cursor-private-attribution.sh ]]; then
  bash scripts/cursor/write-cursor-private-attribution.sh
fi

if [[ -x scripts/git/install-local-hooks.sh ]]; then
  bash scripts/git/install-local-hooks.sh
fi

if [[ -x scripts/git/verify-git-guards.sh ]]; then
  bash scripts/git/verify-git-guards.sh
fi

if command -v python3 >/dev/null 2>&1 && [[ -f scripts/review/repo_hygiene.py ]]; then
  python3 scripts/review/repo_hygiene.py .
fi

if [[ -x scripts/git/scan-tracked-banned-tokens.sh ]]; then
  bash scripts/git/scan-tracked-banned-tokens.sh
fi

range="${remote}/${base}..${branch}"
if ! git rev-parse --verify "${remote}/${base}" >/dev/null 2>&1; then
  range="${base}..${branch}"
fi

export GIT_AUDIT_RANGE="$range"
export GIT_AUDIT_STRICT=1
bash scripts/git/audit_attribution.sh

if ! banned_patterns_ready "$REPO_ROOT"; then
  echo "ERROR: banned pattern file missing" >&2
  exit 1
fi

while read -r h; do
  ae="$(git log -1 --format=%ae "$h")"
  ce="$(git log -1 --format=%ce "$h")"
  ae_lc="$(printf '%s' "$ae" | tr '[:upper:]' '[:lower:]')"
  ce_lc="$(printf '%s' "$ce" | tr '[:upper:]' '[:lower:]')"
  if [[ "$ae_lc" == "cursoragent@cursor.com" || "$ce_lc" == "cursoragent@cursor.com" ]]; then
    echo "ERROR: Cursor Agent author/committer on $h" >&2
    exit 1
  fi
  body_lc="$(git log -1 --format=%B "$h" | tr '[:upper:]' '[:lower:]')"
  while IFS= read -r line; do
    line_lc="$(printf '%s' "$line" | tr '[:upper:]' '[:lower:]')"
    case "$line_lc" in
      co-authored-by:*)
        if line_matches_banned_pattern "$line_lc" "$REPO_ROOT"; then
          echo "ERROR: banned Co-authored-by on $h" >&2
          exit 1
        fi
        ;;
    esac
  done <<< "$body_lc"
  if line_matches_banned_pattern "$ae_lc" "$REPO_ROOT" \
    || line_matches_banned_pattern "$ce_lc" "$REPO_ROOT"; then
    echo "ERROR: banned author/committer on $h" >&2
    exit 1
  fi
done < <(git rev-list "$range")

echo "OK: ${range} passes attribution scan — force-pushing ${branch} → ${remote}"
git push --force-with-lease "$remote" "${branch}:${branch}"

echo "OK: published $(git rev-parse --short "$branch") to ${remote}/${branch}"
