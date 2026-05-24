#!/usr/bin/env bash
# Apply Cursor commit-attribution guards to Perpetua-Tools + sibling OpenClaw repos.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
DISABLE="$SCRIPT_DIR/disable-cursor-commit-attribution.sh"
SYNC="$SCRIPT_DIR/sync-attribution-guard-scripts.sh"

OPENCLAW_HOME="${OPENCLAW_HOME:-$HOME/openclaw-v1}"

repos=(
  "$PT_ROOT"
  "${PERPETUA_TOOLS_PATH:-$PT_ROOT}"
  "${PERPETUA_TOOLS_ROOT:-$PT_ROOT}"
  "${ORAMA_SYSTEM_PATH:-$OPENCLAW_HOME/orama-system}"
  "${ALPHACLAW_INSTALL_DIR:-$OPENCLAW_HOME/AlphaClaw}"
)

# Deduplicate paths.
declare -A seen=()
unique=()
for r in "${repos[@]}"; do
  [[ -n "$r" ]] || continue
  if [[ -n "${seen[$r]+x}" ]]; then
    continue
  fi
  seen[$r]=1
  unique+=("$r")
done

if [[ -x "$SYNC" ]]; then
  for r in "${unique[@]}"; do
    [[ "$r" == "$PT_ROOT" ]] && continue
    if [[ -d "$r/.git" ]]; then
      bash "$SYNC" "$r"
    fi
  done
fi

for r in "${unique[@]}"; do
  if [[ -d "$r/.git" ]]; then
    bash "$DISABLE" "$r"
  else
    echo "skip (no .git): $r" >&2
  fi
done

echo "OK: attribution guards applied for ${#unique[@]} repo path(s)"
