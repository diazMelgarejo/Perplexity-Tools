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
  sync-attribution-guard-scripts.sh; do
  install -m 0755 "$SCRIPT_DIR/$rel" "$target/scripts/git/$rel"
done

# Repo-local agent rule (Cursor Cloud).
mkdir -p "$target/.cursor/rules"
install -m 0644 "$source_root/.cursor/rules/no-commit-attribution.mdc" \
  "$target/.cursor/rules/no-commit-attribution.mdc" 2>/dev/null || true

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
