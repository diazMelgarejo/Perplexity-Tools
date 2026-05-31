#!/usr/bin/env bash
# =============================================================================
# install-claude-desktop-llm.sh — Build real MCPB bundles from upstream submodule
# =============================================================================
# Uses vendor/Claude-Desktop-LLM (yayoboy/Claude-Desktop-LLM) unchanged.
# Packs with @anthropic-ai/mcpb per Anthropic MCPB spec — not PT JSON knockoffs.
#
# Independent of AlphaClaw. Claude Code continues to use packages/alphaclaw-mcp.
#
# Usage:
#   bash scripts/install-claude-desktop-llm.sh              # build + stage .mcpb
#   bash scripts/install-claude-desktop-llm.sh --open         # macOS: open .mcpb in Claude Desktop
#   bash scripts/install-claude-desktop-llm.sh --skip-desktop # build only (CI / Linux)
# =============================================================================

set -euo pipefail

BOLD='\033[1m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; RED='\033[0;31m'
CYAN='\033[0;36m'; RESET='\033[0m'

log()  { echo -e "${BOLD}${CYAN}[claude-desktop-llm]${RESET} $*"; }
ok()   { echo -e "  ${GREEN}✓${RESET} $*"; }
warn() { echo -e "  ${YELLOW}⚠${RESET}  $*"; }
err()  { echo -e "  ${RED}✗${RESET} $*" >&2; }

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
SUBMODULE_DIR="$PT_ROOT/vendor/Claude-Desktop-LLM"
STAGE_DIR="$PT_ROOT/packages/mcpb-agents/built"
OPEN_DESKTOP=0
SKIP_DESKTOP=0

for arg in "$@"; do
  case "$arg" in
    --open) OPEN_DESKTOP=1 ;;
    --skip-desktop) SKIP_DESKTOP=1 ;;
    --help|-h)
      echo "Usage: install-claude-desktop-llm.sh [--open] [--skip-desktop]"
      exit 0
      ;;
  esac
done

ensure_submodule() {
  if [[ ! -f "$SUBMODULE_DIR/scripts/build-extensions.sh" ]]; then
    log "Initializing vendor/Claude-Desktop-LLM submodule..."
  fi
  git -C "$PT_ROOT" submodule update --init --recursive vendor/Claude-Desktop-LLM
  if [[ ! -f "$SUBMODULE_DIR/scripts/build-extensions.sh" ]]; then
    err "Submodule missing at $SUBMODULE_DIR"
    exit 1
  fi
  ok "submodule @ $(git -C "$SUBMODULE_DIR" rev-parse --short HEAD)"
}

MCPB_CMD=()

ensure_mcpb_cli() {
  if command -v mcpb &>/dev/null; then
    MCPB_CMD=(mcpb)
    ok "mcpb CLI: $(mcpb --version 2>/dev/null || echo present)"
    return 0
  fi
  if ! command -v npm &>/dev/null; then
    err "npm required for @anthropic-ai/mcpb (global or npx)"
    exit 1
  fi
  local local_bin="$PT_ROOT/.npm-global/bin"
  if [[ -x "$local_bin/mcpb" ]]; then
    MCPB_CMD=("$local_bin/mcpb")
    ok "mcpb CLI (local prefix)"
    return 0
  fi
  log "Installing @anthropic-ai/mcpb to $PT_ROOT/.npm-global ..."
  mkdir -p "$PT_ROOT/.npm-global"
  npm install --prefix "$PT_ROOT/.npm-global" @anthropic-ai/mcpb
  if [[ -x "$local_bin/mcpb" ]]; then
    MCPB_CMD=("$local_bin/mcpb")
    ok "mcpb CLI (local prefix)"
    return 0
  fi
  if npx --yes @anthropic-ai/mcpb --version &>/dev/null; then
    MCPB_CMD=(npx --yes @anthropic-ai/mcpb)
    ok "mcpb via npx @anthropic-ai/mcpb"
    return 0
  fi
  err "Could not run mcpb — install manually: npm install -g @anthropic-ai/mcpb"
  exit 1
}

run_mcpb() {
  "${MCPB_CMD[@]}" "$@"
}

