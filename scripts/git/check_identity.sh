#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

actual_name="$(git -C "$REPO_ROOT" config user.name || true)"
actual_email="$(git -C "$REPO_ROOT" config user.email || true)"
actual_email_lc="$(printf '%s' "$actual_email" | tr '[:upper:]' '[:lower:]')"

echo "git user.name=${actual_name:-<unset>}"
echo "git user.email=${actual_email:-<unset>}"

# This check is scoped to Cursor remote/cloud agent commits only.
# Non-Cursor commits (human, Codex, Claude CLI) pass through unchecked.
# Cursor context detected by env vars Cursor sets in its agent subprocess,
# OR by the committer name/email pattern.
is_cursor_agent() {
  [[ -n "${CURSOR_SESSION_ID:-}" || -n "${CURSOR_TRACE_ID:-}" ]] && return 0
  local name_lc="$(printf '%s' "$actual_name" | tr '[:upper:]' '[:lower:]')"
  [[ "$name_lc" == *cursor* || "$actual_email_lc" == *@cursor.com || "$actual_email_lc" == *@cursor.sh ]] && return 0
  return 1
}

if ! is_cursor_agent; then
  exit 0
fi

WELL_KNOWN_AUTHOR_DOMAIN_SUFFIXES=(
  openai.com
  anthropic.com
  cursor.com
  cursor.sh
  google.com
  google.dev
  github.com
  microsoft.com
  azure.com
  perplexity.ai
  x.ai
)

author_domain_ok() {
  local email_lc="$1"
  local domain="${email_lc#*@}"
  [[ -z "$domain" || "$domain" == "$email_lc" ]] && return 1
  local suffix
  for suffix in "${WELL_KNOWN_AUTHOR_DOMAIN_SUFFIXES[@]}"; do
    if [[ "$domain" == "$suffix" || "$domain" == *."$suffix" ]]; then
      return 0
    fi
  done
  return 1
}

if [[ -z "$actual_name" || -z "$actual_email" ]]; then
  echo "ERROR: set user.name and user.email before committing" >&2
  exit 1
fi

if [[ "$actual_email_lc" == "diazmelgarejo@gmail.com" ]]; then
  echo "OK: approved git identity"
  exit 0
fi

if [[ "$actual_email_lc" == "lawrence@cyre.me" ]]; then
  echo "OK: approved git identity"
  exit 0
fi

if [[ "$actual_name" == "Codex" && "$actual_email_lc" == "codex@openai.com" ]]; then
  echo "OK: approved AI agent git identity"
  exit 0
fi

if author_domain_ok "$actual_email_lc"; then
  echo "OK: approved well-known AI/vendor git identity"
  exit 0
fi

echo "ERROR: git identity must be one of:" >&2
echo "  - * <diazMelgarejo@gmail.com>" >&2
echo "  - * <Lawrence@cyre.me>" >&2
echo "  - Codex <codex@openai.com>" >&2
echo "  - a well-known AI/vendor domain (OpenAI, Anthropic, Cursor, Google/Gemini, GitHub/Copilot, Microsoft, Perplexity, xAI/Grok)" >&2
exit 1
