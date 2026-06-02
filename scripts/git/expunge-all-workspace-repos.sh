#!/usr/bin/env bash
# Expunge banned Co-authored-by trailers from every repo under a workspace root, then force-push all branches.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
WORKSPACE_ROOT="${WORKSPACE_ROOT:-/agent/repos}"
EXPUNGE="$SCRIPT_DIR/expunge-banned-attribution-history.sh"
SYNC="$SCRIPT_DIR/sync-banned-patterns-to-repo.sh"
PUSH_ALL="${PUSH_ALL:-1}"

HOME="${HOME:-/home/ubuntu}"
export HOME PERPETUA_TOOLS_GUARD="$PT_ROOT"

if [[ -x "${ORAMA_SYSTEM_PATH:-}/scripts/cursor/write-openclaw-private-attribution.sh" ]]; then
  bash "${ORAMA_SYSTEM_PATH}/scripts/cursor/write-openclaw-private-attribution.sh"
elif [[ -x /agent/repos/orama-system/scripts/cursor/write-openclaw-private-attribution.sh ]]; then
  bash /agent/repos/orama-system/scripts/cursor/write-openclaw-private-attribution.sh
fi

if [[ -x "$PT_ROOT/scripts/git/neutralize-cursor-coauthor-hook.sh" ]]; then
  bash "$PT_ROOT/scripts/git/neutralize-cursor-coauthor-hook.sh" --all-agent-hooks
fi

scan_repo_hits() {
  local repo="$1"
  # shellcheck source=banned_attribution_lib.sh
  source "$PT_ROOT/scripts/git/banned_attribution_lib.sh"
  local hits=0 h line line_lc
  while IFS= read -r h; do
    while IFS= read -r line; do
      line_lc="$(printf '%s' "$line" | tr '[:upper:]' '[:lower:]')"
      case "$line_lc" in
        co-authored-by:*)
          line_matches_banned_pattern "$line_lc" "$repo" && hits=$((hits + 1))
          ;;
      esac
    done < <(git -C "$repo" log -1 --format=%B "$h")
  done < <(git -C "$repo" rev-list --all 2>/dev/null)
  printf '%s' "$hits"
}

force_push_repo() {
  local repo="$1"
  git -C "$repo" remote get-url origin >/dev/null 2>&1 || return 0
  local branch
  while IFS= read -r branch; do
    [[ -n "$branch" ]] || continue
    git -C "$repo" push --force-with-lease origin "${branch}:${branch}" 2>/dev/null \
      || git -C "$repo" push --force origin "${branch}:${branch}" 2>/dev/null \
      || echo "warn: push failed ${branch} in $(basename "$repo")" >&2
  done < <(git -C "$repo" for-each-ref refs/heads --format='%(refname:short)')
}

expunge_repo() {
  local repo="$1"
  local name
  name="$(basename "$repo")"
  [[ -d "${repo}/.git" ]] || return 0

  echo ">>> [$name] fetch"
  git -C "$repo" fetch origin --prune 2>/dev/null || true

  bash "$SYNC" "$repo"

  local before after
  before="$(scan_repo_hits "$repo")"
  echo ">>> [$name] banned co-author hits before expunge: $before"
  if [[ "$before" -eq 0 ]]; then
    echo ">>> [$name] clean — skip history rewrite and force-push"
    return 0
  fi

  echo ">>> [$name] filter-branch (all refs)"
  if ! git -C "$repo" diff-index --quiet HEAD -- 2>/dev/null \
    || ! git -C "$repo" diff-index --quiet --cached HEAD -- 2>/dev/null; then
    git -C "$repo" stash push -u -m "attribution-expunge-autostash" >/dev/null 2>&1 || true
    stashed=1
  else
    stashed=0
  fi
  bash "$EXPUNGE" "$repo"
  if [[ "${stashed:-0}" == "1" ]]; then
    git -C "$repo" stash pop >/dev/null 2>&1 || true
  fi

  after="$(scan_repo_hits "$repo")"
  echo ">>> [$name] banned co-author hits after expunge: $after"
  if [[ "$after" -ne 0 ]]; then
    echo "ERROR: [$name] still has banned trailers after expunge" >&2
    return 1
  fi

  if [[ "$PUSH_ALL" == "1" ]]; then
    echo ">>> [$name] force-push all local branches"
    force_push_repo "$repo"
  fi
  echo ">>> [$name] OK"
}

shopt -s nullglob
repos=("$WORKSPACE_ROOT"/*)
if [[ ! -d "$WORKSPACE_ROOT" ]]; then
  echo "ERROR: workspace root not found: $WORKSPACE_ROOT" >&2
  exit 1
fi

failed=0
for repo in "${repos[@]}"; do
  [[ -d "$repo/.git" ]] || continue
  expunge_repo "$repo" || failed=$((failed + 1))
done

if [[ "$failed" -gt 0 ]]; then
  echo "expunge-all-workspace-repos: $failed repo(s) failed" >&2
  exit 1
fi
echo "OK: workspace expunge complete (${#repos[@]} roots scanned)"