build_extensions() {
  log "Building MCPB extensions (upstream build-extensions.sh)..."
  chmod +x "$SUBMODULE_DIR/scripts/build-extensions.sh"
  export PATH="$PT_ROOT/.npm-global/bin:${PATH:-}"
  (cd "$SUBMODULE_DIR" && bash scripts/build-extensions.sh)
  for name in ollama-agent.mcpb lmstudio-agent.mcpb; do
    if [[ ! -f "$SUBMODULE_DIR/dist/$name" ]]; then
      err "Expected $SUBMODULE_DIR/dist/$name"
      exit 1
    fi
  done
  ok "built in vendor/Claude-Desktop-LLM/dist/"
}

validate_bundles() {
  if [[ ${#MCPB_CMD[@]} -eq 0 ]]; then
    warn "mcpb not available — skip manifest validation"
    return 0
  fi
  for name in ollama-agent.mcpb lmstudio-agent.mcpb; do
    if run_mcpb info "$STAGE_DIR/$name" &>/dev/null; then
      ok "mcpb info: $name"
    else
      warn "mcpb info failed for $name (may still be valid ZIP bundle)"
    fi
  done
}

stage_bundles() {
  mkdir -p "$STAGE_DIR"
  cp -f "$SUBMODULE_DIR/dist/ollama-agent.mcpb" "$STAGE_DIR/"
  cp -f "$SUBMODULE_DIR/dist/lmstudio-agent.mcpb" "$STAGE_DIR/"
  ok "staged -> packages/mcpb-agents/built/"
}

# Optional PT stack defaults (env hints only — extensions use user_config in Claude Desktop)
write_stack_env_hint() {
  local hint="$STAGE_DIR/stack-env.example"
  cat >"$hint" <<'EOF'
# Optional env for Claude Desktop extension user_config (set in Settings → Extensions → Configure)
# PT does not write AlphaClaw config; these mirror common stack endpoints.
#
# Ollama Agent → server_url (default upstream: http://localhost:11434)
# LM Studio Agent → server_url (default upstream: http://localhost:1234)
#
# Mac Ollama (orama hard req): http://localhost:11434
# Win LM Studio LAN: set in Claude Desktop UI from your devices.yml / LMSTUDIO_BASE_URL
EOF
  ok "wrote stack-env.example (documentation only)"
}

open_in_claude_desktop() {
  if [[ "$SKIP_DESKTOP" -eq 1 ]]; then
    return 0
  fi
  if [[ "$(uname -s)" != "Darwin" ]]; then
    warn "Auto-open skipped (not macOS). Install manually:"
    echo "    Settings → Extensions → Install Extension… → select packages/mcpb-agents/built/*.mcpb"
    return 0
  fi
  if [[ "$OPEN_DESKTOP" -eq 1 ]] || [[ "${PERPETUA_MCPB_OPEN_DESKTOP:-}" == "1" ]]; then
    for bundle in "$STAGE_DIR"/*.mcpb; do
      [[ -f "$bundle" ]] || continue
      log "Opening $(basename "$bundle") with Claude Desktop..."
      open "$bundle" || warn "open failed for $bundle"
    done
  else
    info_install_manual
  fi
}

info_install_manual() {
  echo ""
  echo -e "  ${BOLD}Claude Desktop install:${RESET}"
  echo "    1. Open Claude Desktop → Settings → Extensions"
  echo "    2. Advanced settings → Install Extension…"
  echo "    3. Select:"
  echo "         $STAGE_DIR/ollama-agent.mcpb"
  echo "         $STAGE_DIR/lmstudio-agent.mcpb"
  echo "    Or: bash scripts/install-claude-desktop-llm.sh --open"
  echo ""
}

echo ""
echo "  ╔═══════════════════════════════════════════════════╗"
echo "  ║  Perpetua-Tools — Claude Desktop LLM (MCPB)    ║"
echo "  ╚═══════════════════════════════════════════════════╝"
echo ""

ensure_submodule
ensure_mcpb_cli
build_extensions
stage_bundles
write_stack_env_hint
validate_bundles
open_in_claude_desktop

ok "Claude-Desktop-LLM MCPB install complete"
