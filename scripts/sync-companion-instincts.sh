#!/usr/bin/env bash
# Imports ultrathink-system instincts → Perplexity-Tools on every session start.
# Idempotent. Local-first; clones companion repo if absent.
# Note: uses ultrathink-system's .ecc for instinct-cli.py (PT has no .ecc).

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PARENT_DIR="$(dirname "$REPO_ROOT")"

# 1. Find or clone ultrathink-system
UT_REPO=""
for p in "$PARENT_DIR/ultrathink-system" "$(dirname "$PARENT_DIR")/ultrathink-system"; do
  [[ -d "$p/.claude" ]] && { UT_REPO="$p"; break; }
done

if [[ -z "$UT_REPO" ]]; then
  git clone --depth 1 https://github.com/diazMelgarejo/ultrathink-system \
    "$PARENT_DIR/ultrathink-system" 2>/dev/null || exit 0
  UT_REPO="$PARENT_DIR/ultrathink-system"
fi

# 2. Find instinct-cli.py (from ultrathink's .ecc)
INSTINCT_CLI=""
for p in \
  "$UT_REPO/.ecc/skills/continuous-learning-v2/scripts/instinct-cli.py" \
  "${CLAUDE_PLUGIN_ROOT:-}/skills/continuous-learning-v2/scripts/instinct-cli.py"; do
  [[ -f "$p" ]] && { INSTINCT_CLI="$p"; break; }
done
[[ -z "$INSTINCT_CLI" ]] && exit 0

# 3. Import
YAML="$UT_REPO/.claude/homunculus/instincts/inherited/ultrathink-system-instincts.yaml"
[[ -f "$YAML" ]] || exit 0
python3 "$INSTINCT_CLI" import "$YAML" --force
