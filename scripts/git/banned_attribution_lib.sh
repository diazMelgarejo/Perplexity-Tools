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

# banned_patterns_ready reports whether a valid banned-attribution patterns file exists and is non-empty.
# banned_patterns_ready accepts an optional root directory argument used to resolve the patterns file; it exits with status 0 if the resolved file exists and has size > 0, non-zero otherwise.
banned_patterns_ready() {
  local f
  f="$(banned_patterns_file "${1:-}")"
  [[ -f "$f" && -s "$f" ]]
}

# list_banned_pattern_tokens streams banned-attribution pattern tokens (one per line) from the repository or user patterns file.
# It resolves the patterns file (optional `root` argument), reads it line-by-line, removes inline comments (`#`) and all whitespace, skips empty tokens, and writes each remaining token to stdout on its own line.
# Usage: while read -r token; do ...; done < <(list_banned_pattern_tokens "$root")
# Parameters:
#   root (optional) — repository root directory to use when resolving the patterns file; if omitted, the script determines the root automatically.
# Exit:
#   Returns non-zero if the resolved patterns file does not exist or cannot be read.
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

# first_banned_pattern_token outputs the first non-empty, non-comment banned-attribution pattern token from the resolved patterns file (takes an optional root directory argument).
# It prints the token to stdout and returns success; if no file or no token is found it returns a non-zero status.
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

# line_matches_banned_pattern checks whether a lowercased line contains any banned-attribution pattern token; tokens are lowercased before matching and are read from the resolved patterns file.
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
