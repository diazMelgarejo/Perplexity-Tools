#!/usr/bin/env bash
# Primary commit author policy — non-negotiable, always enforced (matches repo_hygiene.py).
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
# shellcheck source=banned_attribution_lib.sh
source "$SCRIPT_DIR/banned_attribution_lib.sh"

actual_name="$(git -C "$REPO_ROOT" config user.name || true)"
actual_email="$(git -C "$REPO_ROOT" config user.email || true)"
actual_email_lc="$(printf '%s' "$actual_email" | tr '[:upper:]' '[:lower:]')"
actual_name_lc="$(printf '%s' "$actual_name" | tr '[:upper:]' '[:lower:]')"

echo "git user.name=${actual_name:-<unset>}"
echo "git user.email=${actual_email:-<unset>}"

if [[ -z "$actual_name" || -z "$actual_email" ]]; then
  echo "ERROR: set user.name and user.email before committing" >&2
  echo "  git config user.name \"cyre\"" >&2
  echo "  git config user.email \"Lawrence@cyre.me\"  # or diazMelgarejo@gmail.com" >&2
  exit 1
fi

if ! banned_patterns_ready "$REPO_ROOT"; then
  echo "ERROR: missing .cursor/private/banned-attribution-patterns" >&2
  echo "Run: bash scripts/cursor/install-user-git-environment.sh" >&2
  exit 1
fi
if line_matches_banned_pattern "$actual_email_lc" "$REPO_ROOT" \
  || line_matches_banned_pattern "$actual_name_lc" "$REPO_ROOT"; then
  echo "ERROR: banned git identity (see .cursor/private/banned-attribution-patterns)" >&2
  exit 1
fi

# Cursor Agent must not be primary author (Co-authored-by only, via strip hook + policy).
if [[ "$actual_email_lc" == "cursoragent@cursor.com" ]] \
  || [[ "$actual_name_lc" == "cursor agent" ]] \
  || [[ "$actual_name_lc" == *"cursor agent"* ]]; then
  echo "ERROR: Cursor Agent must not be the git author" >&2
  echo "  git config user.name \"cyre\"" >&2
  echo "  git config user.email \"Lawrence@cyre.me\"" >&2
  echo "  bash scripts/git/install-local-hooks.sh" >&2
  exit 1
fi

identity_ok() {
  case "$actual_email_lc" in
    diazmelgarejo@gmail.com | lawrence@cyre.me)
      return 0
      ;;
    codex@openai.com)
      [[ "$actual_name" == "Codex" ]]
      return $?
      ;;
  esac
  return 1
}

if identity_ok; then
  echo "OK: approved git identity"
  exit 0
fi

echo "ERROR: git identity must be one of:" >&2
echo "  - cyre <diazMelgarejo@gmail.com>" >&2
echo "  - cyre <Lawrence@cyre.me>" >&2
echo "  - Codex <codex@openai.com>" >&2
exit 1
