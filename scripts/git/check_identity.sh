#!/usr/bin/env bash
set -euo pipefail

# Keep in sync with scripts/review/repo_hygiene.py APPROVED_IDENTITIES.
ALLOWED_IDENTITIES=(
  "cyre|Lawrence@cyre.me"
  "cyre|diazMelgarejo@gmail.com"
  "Codex|codex@openai.com"
  "Cursor Agent|cursoragent@cursor.com"
)
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

actual_name="$(git -C "$REPO_ROOT" config user.name || true)"
actual_email="$(git -C "$REPO_ROOT" config user.email || true)"

echo "git user.name=${actual_name:-<unset>}"
echo "git user.email=${actual_email:-<unset>}"

for pair in "${ALLOWED_IDENTITIES[@]}"; do
  expected_name="${pair%%|*}"
  expected_email="${pair##*|}"
  if [[ "$actual_name" == "$expected_name" && "$actual_email" == "$expected_email" ]]; then
    echo "OK: approved git identity"
    exit 0
  fi
done

echo "ERROR: git identity must be one of:" >&2
for pair in "${ALLOWED_IDENTITIES[@]}"; do
  expected_name="${pair%%|*}"
  expected_email="${pair##*|}"
  echo "  - ${expected_name} <${expected_email}>" >&2
done
exit 1
