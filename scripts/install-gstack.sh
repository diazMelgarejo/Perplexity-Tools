#!/usr/bin/env bash
# =============================================================================
# install-gstack.sh — Install gstack for this project
# =============================================================================
# gstack provides agent skills for web browsing, planning, and review.
# Run this once per machine. Requires: bun (https://bun.sh)
#
# Usage:
#   bash scripts/install-gstack.sh           # installs to ~/.claude/skills/gstack
#   bash scripts/install-gstack.sh --team    # also registers project-level team mode
#   bash scripts/install-gstack.sh --upgrade # upgrade existing install
# =============================================================================

set -euo pipefail

BOLD='\033[1m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; RED='\033[0;31m'
CYAN='\033[0;36m'; RESET='\033[0m'

log()  { echo -e "${BOLD}${CYAN}[install-gstack]${RESET} $*"; }
ok()   { echo -e "  ${GREEN}✓${RESET} $*"; }
warn() { echo -e "  ${YELLOW}⚠${RESET}  $*"; }
err()  { echo -e "  ${RED}✗${RESET} $*" >&2; }

GSTACK_DIR="$HOME/.claude/skills/gstack"
GSTACK_REPO="https://github.com/garrytan/gstack.git"
TEAM_MODE=0
UPGRADE=0

for arg in "$@"; do
  case "$arg" in
    --team)    TEAM_MODE=1 ;;
    --upgrade) UPGRADE=1 ;;
  esac
done

echo ""
echo "  ╔═══════════════════════════════════════════════════╗"
echo "  ║       AlphaClaw — gstack skill installer         ║"
echo "  ╚═══════════════════════════════════════════════════╝"
echo ""

# ─── Check bun ────────────────────────────────────────────────────────────────
log "Checking for bun runtime..."
if ! command -v bun &>/dev/null; then
  err "bun is required but not installed."
  echo ""
  echo "  Install bun (verify checksum before running):"
  echo "    BUN_VERSION=\"1.3.10\""
  echo "    tmpfile=\$(mktemp)"
  echo "    curl -fsSL https://bun.sh/install -o \"\$tmpfile\""
  echo "    echo \"Verify: shasum -a 256 \$tmpfile\""
  echo "    BUN_VERSION=\"\$BUN_VERSION\" bash \"\$tmpfile\" && rm \"\$tmpfile\""
  echo ""
  exit 1
fi
ok "bun $(bun --version) found"

# ─── Clone or upgrade ─────────────────────────────────────────────────────────
if [[ -d "$GSTACK_DIR" ]]; then
  if [[ "$UPGRADE" -eq 1 ]]; then
    log "Upgrading gstack..."
    cd "$GSTACK_DIR"
    git fetch --depth 1 origin main
    git reset --hard origin/main
    ok "gstack updated to $(cat VERSION 2>/dev/null || echo unknown)"
  else
    ok "gstack already installed at $GSTACK_DIR"
    log "To upgrade: bash scripts/install-gstack.sh --upgrade"
  fi
else
  log "Cloning gstack..."
  git clone --single-branch --depth 1 "$GSTACK_REPO" "$GSTACK_DIR"
  ok "Cloned gstack $(cat "$GSTACK_DIR/VERSION" 2>/dev/null || echo unknown)"
fi

# ─── Run setup ────────────────────────────────────────────────────────────────
log "Running gstack setup..."
cd "$GSTACK_DIR"
./setup
ok "gstack setup complete"

# ─── Team mode ────────────────────────────────────────────────────────────────
if [[ "$TEAM_MODE" -eq 1 ]]; then
  log "Enabling team mode for this project..."
  SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
  PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"

  ./setup --team
  cd "$PROJECT_ROOT"
  "$GSTACK_DIR/bin/gstack-team-init" required
  ok "Team mode enabled — teammates will get gstack on their next setup run"
fi

# ─── Summary ──────────────────────────────────────────────────────────────────
echo ""
echo "  ${BOLD}${GREEN}gstack ready!${RESET}"
echo ""
echo "  Key rule: always use /browse for web browsing."
echo "  Never use mcp__Claude_in_Chrome__* tools directly."
echo ""
echo "  Run skills with: /browse, /review, /ship, /qa, /investigate, etc."
echo "  Full list: see CLAUDE.md § gstack"
echo ""
echo "  To enable team mode for this repo:"
echo "    bash scripts/install-gstack.sh --team"
echo ""
