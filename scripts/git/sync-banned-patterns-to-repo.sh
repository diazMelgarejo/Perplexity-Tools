#!/usr/bin/env bash
# Copy gitignored attribution patterns into any repo (never commits them).
set -euo pipefail

repo="${1:-.}"
repo="$(cd "$repo" && pwd)"
HOME="${HOME:-/home/ubuntu}"
OPENCLAW="${HOME}/.cursor/openclaw"
src="${OPENCLAW}/banned-attribution-patterns"
dst_dir="${repo}/.cursor/private"

if [[ ! -f "$src" ]]; then
  ORAMA="${ORAMA_SYSTEM_PATH:-/agent/repos/orama-system}"
  if [[ -x "${ORAMA}/scripts/cursor/write-openclaw-private-attribution.sh" ]]; then
    bash "${ORAMA}/scripts/cursor/write-openclaw-private-attribution.sh"
  else
    echo "ERROR: missing ${src}" >&2
    exit 1
  fi
fi

mkdir -p "$dst_dir"
chmod 700 "$dst_dir" 2>/dev/null || true
install -m 0600 "$src" "${dst_dir}/banned-attribution-patterns"
lesson="${OPENCLAW}/private-lessons/perpetua-tools-git-attribution.md"
[[ -f "$lesson" ]] && install -m 0600 "$lesson" "${dst_dir}/agent-lesson-git-attribution.md" || true
printf 'OK: patterns → %s\n' "$dst_dir"
