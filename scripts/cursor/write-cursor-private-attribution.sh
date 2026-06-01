#!/usr/bin/env bash
# Write gitignored Cursor-local attribution files (never committed).
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
PRIVATE_DIR="${REPO_ROOT}/.cursor/private"
PATTERNS="${PRIVATE_DIR}/banned-attribution-patterns"
GUIDE="${PRIVATE_DIR}/banned-attribution-local.md"
HOME_COPY="${HOME:-/home/ubuntu}/.cursor/openclaw/banned-attribution-local.md"
HOME_PATTERNS="${HOME:-/home/ubuntu}/.cursor/openclaw/banned-attribution-patterns"

mkdir -p "$PRIVATE_DIR" "$(dirname "$HOME_COPY")"
chmod 700 "$PRIVATE_DIR" 2>/dev/null || true

decode_b64() { printf '%s' "$1" | base64 -d 2>/dev/null || true; }

{
  echo "# Banned attribution tokens (one per line, case-insensitive substring match)"
  decode_b64 "ZGFydGguc2VyaW91cw=="
  decode_b64 "bmltYm9zYQ=="
} >"$PATTERNS"
chmod 600 "$PATTERNS"

cat >"$GUIDE" <<'GUIDE_EOF'
# Banned git attribution (Cursor-local — gitignored)

Token list: `.cursor/private/banned-attribution-patterns`

**Never** copy tokens from that file into tracked docs, commit messages, or GitHub.

**Primary author:** `cyre <Lawrence@cyre.me>` or `cyre <diazMelgarejo@gmail.com>` or
`Codex <codex@openai.com>` — not `Cursor Agent <cursoragent@cursor.com>`.

## Pre-push

```bash
bash scripts/git/scan-tracked-banned-tokens.sh
bash scripts/git/audit_attribution.sh 20
GIT_AUDIT_RANGE=origin/main..HEAD GIT_AUDIT_STRICT=1 bash scripts/git/audit_attribution.sh
bash scripts/git/publish-clean-branch.sh <branch> main origin
```

## After history rewrite

```bash
git update-ref -d refs/original/refs/heads/<branch> 2>/dev/null || true
rm -rf .git/refs/original
git reflog expire --expire=now --all
git gc --prune=now
```
GUIDE_EOF
chmod 600 "$GUIDE"

install -m 0600 "$PATTERNS" "$HOME_PATTERNS" 2>/dev/null || cp "$PATTERNS" "$HOME_PATTERNS"
install -m 0600 "$GUIDE" "$HOME_COPY" 2>/dev/null || cp "$GUIDE" "$HOME_COPY"
chmod 600 "$HOME_PATTERNS" "$HOME_COPY" 2>/dev/null || true

printf 'OK: %s\n' "$PATTERNS"
printf 'OK: %s\n' "$GUIDE"
