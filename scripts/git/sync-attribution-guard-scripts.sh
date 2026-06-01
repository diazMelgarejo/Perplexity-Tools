#!/usr/bin/env bash
# Copy attribution-guard scripts from orama-system into a sibling repo checkout.
set -euo pipefail

target="${1:?target repo path required}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source_root="$(cd "$SCRIPT_DIR/../.." && pwd)"

if [[ ! -d "$target/.git" ]]; then
  echo "skip: not a git repo: $target" >&2
  exit 0
fi

target="$(cd "$target" && pwd)"
mkdir -p "$target/scripts/git/hooks"

for rel in \
  cursor-hooks-id.sh \
  hooks/commit-msg.strip-coauthor \
  disable-cursor-commit-attribution.sh \
  commit-clean.sh \
  apply-attribution-guard-all-repos.sh \
  sync-attribution-guard-scripts.sh \
  sync-banned-patterns-to-repo.sh; do
  [[ -f "$SCRIPT_DIR/$rel" ]] || continue
  install -m 0755 "$SCRIPT_DIR/$rel" "$target/scripts/git/$rel"
done

# Thin wrapper — full implementation lives in Perpetua-Tools (canonical).
cat >"$target/scripts/git/daily-attribution-guard.sh" <<'WRAP'
#!/usr/bin/env bash
set -euo pipefail
PT="${PERPETUA_TOOLS_PATH:-/agent/repos/Perpetua-Tools}"
exec bash "$PT/scripts/git/daily-attribution-guard.sh"
WRAP
chmod +x "$target/scripts/git/daily-attribution-guard.sh"

# Repo-local agent rules (Cursor Cloud) — no forbidden tokens in these files.
mkdir -p "$target/.cursor/rules"
for rule in no-commit-attribution.mdc never-undo-attribution-expunge.mdc banned-attribution-local.mdc; do
  [[ -f "$source_root/.cursor/rules/$rule" ]] || continue
  install -m 0644 "$source_root/.cursor/rules/$rule" "$target/.cursor/rules/$rule"
done

echo "synced guard scripts → $target"

snippet="$source_root/scripts/git/snippets/AGENTS-cursor-cloud-git.md"
if [[ -f "$snippet" ]]; then
  if [[ ! -f "$target/AGENTS.md" ]]; then
    {
      echo "# Agent instructions"
      echo
      cat "$snippet"
    } >"$target/AGENTS.md"
  elif ! grep -q 'apply-attribution-guard-all-repos' "$target/AGENTS.md" 2>/dev/null; then
    {
      echo
      cat "$snippet"
    } >>"$target/AGENTS.md"
  fi
fi
