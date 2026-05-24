#!/usr/bin/env bash
# Resolve Cursor cloud-agent git hooks directory id (base64 of absolute repo path).
set -euo pipefail

cursor_hooks_id() {
  local repo_path="${1:?repo path required}"
  local abs
  abs="$(cd "$repo_path" && pwd)"
  python3 - "$abs" <<'PY'
import base64
import sys

print(base64.b64encode(sys.argv[1].encode()).decode().rstrip("="))
PY
}
