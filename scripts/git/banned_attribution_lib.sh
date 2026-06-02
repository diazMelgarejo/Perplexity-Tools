#!/usr/bin/env bash
# Shared helpers for gitignored banned-attribution patterns (no literals in callers).
set -euo pipefail

banned_patterns_file() {
  local root="${1:-}"
  if [[ -z "$root" ]]; then
    root="$(git rev-parse --show-toplevel 2>/dev/null || pwd)"
  fi
  local private="${root}/.cursor/private/banned-attribution-patterns"
  if [[ -f "$private" && -s "$private" ]]; then
    printf '%s' "$private"
    return 0
  fi
  local openclaw="${OPENCLAW_ATTRIBUTION_PATTERNS:-${HOME:-}/.cursor/openclaw/banned-attribution-patterns}"
  if [[ -f "$openclaw" && -s "$openclaw" ]]; then
    printf '%s' "$openclaw"
    return 0
  fi
  printf '%s' "$private"
}

banned_patterns_ready() {
  local f
  f="$(banned_patterns_file "${1:-}")"
  [[ -f "$f" && -s "$f" ]]
}

# First token only (avoids SIGPIPE from `... | head -n1` under pipefail).
# Usage: fixture_token="$(first_banned_pattern_token "$REPO_ROOT" || true)"
first_banned_pattern_token() {
  local token
  while IFS= read -r token; do
    [[ -n "$token" ]] || continue
    printf '%s' "$token"
    return 0
  done < <(list_banned_pattern_tokens "${1:-}")
  return 1
}

# Usage: while read -r token; do ...; done < <(list_banned_pattern_tokens "$root")
list_banned_pattern_tokens() {
  local f token
  f="$(banned_patterns_file "${1:-}")"
  if [[ ! -f "$f" ]]; then
    return 1
  fi
  while IFS= read -r token || [[ -n "$token" ]]; do
    token="${token%%#*}"
    token="$(printf '%s' "$token" | tr -d '[:space:]')"
    [[ -n "$token" ]] || continue
    printf '%s\n' "$token"
  done <"$f"
}

# First token only — avoids SIGPIPE from `list_* | head -n1` under pipefail.
first_banned_pattern_token() {
  local f token
  f="$(banned_patterns_file "${1:-}")"
  if [[ ! -f "$f" ]]; then
    return 1
  fi
  while IFS= read -r token || [[ -n "$token" ]]; do
    token="${token%%#*}"
    token="$(printf '%s' "$token" | tr -d '[:space:]')"
    [[ -n "$token" ]] || continue
    printf '%s' "$token"
    return 0
  done <"$f"
  return 1
}

line_matches_banned_pattern() {
  local line_lc="$1"
  local root="${2:-}"
  local token token_lc
  while IFS= read -r token; do
    token_lc="$(printf '%s' "$token" | tr '[:upper:]' '[:lower:]')"
    if [[ "$line_lc" == *"$token_lc"* ]]; then
      return 0
    fi
  done < <(list_banned_pattern_tokens "$root" 2>/dev/null || true)
  return 1
}
