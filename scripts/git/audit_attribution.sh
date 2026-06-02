#!/usr/bin/env bash
# Scan commits for Co-authored-by policy, non-approved authors, and banned attribution.
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
cd "$REPO_ROOT"
# shellcheck source=banned_attribution_lib.sh
source "$SCRIPT_DIR/banned_attribution_lib.sh"

N="${1:-79}"
HOOK="$REPO_ROOT/scripts/git/check_commit_message.sh"

ALLOWED_HUMAN_AE="diazmelgarejo@gmail.com lawrence@cyre.me codex@openai.com"
ALLOWED_BOT_ORAMA="cursor[bot]@users.noreply.github.com"
ALLOWED_BOT_PT="dependabot[bot]@users.noreply.github.com coderabbitai[bot]@users.noreply.github.com"
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
  local an_lc="$2"
  if [[ "$ae_lc" == "cursoragent@cursor.com" ]] || [[ "$an_lc" == *cursor*agent* ]]; then
    return 1
  fi
  if [[ "$ae_lc" == *"[bot]@users.noreply.github.com" ]]; then
    return 0
  fi
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

banned_attribution_hit() {
  local ae_lc="$1" an_lc="$2" ce_lc="$3" cn_lc="$4" body_lc="$5"
  if ! banned_patterns_ready "$REPO_ROOT"; then
    return 1
  fi
  line_matches_banned_pattern "$ae_lc" "$REPO_ROOT" && return 0
  line_matches_banned_pattern "$an_lc" "$REPO_ROOT" && return 0
  line_matches_banned_pattern "$ce_lc" "$REPO_ROOT" && return 0
  line_matches_banned_pattern "$cn_lc" "$REPO_ROOT" && return 0
  local line
  while IFS= read -r line; do
    line_lc="$(printf '%s' "$line" | tr '[:upper:]' '[:lower:]')"
    case "$line_lc" in
      co-authored-by:*)
        if line_matches_banned_pattern "$line_lc" "$REPO_ROOT"; then
          return 0
        fi
        ;;
    esac
  done <<< "$body_lc"
  return 1
}

refs=(HEAD main origin/main)
for ref in "${refs[@]}"; do
  sha=$(git rev-parse -q --verify "$ref" 2>/dev/null) || { printf '%s\tMISSING\t-\t-\t-\t-\n' "$ref"; continue; }
  banned=0 bad_author=0 bad_co=0 count=0
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
    if banned_attribution_hit "$ae_lc" "$an_lc" "$ce_lc" "$cn_lc" "$body_lc"; then
      banned=$((banned+1))
    fi
    if ! author_ok "$ae_lc" "$an_lc"; then
      bad_author=$((bad_author+1))
    fi
    if [[ -x "$HOOK" ]] && ! "$HOOK" "$tmp" >/dev/null 2>&1; then
      bad_co=$((bad_co+1))
    fi
    rm -f "$tmp"
  done < <(git log -"$N" --format=%H "$ref" 2>/dev/null)
  clean=no
  [[ $banned -eq 0 && $bad_author -eq 0 && $bad_co -eq 0 ]] && clean=yes
  printf '%s\t%s\tbanned=%s\tbad_author=%s\tbad_coauthor=%s\tcommits=%s\tclean=%s\trepo_bot=%s\n' \
    "$ref" "${sha:0:12}" "$banned" "$bad_author" "$bad_co" "$count" "$clean" "${PREFERRED_BOT:-any}"
done

if [[ -n "${GIT_AUDIT_RANGE:-}" ]]; then
  range_banned=0 range_bad_author=0 range_bad_co=0 range_count=0
  while read -r h; do
    range_count=$((range_count + 1))
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
    if banned_attribution_hit "$ae_lc" "$an_lc" "$ce_lc" "$cn_lc" "$body_lc"; then
      range_banned=$((range_banned + 1))
      echo "banned_attribution: $h $(git log -1 --oneline "$h")" >&2
    fi
    if ! author_ok "$ae_lc" "$an_lc"; then
      range_bad_author=$((range_bad_author + 1))
      echo "bad_author: $h $an <$ae>" >&2
    fi
    if [[ -x "$HOOK" ]] && ! "$HOOK" "$tmp" >/dev/null 2>&1; then
      range_bad_co=$((range_bad_co + 1))
      echo "bad_coauthor: $h $(git log -1 --oneline "$h")" >&2
    fi
    rm -f "$tmp"
  done < <(git rev-list "${GIT_AUDIT_RANGE}" 2>/dev/null)
  printf 'RANGE\t%s\tbanned=%s\tbad_author=%s\tbad_coauthor=%s\tcommits=%s\tclean=%s\n' \
    "$GIT_AUDIT_RANGE" "$range_banned" "$range_bad_author" "$range_bad_co" "$range_count" \
    "$([[ $range_banned -eq 0 && $range_bad_author -eq 0 && $range_bad_co -eq 0 ]] && echo yes || echo no)"
  if [[ "${GIT_AUDIT_STRICT:-}" == "1" ]] \
    && [[ $range_banned -ne 0 || $range_bad_author -ne 0 || $range_bad_co -ne 0 ]]; then
    exit 1
  fi
fi
