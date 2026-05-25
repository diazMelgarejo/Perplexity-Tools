#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

actual_name="$(git -C "$REPO_ROOT" config user.name || true)"
actual_email="$(git -C "$REPO_ROOT" config user.email || true)"
actual_email_lc="$(printf '%s' "$actual_email" | tr '[:upper:]' '[:lower:]')"

echo "git user.name=${actual_name:-<unset>}"
echo "git user.email=${actual_email:-<unset>}"

if [[ -z "$actual_name" || -z "$actual_email" ]]; then
  echo "ERROR: set user.name and user.email before committing" >&2
  exit 1
fi

if [[ "$actual_name" == "cyre" && "$actual_email_lc" == "diazmelgarejo@gmail.com" ]]; then
  echo "OK: approved git identity"
  exit 0
fi

if [[ "$actual_name" == "cyre" && "$actual_email_lc" == "lawrence@cyre.me" ]]; then
  echo "OK: approved git identity"
  exit 0
fi

if [[ "$actual_email_lc" == "lawrence@cyre.me" && "$actual_name" == *Lawrence* ]]; then
  echo "OK: approved git identity"
  exit 0
fi

if [[ "$actual_name" == "Codex" && "$actual_email_lc" == "codex@openai.com" ]]; then
  echo "OK: approved git identity"
  exit 0
fi

echo "ERROR: git identity must be one of:" >&2
echo "  - cyre <diazMelgarejo@gmail.com>" >&2
echo "  - cyre <Lawrence@cyre.me>" >&2
echo "  - Lawrence Cyre <Lawrence@cyre.me> (or similar name with Lawrence@cyre.me)" >&2
echo "  - Codex <codex@openai.com>" >&2
exit 1
