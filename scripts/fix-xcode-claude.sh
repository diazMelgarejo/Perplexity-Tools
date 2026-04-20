#!/usr/bin/env bash
# =============================================================================
# fix-xcode-claude.sh — AlphaClaw Xcode 26.3 BETA + Claude Code Integration Fix
# =============================================================================
# Fixes: "No conversation found with session ID" and related Claude spawn errors
# Run from Terminal (NOT from inside Xcode): bash scripts/fix-xcode-claude.sh
# =============================================================================

set -euo pipefail

BOLD='\033[1m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; RED='\033[0;31m'
CYAN='\033[0;36m'; RESET='\033[0m'

log()  { echo -e "${BOLD}${CYAN}[fix-xcode-claude]${RESET} $*"; }
ok()   { echo -e "  ${GREEN}✓${RESET} $*"; }
warn() { echo -e "  ${YELLOW}⚠${RESET}  $*"; }
err()  { echo -e "  ${RED}✗${RESET} $*"; }
sep()  { echo "  ────────────────────────────────────────────"; }

echo ""
echo "  ╔═══════════════════════════════════════════════════╗"
echo "  ║  AlphaClaw — Xcode 26.3 BETA / Claude Code Fix   ║"
echo "  ╚═══════════════════════════════════════════════════╝"
echo ""
log "Platform: $(uname -m) | macOS $(sw_vers -productVersion 2>/dev/null || echo unknown)"
echo ""

# ─── STEP 1: Shell arch check ─────────────────────────────────────────────
sep
log "Step 1: Shell architecture"
ARCH=$(uname -m)
if [[ "$ARCH" == "arm64" ]]; then
    ok "Native ARM64 shell — esbuild binary selection will be correct"
else
    warn "Rosetta x64 shell detected — npm may install wrong esbuild binary"
    warn "For best results, open a new Terminal.app window WITHOUT Rosetta"
fi

# ─── STEP 2: Claude Code CLI ──────────────────────────────────────────────
sep
log "Step 2: Verifying Claude Code CLI"
CLAUDE_BIN=$(command -v claude 2>/dev/null || true)
if [[ -z "$CLAUDE_BIN" ]]; then
    err "Claude Code CLI not found in PATH"
    echo ""
    echo "    Install options:"
    echo "    a) Download from https://claude.ai/download (recommended)"
    echo "    b) npm install -g @anthropic-ai/claude-code"
    echo ""
    echo "    Then ensure PATH includes the install location:"
    echo "    export PATH=\"\$HOME/.local/bin:\$PATH\""
    echo ""
    # Try known locations
    for loc in /usr/local/bin/claude ~/.local/bin/claude /opt/homebrew/bin/claude; do
        if [[ -x "$loc" ]]; then
            CLAUDE_BIN="$loc"
            warn "Found claude at $loc but it's not in PATH"
            warn "Add to ~/.zshrc: export PATH=\"$(dirname $loc):\$PATH\""
            break
        fi
    done
    [[ -z "$CLAUDE_BIN" ]] && { err "Cannot continue without Claude Code CLI"; exit 1; }
fi

CLAUDE_VERSION=$("$CLAUDE_BIN" --version 2>/dev/null || echo "unknown")
ok "Claude Code CLI: $CLAUDE_BIN (v$CLAUDE_VERSION)"

# ─── STEP 3: Create ~/.claude/ directory ─────────────────────────────────
sep
log "Step 3: Initializing ~/.claude/ session directory"
mkdir -p ~/.claude
ok "~/.claude/ directory ready"

# Create settings.json if missing
CLAUDE_SETTINGS=~/.claude/settings.json
if [[ ! -f "$CLAUDE_SETTINGS" ]]; then
    cat > "$CLAUDE_SETTINGS" << 'JSON'
{
  "autoUpdaterStatus": "enabled",
  "hasCompletedOnboarding": true,
  "lastSeenChangelog": "1.0.0"
}
JSON
    ok "Created ~/.claude/settings.json"
else
    ok "~/.claude/settings.json exists"
fi

# ─── STEP 4: Clear stale session IDs ─────────────────────────────────────
sep
log "Step 4: Clearing stale session IDs"
STALE_IDS=(
    "a711fb52-edd6-4017-9fa4-3f9dac2c1481"
)

clear_stale_sessions_in_dir() {
    local dir="$1"
    local label="$2"
    local cleared=0
    for sid in "${STALE_IDS[@]}"; do
        if grep -rl "$sid" "$dir" 2>/dev/null | grep -q .; then
            warn "Found stale session $sid in $label"
            grep -rl "$sid" "$dir" 2>/dev/null | while IFS= read -r f; do
                cp "$f" "${f}.bak.$(date +%s)" 2>/dev/null || true
                python3 - "$f" "$sid" << 'PYEOF'
import json, sys
fpath, bad_sid = sys.argv[1], sys.argv[2]
try:
    with open(fpath, 'r') as fh:
        raw = fh.read()
    data = json.loads(raw)
    changed = False
    def scrub(obj):
        global changed
        if isinstance(obj, dict):
            keys_to_del = [k for k, v in obj.items()
                           if bad_sid in str(v) or ('session' in k.lower() and v == bad_sid)]
            for k in keys_to_del:
                del obj[k]
                changed = True
            for v in obj.values():
                scrub(v)
        elif isinstance(obj, list):
            for item in obj:
                scrub(item)
    scrub(data)
    if changed:
        with open(fpath, 'w') as fh:
            json.dump(data, fh, indent=2)
        print(f"  Cleared stale session from {fpath}")
except Exception as e:
    print(f"  Skipped {fpath}: {e}")
PYEOF
                cleared=1
            done
        fi
    done
    [[ $cleared -eq 0 ]] && ok "No stale sessions in $label"
}

# VS Code Claude Code extension
VSCODE_CLAUDE="$HOME/Library/Application Support/Code/User/globalStorage/anthropic.claude-code"
if [[ -d "$VSCODE_CLAUDE" ]]; then
    clear_stale_sessions_in_dir "$VSCODE_CLAUDE" "VS Code Claude extension"
else
    ok "VS Code Claude extension state: not found (clean)"
fi

# Cursor IDE
CURSOR_CLAUDE="$HOME/Library/Application Support/Cursor/User/globalStorage/anthropic.claude-code"
if [[ -d "$CURSOR_CLAUDE" ]]; then
    clear_stale_sessions_in_dir "$CURSOR_CLAUDE" "Cursor Claude extension"
else
    ok "Cursor Claude extension state: not found (clean)"
fi

# Xcode CodingAssistant
XCODE_CA="$HOME/Library/Developer/Xcode/CodingAssistant/ClaudeAgentConfig"
if [[ -d "$XCODE_CA" ]]; then
    clear_stale_sessions_in_dir "$XCODE_CA" "Xcode CodingAssistant"
else
    ok "Xcode CodingAssistant: not yet configured (will create below)"
fi

# ~/.claude sessions directory
CLAUDE_SESSIONS=~/.claude/sessions
if [[ -d "$CLAUDE_SESSIONS" ]]; then
    for sid in "${STALE_IDS[@]}"; do
        local_session="$CLAUDE_SESSIONS/$sid"
        if [[ -e "$local_session" ]]; then
            rm -rf "$local_session"
            ok "Removed stale session dir: $local_session"
        fi
    done
    ok "~/.claude/sessions cleaned"
fi

# ─── STEP 5: Fix npm prefix ───────────────────────────────────────────────
sep
log "Step 5: npm prefix (sudo-free installs)"
NPM_PREFIX=$(npm config get prefix 2>/dev/null || echo "")
if [[ "$NPM_PREFIX" == "/usr/local" || "$NPM_PREFIX" == "/usr" || \
      "$NPM_PREFIX" == "/usr/local/lib" || "$NPM_PREFIX" == "/opt/homebrew" ]]; then
    warn "npm prefix is '$NPM_PREFIX' (system-owned) — changing to ~/.local"
    npm config set prefix ~/.local
    mkdir -p ~/.local/bin

    ZSHRC=~/.zshrc
    if ! grep -q '"$HOME/.local/bin"' "$ZSHRC" 2>/dev/null && \
       ! grep -q '/.local/bin' "$ZSHRC" 2>/dev/null; then
        {
            echo ''
            echo '# sudo-free npm prefix — added by AlphaClaw fix-xcode-claude.sh'
            echo 'export PATH="$HOME/.local/bin:$PATH"'
        } >> "$ZSHRC"
        warn "Added ~/.local/bin to PATH in ~/.zshrc"
        warn "Run: source ~/.zshrc   (or open a new terminal)"
    fi
    ok "npm prefix is now ~/.local"
else
    ok "npm prefix is '$NPM_PREFIX' — OK"
fi

# ─── STEP 6: xcrun mcpbridge registration ────────────────────────────────
sep
log "Step 6: Registering xcrun mcpbridge MCP server"

# Find Xcode developer tools
XCODE_DEV=$(xcode-select -p 2>/dev/null || echo "")
if [[ -z "$XCODE_DEV" ]]; then
    warn "xcode-select -p returned nothing — Xcode Command Line Tools may not be installed"
    warn "Run: xcode-select --install"
else
    ok "Xcode developer tools: $XCODE_DEV"
fi

# Check for mcpbridge
MCPBRIDGE=""
for candidate in \
    "$(xcrun --find mcpbridge 2>/dev/null || true)" \
    "$XCODE_DEV/usr/bin/mcpbridge" \
    "/Applications/Xcode-26.3-BETA.app/Contents/Developer/usr/bin/mcpbridge" \
    "/Applications/Xcode.app/Contents/Developer/usr/bin/mcpbridge"; do
    if [[ -x "$candidate" ]]; then
        MCPBRIDGE="$candidate"
        break
    fi
done

if [[ -n "$MCPBRIDGE" ]]; then
    ok "mcpbridge found: $MCPBRIDGE"
    if "$CLAUDE_BIN" mcp list 2>/dev/null | grep -q "^xcode"; then
        ok "'xcode' MCP server already registered"
    else
        "$CLAUDE_BIN" mcp add --transport stdio xcode -- xcrun mcpbridge
        ok "Registered 'xcode' MCP server (xcrun mcpbridge)"
    fi
else
    warn "xcrun mcpbridge not found — requires Xcode 26.3+ with Intelligence enabled"
    warn "Enable via: Xcode → Settings → Intelligence → Model Context Protocol"
    warn "→ 'Allow external agents to use Xcode tools': ON"
    warn "After enabling, rerun this script"
fi

# Register alphaclaw MCP server
sep
log "Step 6b: Registering alphaclaw MCP server"
SCRIPT_DIR_TMP="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT_TMP="$(dirname "$SCRIPT_DIR_TMP")"
ALPHACLAW_MCP="$PROJECT_ROOT_TMP/lib/mcp/alphaclaw-mcp.js"

if [[ -f "$ALPHACLAW_MCP" ]]; then
    if "$CLAUDE_BIN" mcp list 2>/dev/null | grep -q "^alphaclaw"; then
        ok "'alphaclaw' MCP server already registered"
    else
        "$CLAUDE_BIN" mcp add --transport stdio alphaclaw -- node "$ALPHACLAW_MCP"
        ok "Registered 'alphaclaw' MCP server ($ALPHACLAW_MCP)"
    fi
else
    warn "lib/mcp/alphaclaw-mcp.js not found — skipping alphaclaw MCP registration"
fi

# ─── STEP 7: Xcode CodingAssistant config ────────────────────────────────
sep
log "Step 7: Xcode 26.3 CodingAssistant config"
XCODE_CA_DIR="$HOME/Library/Developer/Xcode/CodingAssistant/ClaudeAgentConfig"
mkdir -p "$XCODE_CA_DIR"

CLAUDE_PATH="$CLAUDE_BIN"
cat > "$XCODE_CA_DIR/.claude.json" << JSON
{
  "claudeCodePath": "$CLAUDE_PATH",
  "preferredModel": "claude-sonnet-4-6",
  "enableMCP": true,
  "mcpServers": {
    "xcode": {
      "command": "xcrun",
      "args": ["mcpbridge"],
      "type": "stdio"
    }
  },
  "sessionManagement": {
    "resumeOnRestart": false,
    "clearStaleSessionsOnStart": true
  }
}
JSON
ok "Xcode CodingAssistant config: $XCODE_CA_DIR/.claude.json"

# ─── STEP 8: Verify project .mcp.json ────────────────────────────────────
sep
log "Step 8: Verify project-level .mcp.json"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
MCP_JSON="$PROJECT_ROOT/.mcp.json"

if [[ -f "$MCP_JSON" ]]; then
    ok ".mcp.json exists at project root"
    python3 -c "import json; json.load(open('$MCP_JSON')); print('  Syntax: valid JSON')"
else
    warn ".mcp.json missing — creating"
    cat > "$MCP_JSON" << 'JSON'
{
  "mcpServers": {
    "xcode": {
      "command": "xcrun",
      "args": ["mcpbridge"],
      "type": "stdio"
    }
  }
}
JSON
    ok ".mcp.json created"
fi

# ─── STEP 9: Verify Claude Code MCP list ─────────────────────────────────
sep
log "Step 9: Claude Code MCP server list"
echo ""
"$CLAUDE_BIN" mcp list 2>/dev/null || warn "Could not list MCP servers"
echo ""

# ─── STEP 10: Test Claude Code spawn ─────────────────────────────────────
sep
log "Step 10: Test Claude Code spawning"
TEST_OUTPUT=$("$CLAUDE_BIN" --version 2>&1)
if [[ $? -eq 0 ]]; then
    ok "Claude Code CLI spawns cleanly: $TEST_OUTPUT"
else
    err "Claude Code CLI spawn failed: $TEST_OUTPUT"
fi

# ─── SUMMARY ─────────────────────────────────────────────────────────────
echo ""
sep
echo ""
echo "  ${BOLD}${GREEN}Fix complete!${RESET}"
echo ""
echo "  Next steps:"
echo ""
echo "  1. ${BOLD}Restart Xcode${RESET} (quit fully, then reopen AlphaClaw)"
echo ""
echo "  2. ${BOLD}Enable MCP in Xcode:${RESET}"
echo "     Xcode → Settings → Intelligence"
echo "     → Model Context Protocol → Xcode Tools: ON"
echo ""
echo "  3. ${BOLD}Verify MCP registration:${RESET}"
echo "     claude mcp list"
echo "     (should show 'xcode' server)"
echo ""
echo "  4. ${BOLD}If session error recurs${RESET}, run:"
echo "     bash scripts/fix-xcode-claude.sh"
echo ""
echo "  For AlphaClaw macOS build/test:"
echo "     bash scripts/setup-macos-sandbox.sh"
echo ""
sep
