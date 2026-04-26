#!/usr/bin/env bash
# setup_codex.sh — Ensure Codex CLI is always callable from any Node version.
#
# Problem: Claude Code shells may activate nvm v14 (no codex) before PATH
#          reaches /opt/homebrew/bin where the native codex binary lives.
#
# Fix 1 (primary):  symlink ~/.local/bin/codex → /opt/homebrew/bin/codex
#                   ~/.local/bin is prepended to PATH in .zshrc, so it wins.
# Fix 2 (fallback): if homebrew codex is absent, ensure nvm default is 24.
#
# Run once at machine setup, or from start.sh / install.sh (idempotent).

set -euo pipefail

HOMEBREW_CODEX="/opt/homebrew/bin/codex"
LOCAL_BIN="$HOME/.local/bin"
SYMLINK="$LOCAL_BIN/codex"

echo "[setup_codex] Checking Codex availability..."

mkdir -p "$LOCAL_BIN"

# ── Fix 1: native Homebrew binary ────────────────────────────────────────────
if [ -f "$HOMEBREW_CODEX" ]; then
  if [ -L "$SYMLINK" ] && [ "$(readlink "$SYMLINK")" = "$HOMEBREW_CODEX" ]; then
    echo "[setup_codex] ✓ ~/.local/bin/codex already points to Homebrew native binary."
  else
    ln -sf "$HOMEBREW_CODEX" "$SYMLINK"
    echo "[setup_codex] ✓ Symlinked ~/.local/bin/codex → $HOMEBREW_CODEX"
  fi
  # Verify
  if "$SYMLINK" --version >/dev/null 2>&1; then
    echo "[setup_codex] ✓ codex OK: $("$SYMLINK" --version 2>&1 | head -1)"
    exit 0
  fi
fi

# ── Fix 2: nvm fallback ───────────────────────────────────────────────────────
echo "[setup_codex] Homebrew codex not found or broken — checking nvm..."

# Load nvm if available
NVM_SH="${NVM_DIR:-$HOME/.nvm}/nvm.sh"
if [ -s "$NVM_SH" ]; then
  # shellcheck source=/dev/null
  source "$NVM_SH"
  CURRENT=$(nvm current 2>/dev/null || echo "none")
  DEFAULT_VER=$(nvm alias default 2>/dev/null | grep -oE 'v[0-9]+' | head -1 || echo "")

  if [ "$CURRENT" = "v24."* ] || nvm use 24 >/dev/null 2>&1; then
    NVM_CODEX="$HOME/.nvm/versions/node/$(nvm current)/bin/codex"
    if [ -f "$NVM_CODEX" ]; then
      ln -sf "$NVM_CODEX" "$SYMLINK"
      echo "[setup_codex] ✓ Symlinked ~/.local/bin/codex → $NVM_CODEX"
    fi
  fi

  # Ensure nvm default is 24 so future shells get the right Node
  if [ "$DEFAULT_VER" != "v24" ]; then
    nvm alias default 24 2>/dev/null && echo "[setup_codex] ✓ nvm default set to 24"
  fi
fi

# ── Final check ───────────────────────────────────────────────────────────────
if command -v codex >/dev/null 2>&1; then
  echo "[setup_codex] ✓ codex reachable: $(codex --version 2>&1 | head -1)"
else
  echo "[setup_codex] ✗ codex NOT found. Install with:"
  echo "    brew install codex"
  echo "  or: nvm use 24 && npm install -g @openai/codex@latest"
  exit 1
fi
