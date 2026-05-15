#!/usr/bin/env bash
# scripts/ensure_requirements.sh — idempotent requirements probe + installer
# Perpetua-Tools v0.9.9.8 (Layer 2 — middleware/adapters)
#
# SOFT requirements (auto-install, non-fatal if fail):
#   Python venv + pip deps (requirements.txt)
#   Node packages (packages/alphaclaw-adapter, packages/alphaclaw-mcp)
#
# Hard requirements (Ollama + models) are probed by orama-system's
# ensure_requirements.sh — PT does not re-probe them here to avoid duplication.
# PT's only hard check: LM Studio Win endpoint (warns, does not abort).
#
# Usage:
#   bash scripts/ensure_requirements.sh            # check + install
#   bash scripts/ensure_requirements.sh --check    # probe only, exit 1 if missing
#   bash scripts/ensure_requirements.sh --force    # skip stamps, reinstall
#   bash scripts/ensure_requirements.sh --quiet    # suppress INFO lines

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
STAMP_FILE="${SCRIPT_DIR}/.requirements.stamp"
LOG_DIR="${SCRIPT_DIR}/.logs"
mkdir -p "$LOG_DIR"

MODE_CHECK=0; MODE_FORCE=0; MODE_QUIET=0
for _arg in "$@"; do
  case "$_arg" in
    --check) MODE_CHECK=1 ;;
    --force) MODE_FORCE=1 ;;
    --quiet) MODE_QUIET=1 ;;
  esac
done

_ts()   { date +%H:%M:%S; }
_info() { [ "$MODE_QUIET" -eq 0 ] && echo "[$(_ts)] INFO  [pt-ensure] $*" || true; }
_warn() { echo "[$(_ts)] WARN  [pt-ensure] $*" >&2; }
_err()  { echo "[$(_ts)] ERROR [pt-ensure] $*" >&2; }
_ok()   { echo "[$(_ts)] OK    [pt-ensure] $*"; }

_req_hash() {
  local req="${SCRIPT_DIR}/requirements.txt"
  [ -f "$req" ] && sha256sum "$req" 2>/dev/null | cut -d' ' -f1 || echo "none"
}
_stamp_current() {
  cat "$STAMP_FILE" 2>/dev/null | grep "^python_req=" | cut -d= -f2 || echo ""
}
_stamp_write() {
  { echo "python_req=$(_req_hash)"; echo "ts=$(date -u +%Y-%m-%dT%H:%M:%SZ)"; echo "version=1"; } > "$STAMP_FILE"
}

# ──────────────────────────────────────────────────────────────────────────────
# PHASE 1 — SOFT warn: LM Studio Win endpoint (PT routes to it — not probed hard here)
# ──────────────────────────────────────────────────────────────────────────────
_info "Phase 1 — LM Studio Win endpoint check (advisory)"

LM_WIN_ENDPOINTS="${LM_STUDIO_WIN_ENDPOINTS:-}"
if [ -z "$LM_WIN_ENDPOINTS" ]; then
  _warn "LM_STUDIO_WIN_ENDPOINTS not set — Windows GPU routing will be unavailable"
  _warn "Set in .env or export before starting. See CLAUDE-instru.md §6."
else
  _info "LM_STUDIO_WIN_ENDPOINTS=${LM_WIN_ENDPOINTS} (not probed here — orama start.sh does LAN probe)"
fi

# ──────────────────────────────────────────────────────────────────────────────
# PHASE 2 — SOFT: Python venv + pip deps (stamp-gated)
# ──────────────────────────────────────────────────────────────────────────────
_info "Phase 2 — Python venv + dependencies"

VENV_FRESH=0
if [ ! -d "${SCRIPT_DIR}/.venv" ]; then
  if [ "$MODE_CHECK" -eq 0 ]; then
    _info "Creating Python venv..."
    python3 -m venv "${SCRIPT_DIR}/.venv" >>"${LOG_DIR}/install.log" 2>&1 || {
      _warn "venv creation failed — see ${LOG_DIR}/install.log"; }
    VENV_FRESH=1
  else
    _warn ".venv not found — run without --check to create"
  fi
