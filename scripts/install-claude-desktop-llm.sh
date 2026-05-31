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

# log prints a prefixed informational message to stdout using a bold cyan [claude-desktop-llm] tag.
log()  { echo -e "${BOLD}${CYAN}[claude-desktop-llm]${RESET} $*"; }
# ok prints a green checkmark followed by the provided message to stdout.
ok()   { echo -e "  ${GREEN}✓${RESET} $*"; }
# warn prints its arguments as a single warning line prefixed with a yellow ⚠ symbol.
warn() { echo -e "  ${YELLOW}⚠${RESET}  $*"; }
# err prints an error message to stderr prefixed with a red "✗" indicator.
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

# ensure_submodule ensures the vendor/Claude-Desktop-LLM submodule is initialized and updated recursively and verifies that scripts/build-extensions.sh exists, exiting with status 1 if it is missing.
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

# ensure_mcpb_cli ensures the `mcpb` CLI is available and sets the global MCPB_CMD array to the command invocation to use.
# Prefers a system `mcpb`, then a locally installed copy under "$PT_ROOT/.npm-global/bin", and falls back to `npx` if needed.
# Exits with status 1 if `npm` is not available or no usable `mcpb` can be run.
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

# run_mcpb invokes the configured `mcpb` command with the provided arguments.
run_mcpb() {
  "${MCPB_CMD[@]}" "$@"
}

# build_extensions builds the upstream MCPB extension bundles by invoking the vendor submodule's build-extensions.sh and verifies the expected .mcpb artifacts exist in vendor/Claude-Desktop-LLM/dist/.
# It also ensures the upstream script is executable and prepends the local npm-global bin to PATH before running the build.
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

# validate_bundles runs `mcpb info` on the staged MCPB bundles and logs success or warnings for each.
# If the `mcpb` CLI is not available, it logs a warning and skips validation.
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

# stage_bundles creates the stage directory and copies ollama-agent.mcpb and lmstudio-agent.mcpb from the vendor submodule into packages/mcpb-agents/built/.
stage_bundles() {
  mkdir -p "$STAGE_DIR"
  cp -f "$SUBMODULE_DIR/dist/ollama-agent.mcpb" "$STAGE_DIR/"
  cp -f "$SUBMODULE_DIR/dist/lmstudio-agent.mcpb" "$STAGE_DIR/"
  ok "staged -> packages/mcpb-agents/built/"
}

# write_stack_env_hint writes a documentation-only example file at "$STAGE_DIR/stack-env.example" containing common Claude Desktop extension `server_url` defaults and deployment hints.
# It only emits user-facing guidance and does not modify any runtime configuration or extension settings.
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

# open_in_claude_desktop opens staged .mcpb bundles in Claude Desktop on macOS when enabled. If SKIP_DESKTOP=1 the function returns immediately; on non-macOS it prints manual install instructions. When OPEN_DESKTOP=1 or PERPETUA_MCPB_OPEN_DESKTOP=1 it attempts to open each .mcpb in STAGE_DIR using `open` (warnings are issued on failure); otherwise it prints manual installation steps via info_install_manual.
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

# info_install_manual prints step-by-step instructions for manually installing the staged MCPB `.mcpb` bundles into Claude Desktop and suggests the `--open` shortcut.
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
