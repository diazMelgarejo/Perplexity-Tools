#!/usr/bin/env bash
# Sync gitignored .cursor/private/ from ~/.cursor/openclaw (no tokens in this repo).
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
HOME="${HOME:-/home/ubuntu}"
OPENCLAW="${HOME}/.cursor/openclaw"
PRIVATE="${REPO_ROOT}/.cursor/private"

HOME_PATTERNS="${OPENCLAW}/banned-attribution-patterns"
HOME_GUIDE="${OPENCLAW}/banned-attribution-local.md"
HOME_LESSON="${OPENCLAW}/private-lessons/perpetua-tools-git-attribution.md"

if [[ ! -f "$HOME_PATTERNS" ]]; then
  ORAMA="${ORAMA_SYSTEM_PATH:-/agent/repos/orama-system}"
  if [[ -x "${ORAMA}/scripts/cursor/write-openclaw-private-attribution.sh" ]]; then
    bash "${ORAMA}/scripts/cursor/write-openclaw-private-attribution.sh"
  else
    echo "ERROR: missing ${HOME_PATTERNS}" >&2
    echo "Run orama-system: bash scripts/cursor/write-openclaw-private-attribution.sh" >&2
    echo "Or: bash scripts/cursor/install-user-git-environment.sh (orama)" >&2
    exit 1
  fi
fi

mkdir -p "$PRIVATE"
chmod 700 "$PRIVATE" 2>/dev/null || true

for pair in \
  "$HOME_PATTERNS|$PRIVATE/banned-attribution-patterns" \
  "$HOME_GUIDE|$PRIVATE/banned-attribution-local.md" \
  "$HOME_LESSON|$PRIVATE/agent-lesson-git-attribution.md"; do
  src="${pair%%|*}"
  dst="${pair##*|}"
  [[ -f "$src" ]] || continue
  install -m 0600 "$src" "$dst"
done

if [[ ! -f "$PRIVATE/banned-attribution-patterns" ]]; then
  echo "ERROR: sync failed — patterns file missing under .cursor/private/" >&2
  exit 1
fi

printf 'OK: synced private attribution into %s\n' "$PRIVATE"
