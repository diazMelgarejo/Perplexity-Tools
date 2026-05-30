#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

actual_name="$(git -C "$REPO_ROOT" config user.name || true)"
actual_email="$(git -C "$REPO_ROOT" config user.email || true)"
actual_email_lc="$(printf '%s' "$actual_email" | tr '[:upper:]' '[:lower:]')"

echo "git user.name=${actual_name:-<unset>}"
echo "git user.email=${actual_email:-<unset>}"

# Detect if this commit is coming from a Cursor remote/cloud agent.
# Trigger: CURSOR_SESSION_ID or CURSOR_TRACE_ID env var is set,
#          OR the committer name/email signals Cursor.
is_cursor_agent() {
  [[ -n "${CURSOR_SESSION_ID:-}" || -n "${CURSOR_TRACE_ID:-}" ]] && return 0
  local name_lc email_lc
  name_lc="$(printf '%s' "$actual_name" | tr '[:upper:]' '[:lower:]')"
  email_lc="$actual_email_lc"
  [[ "$name_lc" == *cursor* || "$email_lc" == *@cursor.com || "$email_lc" == *@cursor.sh ]] && return 0
  return 1
}

# When a Cursor agent is committing, enforce strict Cursor-specific allowlist
# and exit immediately (no fall-through to the general policy below).
if is_cursor_agent; then
  case "$actual_email_lc" in
    cursoragent@cursor.com|noreply@cursor.com)
      echo "OK: approved Cursor agent identity"
      exit 0
      ;;
    *)
      echo "ERROR: Cursor agent email not on allowlist: $actual_email" >&2
      echo "  Allowed Cursor identities: cursoragent@cursor.com, noreply@cursor.com" >&2
      echo "  Set: git config user.email cursoragent@cursor.com" >&2
      exit 1
      ;;
  esac
fi

WELL_KNOWN_AUTHOR_DOMAIN_SUFFIXES=(
  openai.com
  anthropic.com
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
