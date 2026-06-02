#!/usr/bin/env bash
# Self-contained CI bootstrap for gitignored attribution patterns (no orama checkout required).
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
HOME="${HOME:-/home/ubuntu}"
OPENCLAW="${HOME}/.cursor/openclaw"
PRIVATE="${REPO_ROOT}/.cursor/private"

decode_b64_line() {
  local raw decoded
  raw="$(printf '%s' "$1" | base64 -d 2>/dev/null || true)"
  decoded="$(printf '%s' "$raw" | tr -d '[:space:]')"
  [[ -n "$decoded" ]] || return 0
  printf '%s\n' "$decoded"
}

mkdir -p "$OPENCLAW/private-lessons" "$PRIVATE"
chmod 700 "$OPENCLAW" "$PRIVATE" 2>/dev/null || true

PATTERNS_OPENCLAW="${OPENCLAW}/banned-attribution-patterns"
if [[ -s "$PATTERNS_OPENCLAW" && -s "${PRIVATE}/banned-attribution-patterns" ]]; then
  printf 'OK: CI bootstrap already present → %s\n' "$PATTERNS_OPENCLAW"
  exit 0
fi

{
  echo "# Banned attribution tokens (one per line, case-insensitive substring match)"
  decode_b64_line "ZGFydGguc2VyaW91cw=="
  decode_b64_line "bmltYm9zYQ=="
} >"$PATTERNS_OPENCLAW"
chmod 600 "$PATTERNS_OPENCLAW"
install -m 0600 "$PATTERNS_OPENCLAW" "${PRIVATE}/banned-attribution-patterns"

printf 'OK: CI bootstrap → %s and %s\n' "$PATTERNS_OPENCLAW" "${PRIVATE}/banned-attribution-patterns"
