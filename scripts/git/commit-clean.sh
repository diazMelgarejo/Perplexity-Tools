#!/usr/bin/env bash
# Create a commit without running git commit hooks (avoids Cursor co-author injection).
set -euo pipefail

usage() {
  cat <<'EOF'
Usage: scripts/git/commit-clean.sh -m "message" [--amend]

Stages must already reflect the desired tree (git add …).
Uses git commit-tree so Cursor commit-msg hooks never run.

Environment overrides: GIT_AUTHOR_NAME, GIT_AUTHOR_EMAIL
EOF
}

repo_root="$(git rev-parse --show-toplevel 2>/dev/null)" || {
  echo "error: not inside a git repository" >&2
  exit 1
}
cd "$repo_root"

message=""
amend=0
while [[ $# -gt 0 ]]; do
  case "$1" in
    -m)
      message="${2:-}"
      shift 2
      ;;
    --amend)
      amend=1
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "error: unknown argument: $1" >&2
      usage
      exit 1
      ;;
  esac
done

[[ -n "$message" ]] || {
  echo "error: -m message is required" >&2
  usage
  exit 1
}

author_name="${GIT_AUTHOR_NAME:-$(git config user.name)}"
author_email="${GIT_AUTHOR_EMAIL:-$(git config user.email)}"
[[ -n "$author_name" && -n "$author_email" ]] || {
  echo "error: configure user.name and user.email or set GIT_AUTHOR_*" >&2
  exit 1
}
author_email_lc="$(printf '%s' "$author_email" | tr '[:upper:]' '[:lower:]')"
author_domain_ok() {
  local email_lc="$1"
  local domain="${email_lc#*@}"
  [[ -z "$domain" || "$domain" == "$email_lc" ]] && return 1
  case "$domain" in
    openai.com|*.openai.com|anthropic.com|*.anthropic.com|cursor.com|*.cursor.com|cursor.sh|*.cursor.sh|google.com|*.google.com|google.dev|*.google.dev|github.com|*.github.com|microsoft.com|*.microsoft.com|azure.com|*.azure.com|perplexity.ai|*.perplexity.ai|x.ai|*.x.ai)
      return 0
      ;;
  esac
  return 1
}
case "$author_email_lc" in
  diazmelgarejo@gmail.com|lawrence@cyre.me|codex@openai.com)
    ;;
  *)
    if ! author_domain_ok "$author_email_lc"; then
      echo "error: commit author email must be diazMelgarejo@gmail.com, Lawrence@cyre.me, codex@openai.com, or a well-known AI/vendor domain" >&2
      exit 1
    fi
    ;;
esac

if git diff-index --quiet HEAD -- 2>/dev/null && [[ "$amend" -eq 0 ]]; then
  if git diff-index --quiet --cached HEAD -- 2>/dev/null; then
    echo "error: nothing staged to commit" >&2
    exit 1
  fi
fi

tree="$(git write-tree)"
if [[ "$amend" -eq 1 ]]; then
  parent="$(git rev-parse HEAD^)"
else
  if git rev-parse HEAD >/dev/null 2>&1; then
    parent="$(git rev-parse HEAD)"
  else
    parent=""
  fi
fi

if [[ -n "$parent" ]]; then
  new_sha="$(
    printf '%s\n' "$message" |
      GIT_AUTHOR_NAME="$author_name" GIT_AUTHOR_EMAIL="$author_email" \
      git commit-tree "$tree" -p "$parent" -F -
  )"
else
  new_sha="$(
    printf '%s\n' "$message" |
      GIT_AUTHOR_NAME="$author_name" GIT_AUTHOR_EMAIL="$author_email" \
      git commit-tree "$tree" -F -
  )"
fi

branch="$(git symbolic-ref --short HEAD 2>/dev/null || true)"
if [[ -n "$branch" ]]; then
  git update-ref "refs/heads/${branch}" "$new_sha"
else
  git update-ref HEAD "$new_sha"
fi

git reset --hard "$new_sha" >/dev/null
echo "$new_sha"
