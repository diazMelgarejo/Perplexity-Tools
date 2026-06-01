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
# ensure_mcpb_cli ensures a usable `mcpb` CLI is available (prefers system `mcpb`, then the local npm prefix, then `npx`); exits with status 1 if none can be run.
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
  npm install -g --prefix "$PT_ROOT/.npm-global" @anthropic-ai/mcpb
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
# build_extensions runs the upstream build-extensions.sh in the vendor submodule (making it executable and prepending the local npm-global bin to PATH) and verifies that the expected .mcpb artifacts exist.
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
# validate_bundles validates the staged `.mcpb` bundles by running `mcpb info` and logs success or warnings; if no `mcpb` CLI is configured it logs a warning and returns.
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
# write_stack_env_hint writes a documentation-only stack-env.example into "$STAGE_DIR" describing common Claude Desktop extension `user_config` defaults (Ollama and LM Studio endpoints) and does not modify runtime configuration.
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

# probe_required_endpoints performs startup health checks for required model backends before installing extensions.
# On macOS: verifies Ollama at localhost:11434 and checks for qwen3.5:9b-nvfp4 and bge-m3 models.
# On Windows: checks LM_STUDIO_WIN_ENDPOINTS environment variable and verifies connectivity.
# probe_required_endpoints checks local model backends required for desktop integration and exits with status 1 if required probes fail; it skips probes on Linux, in CI, or when --skip-desktop is set.
probe_required_endpoints() {
  if [[ "$SKIP_DESKTOP" -eq 1 ]]; then
    return 0
  fi
  if [[ "$(uname -s)" == "Linux" ]]; then
    return 0
  fi
  if [[ "${CI:-}" == "true" ]]; then
    return 0
  fi

  local os="$(uname -s)"

  if [[ "$os" == "Darwin" ]]; then
    # macOS: probe Ollama
    log "Probing Ollama at http://localhost:11434 (Mac hard requirement)..."
    if ! command -v curl &>/dev/null; then
      err "curl required for Ollama health probe"
      exit 1
    fi

    # Single call: check reachability and fetch model list with a 5-second timeout.
    local models_json
    models_json=$(curl -sf --max-time 5 http://localhost:11434/api/tags 2>/dev/null)
    if [[ -z "$models_json" ]]; then
      err "Ollama not reachable at http://localhost:11434 (timeout or not running)"
      err "Mac requires Ollama with qwen3.5:9b-nvfp4 and bge-m3 models"
      err "Install: https://ollama.ai/ then run: ollama pull qwen3.5:9b-nvfp4 && ollama pull bge-m3"
      exit 1
    fi
    local has_qwen=false
    local has_bge=false

    if echo "$models_json" | grep -q "qwen3.5:9b-nvfp4"; then
      has_qwen=true
    fi
    if echo "$models_json" | grep -q "bge-m3"; then
      has_bge=true
    fi

    if [[ "$has_qwen" == false ]] || [[ "$has_bge" == false ]]; then
      err "Required Ollama models missing:"
      [[ "$has_qwen" == false ]] && err "  - qwen3.5:9b-nvfp4"
      [[ "$has_bge" == false ]] && err "  - bge-m3"
      err "Install with: ollama pull qwen3.5:9b-nvfp4 && ollama pull bge-m3"
      exit 1
    fi

    ok "Ollama healthy with required models (qwen3.5:9b-nvfp4, bge-m3)"

  elif [[ "$os" == "MINGW"* ]] || [[ "$os" == "MSYS"* ]] || [[ "$os" == "CYGWIN"* ]]; then
    # Windows: probe LM Studio
    log "Probing LM Studio endpoints (Windows hard requirement)..."
    if [[ -z "${LM_STUDIO_WIN_ENDPOINTS:-}" ]]; then
      err "LM_STUDIO_WIN_ENDPOINTS not set"
      err "Windows requires LM Studio endpoints to be configured"
      err "Set in .env: LM_STUDIO_WIN_ENDPOINTS=http://192.168.x.x:1234,..."
      exit 1
    fi

    if ! command -v curl &>/dev/null; then
      err "curl required for LM Studio health probe"
      exit 1
    fi

    # Split comma-separated endpoints and probe each
    local IFS=','
    local endpoints=($LM_STUDIO_WIN_ENDPOINTS)
    local any_reachable=false

    for endpoint in "${endpoints[@]}"; do
      # Trim whitespace
      endpoint=$(echo "$endpoint" | xargs)
      if curl -sf --max-time 5 "$endpoint/v1/models" &>/dev/null; then
        ok "LM Studio reachable at $endpoint"
        any_reachable=true
      else
        warn "LM Studio unreachable at $endpoint"
      fi
    done

    if [[ "$any_reachable" == false ]]; then
      err "No LM Studio endpoints reachable from LM_STUDIO_WIN_ENDPOINTS"
      err "Ensure LM Studio is running and configured in .env"
      exit 1
    fi
  fi
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
# probe_required_endpoints is intentionally called here even though this is a
# build-only script. It is a no-op when SKIP_DESKTOP=1, when CI=true, or on
# Linux, so build/CI paths are unaffected. The probe runs only on macOS/Windows
# in a real installation context, which is the intended use.
probe_required_endpoints
open_in_claude_desktop

ok "Claude-Desktop-LLM MCPB install complete"
