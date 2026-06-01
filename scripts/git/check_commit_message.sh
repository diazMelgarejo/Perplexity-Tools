#!/usr/bin/env bash
# Co-authored-by policy: allow well-known public AI/helper attribution; block
# unattributable random @gmail.com co-authors (see docs/wiki/08-git-hygiene-and-branching.md).
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
# shellcheck source=banned_attribution_lib.sh
source "$SCRIPT_DIR/banned_attribution_lib.sh"

msg_file="${1:?commit message file required}"
[[ -f "$msg_file" ]] || { echo "ERROR: missing commit message file: $msg_file" >&2; exit 1; }

# Explicit allowlist entries (lowercase match) — always permitted in Co-authored-by.
ALLOWED_EXACT_COAUTHOR_EMAILS=(
  cursoragent@cursor.com
)

# Only these @gmail.com addresses may appear in Co-authored-by (lowercase match).
ALLOWED_GMAIL_COAUTHORS=(
  diazmelgarejo@gmail.com
  lawrence@cyre.me
)

# Public agent / vendor domains (match email domain or subdomain).
WELL_KNOWN_COAUTHOR_DOMAIN_SUFFIXES=(
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

# Match in Co-authored-by display name / address when domain alone is ambiguous.
WELL_KNOWN_COAUTHOR_NAME_MARKERS=(
  codex
  claude
  anthropic
  cursor
  cursoragent
  gemini
  google
  copilot
  openai
  github
  microsoft
  perplexity
  grok
)

email_domain_ok() {
  local email_lc="$1"
  local domain="${email_lc#*@}"
  [[ -z "$domain" ]] && return 1
  local suffix
  for suffix in "${WELL_KNOWN_COAUTHOR_DOMAIN_SUFFIXES[@]}"; do
    if [[ "$domain" == "$suffix" || "$domain" == *."$suffix" ]]; then
      return 0
    fi
  done
  return 1
}

gmail_allowed() {
  local email_lc="$1"
  local allowed
  for allowed in "${ALLOWED_GMAIL_COAUTHORS[@]}"; do
    if [[ "$email_lc" == "$allowed" ]]; then
      return 0
    fi
  done
  return 1
}

coauthor_line_ok() {
  local line_lc="$1"
  local email_lc=""
  if [[ "$line_lc" =~ \<([^>]+)\> ]]; then
    email_lc="$(printf '%s' "${BASH_REMATCH[1]}" | tr '[:upper:]' '[:lower:]')"
  fi

  if [[ -n "$email_lc" ]]; then
    local exact
    for exact in "${ALLOWED_EXACT_COAUTHOR_EMAILS[@]}"; do
      if [[ "$email_lc" == "$exact" ]]; then
        return 0
      fi
    done
    if [[ "$email_lc" == *@gmail.com || "$email_lc" == *@googlemail.com ]]; then
      gmail_allowed "$email_lc"
      return $?
    fi
    if email_domain_ok "$email_lc"; then
      return 0
    fi
  fi

  local marker
  for marker in "${WELL_KNOWN_COAUTHOR_NAME_MARKERS[@]}"; do
    if [[ "$line_lc" == *"$marker"* ]]; then
      return 0
    fi
  done

  return 1
}

if ! banned_patterns_ready "$REPO_ROOT"; then
  echo "ERROR: missing .cursor/private/banned-attribution-patterns" >&2
  echo "Run: bash scripts/cursor/install-user-git-environment.sh" >&2
  exit 1
fi

while IFS= read -r line || [[ -n "$line" ]]; do
  line_lc="$(printf '%s' "$line" | tr '[:upper:]' '[:lower:]')"
  case "$line" in
    [Cc]o-[Aa]uthor*)
      if line_matches_banned_pattern "$line_lc" "$REPO_ROOT"; then
        echo "ERROR: banned Co-authored-by trailer (see .cursor/private/):" >&2
        echo "  $line" >&2
        exit 1
      fi
      if ! coauthor_line_ok "$line_lc"; then
        echo "ERROR: Co-authored-by not on approved co-author policy:" >&2
        echo "  $line" >&2
        echo "Allowed: explicit allowlist (cursoragent@cursor.com), well-known public AI/vendor domains (openai.com, anthropic.com, cursor.com, …), or allowlisted gmail (diazMelgarejo@gmail.com, Lawrence@cyre.me)." >&2
        exit 1
      fi
      ;;
  esac
done < "$msg_file"

exit 0