else
  _ok "Python venv exists"
fi

if [ -d "${SCRIPT_DIR}/.venv" ]; then
  CURRENT_HASH="$(_stamp_current)"
  EXPECTED_HASH="$(_req_hash)"
  if [ "$MODE_FORCE" -eq 1 ] || [ "$VENV_FRESH" -eq 1 ] || [ "$CURRENT_HASH" != "$EXPECTED_HASH" ]; then
    if [ "$MODE_CHECK" -eq 0 ]; then
      _info "Installing Python deps..."
      "${SCRIPT_DIR}/.venv/bin/pip" install -q -r "${SCRIPT_DIR}/requirements.txt" \
        >>"${LOG_DIR}/install.log" 2>&1 && {
        _stamp_write; _ok "Python deps installed"
      } || _warn "pip install failed — see ${LOG_DIR}/install.log"
    else
      _warn "requirements.txt hash mismatch — run without --check to update"
    fi
  else
    _ok "Python deps up-to-date (stamp matches)"
  fi
fi

# ──────────────────────────────────────────────────────────────────────────────
# PHASE 3 — SOFT: Node packages for PT adapter packages
# ──────────────────────────────────────────────────────────────────────────────
_info "Phase 3 — Node packages for PT adapter packages"

NODE_PACKAGES=(
  "packages/alphaclaw-adapter"
  "packages/alphaclaw-mcp"
)

for pkg_rel in "${NODE_PACKAGES[@]}"; do
  PKG_DIR="${SCRIPT_DIR}/${pkg_rel}"
  if [ ! -d "$PKG_DIR" ]; then
    _info "Package ${pkg_rel} not found — skipping"
    continue
  fi

  PKG_JSON="${PKG_DIR}/package.json"
  NODE_MODULES="${PKG_DIR}/node_modules"
  PKG_STAMP="${PKG_DIR}/.node_stamp"

  if [ ! -f "$PKG_JSON" ]; then
    _info "${pkg_rel}: no package.json — skipping"
    continue
  fi

  # Hash package.json to detect changes
  PKG_HASH=$(sha256sum "$PKG_JSON" 2>/dev/null | cut -d' ' -f1 || echo "none")
  CURRENT_PKG_STAMP=$(cat "$PKG_STAMP" 2>/dev/null || echo "")

  if [ ! -d "$NODE_MODULES" ] || [ "$MODE_FORCE" -eq 1 ] || [ "$CURRENT_PKG_HASH" != "$PKG_HASH" ] 2>/dev/null; then
    if [ "$MODE_CHECK" -eq 0 ]; then
      if command -v npm >/dev/null 2>&1; then
        _info "${pkg_rel}: installing Node deps..."
        (cd "$PKG_DIR" && npm install --silent >>"${LOG_DIR}/install.log" 2>&1) && {
          echo "$PKG_HASH" > "$PKG_STAMP"
          _ok "${pkg_rel}: Node deps installed"
        } || _warn "${pkg_rel}: npm install failed — see ${LOG_DIR}/install.log"
      else
        _warn "${pkg_rel}: npm not in PATH — Node deps not installed"
        _warn "Install Node.js 20+: https://nodejs.org or brew install node"
      fi
    else
      if [ ! -d "$NODE_MODULES" ]; then
        _warn "${pkg_rel}/node_modules missing — run without --check to install"
      else
        _warn "${pkg_rel}: package.json changed — run without --check to update"
      fi
    fi
  else
    _ok "${pkg_rel}: Node deps up-to-date"
  fi
done

# ──────────────────────────────────────────────────────────────────────────────
# RESULT
# ──────────────────────────────────────────────────────────────────────────────
echo ""
_ok "Perpetua-Tools requirements check complete"
echo ""
exit 0
