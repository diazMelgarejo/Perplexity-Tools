#!/usr/bin/env bash
# =============================================================================
# Perpetua-Tools install.sh — Layer-2 middleware bootstrap
# =============================================================================
# Installs Claude Desktop LLM extensions (real MCPB from vendor submodule) by default.
# Does not require AlphaClaw. Claude Code MCP: packages/alphaclaw-mcp (separate).
#
# Usage:
#   bash install.sh                    # submodule + build MCPB + stage bundles
#   bash install.sh --open             # also open .mcpb on macOS (Claude Desktop UI)
#   bash install.sh --skip-mcpb        # skip Desktop LLM (submodule init only)
#   bash install.sh --skip-desktop     # forwarded to install-claude-desktop-llm.sh
#   bash install.sh --help
# =============================================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SKIP_MCPB=0
EXTRA_ARGS=()

for arg in "$@"; do
  case "$arg" in
    --skip-mcpb) SKIP_MCPB=1 ;;
    --skip-desktop) EXTRA_ARGS+=("$arg") ;; # forwarded to install-claude-desktop-llm.sh
    --help|-h)
      echo "Usage: install.sh [--open] [--skip-mcpb] [--skip-desktop] [--help]"
      echo "  Default: init vendor/Claude-Desktop-LLM and build MCPB bundles."
      exit 0
      ;;
    *) EXTRA_ARGS+=("$arg") ;;
  esac
done

echo ""
echo "Perpetua-Tools install"
echo "──────────────────────"

if ! git -C "$SCRIPT_DIR" submodule update --init --recursive vendor/Claude-Desktop-LLM; then
  echo "Failed to init submodule vendor/Claude-Desktop-LLM" >&2
  exit 1
fi

if [[ "$SKIP_MCPB" -eq 0 ]]; then
  bash "$SCRIPT_DIR/scripts/install-claude-desktop-llm.sh" "${EXTRA_ARGS[@]}"
else
  echo "  (skipped MCPB build — --skip-mcpb)"
fi

echo ""
echo "Done. Claude Code: cd packages/alphaclaw-mcp && npm run build"
echo "      claude mcp add --transport stdio alphaclaw -- node packages/alphaclaw-mcp/build/index.js"
