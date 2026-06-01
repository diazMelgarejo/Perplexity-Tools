#!/usr/bin/env bash
# Verify mandatory repo git guards (hooks, identity, commit-msg policy).
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
# shellcheck source=banned_attribution_lib.sh
source "$SCRIPT_DIR/banned_attribution_lib.sh"
HOME="${HOME:-/home/ubuntu}"
errors=0

fail() {
  echo "FAIL: $*" >&2
  errors=$((errors + 1))
}

ok() {
  echo "OK: $*"
}

cd "$REPO_ROOT"

if [[ -x scripts/cursor/write-cursor-private-attribution.sh ]]; then
  bash scripts/cursor/write-cursor-private-attribution.sh >/dev/null
fi

if ! bash "$REPO_ROOT/scripts/git/ensure_hooks_installed.sh" >/dev/null 2>&1; then
  fail "repo hooks not installed (bash scripts/git/install-local-hooks.sh)"
else
  ok "repo hooks installed (.githooks)"
fi

session_hook="${HOME}/.cursor/openclaw/hooks/session-apply-git-guards.sh"
if [[ ! -x "$session_hook" ]]; then
  fail "Cursor sessionStart hook missing (bash scripts/cursor/install-user-git-environment.sh)"
else
  ok "Cursor sessionStart hook installed"
fi

if [[ ! -f "${HOME}/.cursor/hooks.json" ]]; then
  fail "missing ${HOME}/.cursor/hooks.json"
else
  ok "Cursor hooks.json present"
fi

email_lc="$(git config --local user.email 2>/dev/null | tr '[:upper:]' '[:lower:]' || true)"
case "$email_lc" in
  diazmelgarejo@gmail.com | lawrence@cyre.me | codex@openai.com)
    ok "user.email=${email_lc}"
    ;;
  *)
    fail "user.email=${email_lc:-<unset>} — expected cyre gmail/cyre.me or Codex"
    ;;
esac

if ! bash "$REPO_ROOT/scripts/git/check_identity.sh" >/dev/null 2>&1; then
  fail "check_identity.sh rejected current git identity"
else
  ok "check_identity.sh passed"
fi

if [[ -f "$REPO_ROOT/scripts/git/cursor-hooks-id.sh" ]]; then
  # shellcheck disable=SC1091
  source "$REPO_ROOT/scripts/git/cursor-hooks-id.sh"
  ws_id="$(cursor_hooks_id "$REPO_ROOT")"
  coauthor="${HOME}/.cursor/agent-hooks/${ws_id}/commit-msg.cursor.co-author"
  if [[ -f "$coauthor" && -x "$coauthor" ]]; then
    fail "Cursor co-author hook still executable: $coauthor"
  else
    ok "Cursor co-author injection hook disabled or absent"
  fi
fi

fixture_token="$(list_banned_pattern_tokens "$REPO_ROOT" | head -n1)"
if [[ -z "$fixture_token" ]]; then
  fail "banned pattern file empty"
else
  tmp="$(mktemp)"
  trap 'rm -f "$tmp"' EXIT
  printf 'test: verify guards\n\nCo-authored-by: X <%s@example.invalid>\n' "$fixture_token" >"$tmp"
  if bash "$REPO_ROOT/scripts/git/check_commit_message.sh" "$tmp" 2>/dev/null; then
    fail "check_commit_message.sh should reject banned co-author fixture"
  else
    ok "commit-msg policy blocks banned co-author fixture"
  fi
fi

tmp="$(mktemp)"
trap 'rm -f "$tmp"' EXIT
cat >"$tmp" <<'MSG'
test: verify guards

Co-authored-by: Random <unknown-person@random-domain-xyz.io>
MSG
if bash "$REPO_ROOT/scripts/git/check_commit_message.sh" "$tmp" 2>/dev/null; then
  fail "check_commit_message.sh should reject unlisted co-author"
else
  ok "commit-msg policy blocks unlisted co-author"
fi

if [[ -x scripts/git/scan-tracked-banned-tokens.sh ]]; then
  if bash scripts/git/scan-tracked-banned-tokens.sh >/dev/null 2>&1; then
    ok "tracked files contain no banned tokens"
  else
    fail "banned token found in tracked files"
  fi
fi

if [[ "$errors" -gt 0 ]]; then
  echo "verify-git-guards: $errors failure(s)" >&2
  exit 1
fi
echo "verify-git-guards: all checks passed"
