#!/usr/bin/env bash
# Apply mandatory git hooks to Perpetua-Tools + sibling repos (Cursor session + manual).
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
DISABLE="$SCRIPT_DIR/disable-cursor-commit-attribution.sh"
INSTALL="$SCRIPT_DIR/install-local-hooks.sh"
SYNC="$SCRIPT_DIR/sync-attribution-guard-scripts.sh"

OPENCLAW_HOME="${OPENCLAW_HOME:-$HOME/openclaw-v1}"

resolve_git_repo() {
  local r="$1"
  [[ -n "$r" ]] || return 1
  [[ "$r" == *'${'* ]] && return 1
  [[ -d "$r/.git" ]] || return 1
  local abs
  abs="$(cd "$r" && pwd)" || return 1
  printf '%s' "$abs"
}

raw_candidates=(
  "$PT_ROOT"
  "${PERPETUA_TOOLS_PATH:-$PT_ROOT}"
  "${PERPETUA_TOOLS_ROOT:-$PT_ROOT}"
  "${ORAMA_SYSTEM_PATH:-$OPENCLAW_HOME/orama-system}"
  "${ALPHACLAW_INSTALL_DIR:-$OPENCLAW_HOME/AlphaClaw}"
  "/agent/repos/Perpetua-Tools"
  "/agent/repos/orama-system"
  "/agent/repos/AlphaClaw"
  "/agent/repos/periscope"
)

if [[ -d /agent/repos ]]; then
  for d in /agent/repos/*; do
    raw_candidates+=("$d")
  done
fi

declare -A seen=()
unique=()
for r in "${raw_candidates[@]}"; do
  resolved="$(resolve_git_repo "$r" 2>/dev/null || true)"
  [[ -n "$resolved" ]] || continue
  if [[ -n "${seen[$resolved]+x}" ]]; then
    continue
  fi
  seen[$resolved]=1
  unique+=("$resolved")
done

if [[ -x "$SYNC" ]]; then
  for r in "${unique[@]}"; do
    [[ "$r" == "$PT_ROOT" ]] && continue
    bash "$SYNC" "$r" 2>/dev/null || true
  done
fi

for r in "${unique[@]}"; do
  bash "$DISABLE" "$r"
  if [[ -x "$INSTALL" && -x "$r/scripts/git/ensure_hooks_installed.sh" ]]; then
    bash "$INSTALL" "$r" || echo "warn: install-local-hooks failed: $r" >&2
  elif [[ -x "$DISABLE" ]]; then
    :
  fi
  git -C "$r" config --local user.name "cyre" 2>/dev/null || true
  git -C "$r" config --local user.email "Lawrence@cyre.me" 2>/dev/null || true
done

echo "OK: mandatory hooks applied for ${#unique[@]} repo(s)"
