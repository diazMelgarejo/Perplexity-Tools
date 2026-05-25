#!/usr/bin/env bash
# Co-authored-by policy: allow well-known public AI/helper attribution; block
# unattributable random @gmail.com co-authors (see docs/wiki/08-git-hygiene-and-branching.md).
set -euo pipefail

msg_file="${1:?commit message file required}"
[[ -f "$msg_file" ]] || { echo "ERROR: missing commit message file: $msg_file" >&2; exit 1; }

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
  github.com
  microsoft.com
  azure.com
)

# Match in Co-authored-by display name / address when domain alone is ambiguous.
WELL_KNOWN_COAUTHOR_NAME_MARKERS=(
  codex
  claude
  anthropic
  cursor
  cursoragent
  gemini
  copilot
  openai
  github
  microsoft
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

while IFS= read -r line || [[ -n "$line" ]]; do
  case "$line" in
    [Cc]o-[Aa]uthor*)
      line_lc="$(printf '%s' "$line" | tr '[:upper:]' '[:lower:]')"
      if ! coauthor_line_ok "$line_lc"; then
        echo "ERROR: Co-authored-by not on approved co-author policy:" >&2
        echo "  $line" >&2
        echo "Allowed: well-known public AI/vendor domains (openai.com, anthropic.com, cursor.com, …) or allowlisted gmail (diazMelgarejo@gmail.com, Lawrence@cyre.me)." >&2
        exit 1
      fi
      ;;
  esac
done < "$msg_file"

exit 0
