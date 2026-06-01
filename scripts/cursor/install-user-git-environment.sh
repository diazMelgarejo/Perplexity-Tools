#!/usr/bin/env bash
# Cursor-only: install user-level sessionStart hook + git guards (idempotent).
# Safe on every cloud VM boot, Cursor agent install, and manual re-run.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
HOME="${HOME:-/home/ubuntu}"
export HOME

OPENCLAW_DIR="${HOME}/.cursor/openclaw"
GUARD_DIR="${OPENCLAW_DIR}/git-guards"
HOOK_DIR="${OPENCLAW_DIR}/hooks"
CURSOR_HOOKS_JSON="${HOME}/.cursor/hooks.json"
SESSION_HOOK="${REPO_ROOT}/scripts/cursor/hooks/session-apply-git-guards.sh"

log() { printf '>>> [install-user-git-environment] %s\n' "$*"; }

# Cursor cloud / agent install only (skip for non-Cursor automation if requested).
if [[ "${CURSOR_SKIP_GIT_GUARDS:-}" == "1" ]]; then
  log "CURSOR_SKIP_GIT_GUARDS=1 — skipping"
  exit 0
fi

mkdir -p "$GUARD_DIR" "$HOOK_DIR"

install -m 0755 "${REPO_ROOT}/scripts/git/cursor-hooks-id.sh" "${GUARD_DIR}/cursor-hooks-id.sh"
install -m 0755 "${REPO_ROOT}/scripts/git/disable-cursor-commit-attribution.sh" "${GUARD_DIR}/disable-cursor-commit-attribution.sh"
install -m 0755 "${REPO_ROOT}/scripts/git/hooks/commit-msg.strip-coauthor" "${GUARD_DIR}/commit-msg.strip-coauthor"
install -m 0755 "${REPO_ROOT}/scripts/git/ensure_hooks_installed.sh" "${GUARD_DIR}/ensure_hooks_installed.sh"
install -m 0755 "${REPO_ROOT}/scripts/git/verify-git-guards.sh" "${GUARD_DIR}/verify-git-guards.sh"
install -m 0755 "$SESSION_HOOK" "${HOOK_DIR}/session-apply-git-guards.sh"

install -m 0755 "${REPO_ROOT}/scripts/git/apply-attribution-guard-all-repos.sh" "${GUARD_DIR}/apply-all-repos.sh"

python3 - "$CURSOR_HOOKS_JSON" "${HOOK_DIR}/session-apply-git-guards.sh" <<'PY'
import json
import sys
from pathlib import Path

dest = Path(sys.argv[1])
hook_script = sys.argv[2]
entry = {"command": hook_script, "timeout": 120}

if dest.is_file():
    cfg = json.loads(dest.read_text(encoding="utf-8"))
else:
    cfg = {"version": 1, "hooks": {}}

cfg.setdefault("version", 1)
hooks = cfg.setdefault("hooks", {})
existing = [
    h
    for h in (hooks.get("sessionStart") or [])
    if not (
        isinstance(h, dict)
        and str(h.get("command", "")).endswith("session-apply-git-guards.sh")
    )
]
existing.append(entry)
hooks["sessionStart"] = existing

dest.parent.mkdir(parents=True, exist_ok=True)
dest.write_text(json.dumps(cfg, indent=2) + "\n", encoding="utf-8")
print(f"OK: {dest}")
PY

log "sessionStart hook → ${HOOK_DIR}/session-apply-git-guards.sh"

export PERPETUA_TOOLS_PATH="${PERPETUA_TOOLS_PATH:-$REPO_ROOT}"
export OPENCLAW_HOME="${OPENCLAW_HOME:-$HOME/openclaw-v1}"
export ORAMA_SYSTEM_PATH="${ORAMA_SYSTEM_PATH:-$OPENCLAW_HOME/orama-system}"
export ALPHACLAW_INSTALL_DIR="${ALPHACLAW_INSTALL_DIR:-$OPENCLAW_HOME/AlphaClaw}"

if [[ -x "${REPO_ROOT}/scripts/git/apply-attribution-guard-all-repos.sh" ]]; then
  log "apply repo guards (Perpetua-Tools + siblings)"
  bash "${REPO_ROOT}/scripts/git/apply-attribution-guard-all-repos.sh"
fi

ORAMA="${ORAMA_SYSTEM_PATH:-$REPO_ROOT/../orama-system}"
if [[ -x "${ORAMA}/scripts/cursor/write-openclaw-private-attribution.sh" ]]; then
  log "write user-level private attribution via orama-system"
  bash "${ORAMA}/scripts/cursor/write-openclaw-private-attribution.sh"
fi
if [[ -x "${REPO_ROOT}/scripts/cursor/sync-private-attribution-from-home.sh" ]]; then
  log "sync gitignored .cursor/private/ from ~/.cursor/openclaw"
  bash "${REPO_ROOT}/scripts/cursor/sync-private-attribution-from-home.sh"
fi

log "complete"
