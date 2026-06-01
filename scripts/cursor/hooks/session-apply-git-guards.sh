#!/usr/bin/env bash
# Cursor sessionStart hook — install mandatory git hooks in every workspace git repo.
# Installed to ~/.cursor/openclaw/hooks/ by scripts/cursor/install-user-git-environment.sh
set -euo pipefail

HOME="${HOME:-/home/ubuntu}"
export HOME

input="$(cat)"

mapfile -t workspace_roots < <(
  REPO_ROOT="${REPO_ROOT:-}" \
  PERPETUA_TOOLS_PATH="${PERPETUA_TOOLS_PATH:-}" \
  python3 -c '
import json, os, sys

raw = sys.stdin.read()
try:
    data = json.loads(raw) if raw.strip() else {}
except json.JSONDecodeError:
    data = {}

roots = list(data.get("workspace_roots") or [])
for key in ("PERPETUA_TOOLS_PATH", "REPO_ROOT", "WORKSPACE_FOLDER"):
    val = os.environ.get(key, "").strip()
    if val and "${" not in val:
        roots.append(val)
for extra in ("/agent/repos/Perpetua-Tools", "/agent/repos/orama-system",
              "/agent/repos/AlphaClaw", "/agent/repos/periscope",
              os.path.expanduser("~/workspace")):
    roots.append(extra)

agent_repos = "/agent/repos"
if os.path.isdir(agent_repos):
    for name in sorted(os.listdir(agent_repos)):
        roots.append(os.path.join(agent_repos, name))

seen = set()
for r in roots:
    if not r or "${" in r:
        continue
    abs_r = os.path.abspath(os.path.expanduser(r))
    if abs_r in seen:
        continue
    seen.add(abs_r)
    print(abs_r)
' <<<"$input"
)

apply_repo() {
  local root="$1"
  [[ -d "$root/.git" ]] || return 0
  # shellcheck source=/dev/null
  if [[ -x "$root/scripts/git/neutralize-cursor-coauthor-hook.sh" ]]; then
    bash "$root/scripts/git/neutralize-cursor-coauthor-hook.sh" --repo "$root" >/dev/null 2>&1 || true
  elif [[ -f "$root/scripts/git/cursor-hooks-id.sh" ]]; then
    # shellcheck disable=SC1091
    source "$root/scripts/git/cursor-hooks-id.sh"
    ws_id="$(cursor_hooks_id "$root")"
    coauthor="${HOME}/.cursor/agent-hooks/${ws_id}/commit-msg.cursor.co-author"
    if [[ -f "$coauthor" ]]; then
      printf '%s\n' '#!/usr/bin/env bash' '# Neutralized — no Co-authored-by injection.' 'exit 0' >"$coauthor"
      chmod -x "$coauthor" 2>/dev/null || true
    fi
  fi
  if [[ -x "$root/scripts/git/install-local-hooks.sh" ]]; then
    bash "$root/scripts/git/install-local-hooks.sh" >/dev/null 2>&1 || true
  fi
  git -C "$root" config --local user.name "cyre" 2>/dev/null || true
  git -C "$root" config --local user.email "Lawrence@cyre.me" 2>/dev/null || true
}

pt_apply="${HOME}/.cursor/openclaw/git-guards/apply-all-repos.sh"
if [[ -x "$pt_apply" ]]; then
  bash "$pt_apply" || true
elif [[ -x "/agent/repos/Perpetua-Tools/scripts/git/apply-attribution-guard-all-repos.sh" ]]; then
  bash "/agent/repos/Perpetua-Tools/scripts/git/apply-attribution-guard-all-repos.sh" || true
fi

for root in "${workspace_roots[@]}"; do
  apply_repo "$root"
done

exit 0
