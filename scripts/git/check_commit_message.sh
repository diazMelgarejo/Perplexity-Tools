#!/usr/bin/env bash
set -euo pipefail

msg_file="${1:?commit message file required}"
[[ -f "$msg_file" ]] || { echo "ERROR: missing commit message file: $msg_file" >&2; exit 1; }

# Forbidden in Co-authored-by trailers only (not primary Author identity).
FORBIDDEN_COAUTHOR_SUBSTRINGS=(
  cursor
  anthropic
  claude
  bettermind
  cursoragent
)

while IFS= read -r line || [[ -n "$line" ]]; do
  case "$line" in
    [Cc]o-[Aa]uthor*)
      line_lc="$(printf '%s' "$line" | tr '[:upper:]' '[:lower:]')"
      for needle in "${FORBIDDEN_COAUTHOR_SUBSTRINGS[@]}"; do
        case "$line_lc" in
          *"$needle"*)
            echo "ERROR: forbidden Co-authored-by trailer in commit message:" >&2
            echo "  $line" >&2
            echo "Remove agent attribution lines before committing." >&2
            exit 1
            ;;
        esac
      done
      ;;
  esac
done < "$msg_file"

exit 0
