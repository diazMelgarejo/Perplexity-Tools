#!/usr/bin/env bash
# Overwrite Cursor commit-msg.cursor.co-author with a no-op (chmod -x is insufficient).
set -euo pipefail

usage() {
  cat <<'EOF'
Usage:
  neutralize-cursor-coauthor-hook.sh <path-to-commit-msg.cursor.co-author>
  neutralize-cursor-coauthor-hook.sh --all-agent-hooks
  neutralize-cursor-coauthor-hook.sh --repo <git-repo-root>
EOF
}

noop_body() {
  cat <<'EOF'
#!/usr/bin/env bash
# Neutralized by Perpetua-Tools git guards — never inject Co-authored-by trailers.
exit 0
EOF
}

neutralize_file() {
  local hook="$1"
  [[ -n "$hook" ]] || return 0
  [[ -f "$hook" ]] || return 0
  noop_body >"$hook"
  chmod -x "$hook" 2>/dev/null || true
  echo "neutralized: $hook"
}

neutralize_all_agent_hooks() {
  local root="${HOME:-}/.cursor/agent-hooks"
  [[ -d "$root" ]] || return 0
  local f
  while IFS= read -r -d '' f; do
    neutralize_file "$f"
  done < <(find "$root" -name 'commit-msg.cursor.co-author' -type f -print0 2>/dev/null)
}

neutralize_repo() {
  local repo="$1"
  local script_dir hook_id
  script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
  # shellcheck source=cursor-hooks-id.sh
  source "$script_dir/cursor-hooks-id.sh"
  hook_id="$(cursor_hooks_id "$repo")"
  neutralize_file "${HOME:-}/.cursor/agent-hooks/${hook_id}/commit-msg.cursor.co-author"
}

case "${1:-}" in
  --all-agent-hooks)
    neutralize_all_agent_hooks
    ;;
  --repo)
    [[ -n "${2:-}" ]] || { usage; exit 1; }
    neutralize_repo "$2"
    ;;
  -h|--help|'')
    usage
    exit 0
    ;;
  *)
    neutralize_file "$1"
    ;;
esac
