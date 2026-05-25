#!/usr/bin/env bash
# Scan last N commits on refs for Co-authored-by policy, non-approved authors, and VERBOTEN identities.
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
cd "$REPO_ROOT"
N="${1:-79}"
HOOK="$REPO_ROOT/scripts/git/check_commit_message.sh"

# Human primary authors allowed in history scans (lowercase).
ALLOWED_HUMAN_AE="diazmelgarejo@gmail.com lawrence@cyre.me codex@openai.com"

# Bot committers — never count as bad_author (repo-specific + union for shared tooling).
ALLOWED_BOT_ORAMA="cursor[bot]@users.noreply.github.com"
ALLOWED_BOT_PT="dependabot[bot]@users.noreply.github.com"
ALLOWED_BOT_EMAILS="$ALLOWED_BOT_ORAMA $ALLOWED_BOT_PT"

repo_name="$(basename "$REPO_ROOT")"
if [[ "$repo_name" == "orama-system" ]]; then
  PREFERRED_BOT="$ALLOWED_BOT_ORAMA"
elif [[ "$repo_name" == "Perpetua-Tools" ]]; then
  PREFERRED_BOT="$ALLOWED_BOT_PT"
else
  PREFERRED_BOT=""
fi

author_ok() {
  local ae_lc="$1"
  local bot
  for bot in $ALLOWED_BOT_EMAILS; do
    [[ "$ae_lc" == "$(printf '%s' "$bot" | tr '[:upper:]' '[:lower:]')" ]] && return 0
  done
  local h
  for h in $ALLOWED_HUMAN_AE; do
    [[ "$ae_lc" == "$h" ]] && return 0
  done
  return 1
}

verboten_hit() {
  local ae_lc="$1" an_lc="$2" ce_lc="$3" cn_lc="$4" body_lc="$5"
  if [[ "$ae_lc" == *darth.serious* || "$ce_lc" == *darth.serious* ]]; then return 0; fi
  if [[ "$an_lc" == *nimbosa* || "$cn_lc" == *nimbosa* ]]; then return 0; fi
  if [[ "$ae_lc" == *nimbosa* || "$ce_lc" == *nimbosa* ]]; then return 0; fi
  local line
  while IFS= read -r line; do
    line_lc="$(printf '%s' "$line" | tr '[:upper:]' '[:lower:]')"
    case "$line_lc" in
      co-authored-by:*darth.serious*|co-authored-by:*nimbosa*) return 0 ;;
    esac
  done <<< "$body_lc"
  return 1
}

refs=(HEAD main origin/main)
for ref in "${refs[@]}"; do
  sha=$(git rev-parse -q --verify "$ref" 2>/dev/null) || { printf '%s\tMISSING\t-\t-\t-\t-\n' "$ref"; continue; }
  verboten=0 bad_author=0 bad_co=0 count=0
  while read -r h; do
    count=$((count+1))
    tmp=$(mktemp)
    git log -1 --format=%B "$h" > "$tmp"
    ae=$(git log -1 --format=%ae "$h")
    ce=$(git log -1 --format=%ce "$h")
    an=$(git log -1 --format=%an "$h")
    cn=$(git log -1 --format=%cn "$h")
    ae_lc="$(printf '%s' "$ae" | tr '[:upper:]' '[:lower:]')"
    ce_lc="$(printf '%s' "$ce" | tr '[:upper:]' '[:lower:]')"
    an_lc="$(printf '%s' "$an" | tr '[:upper:]' '[:lower:]')"
    cn_lc="$(printf '%s' "$cn" | tr '[:upper:]' '[:lower:]')"
    body_lc="$(cat "$tmp" | tr '[:upper:]' '[:lower:]')"
    if verboten_hit "$ae_lc" "$an_lc" "$ce_lc" "$cn_lc" "$body_lc"; then
      verboten=$((verboten+1))
    fi
    if ! author_ok "$ae_lc"; then
      bad_author=$((bad_author+1))
    fi
    if [[ -x "$HOOK" ]] && ! "$HOOK" "$tmp" >/dev/null 2>&1; then
      bad_co=$((bad_co+1))
    fi
    rm -f "$tmp"
  done < <(git log -"$N" --format=%H "$ref" 2>/dev/null)
  clean=no
  [[ $verboten -eq 0 && $bad_author -eq 0 && $bad_co -eq 0 ]] && clean=yes
  printf '%s\t%s\tverboten=%s\tbad_author=%s\tbad_coauthor=%s\tcommits=%s\tclean=%s\trepo_bot=%s\n' \
    "$ref" "${sha:0:12}" "$verboten" "$bad_author" "$bad_co" "$count" "$clean" "${PREFERRED_BOT:-any}"
done
