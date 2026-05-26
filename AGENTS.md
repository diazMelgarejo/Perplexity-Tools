# Agent instructions — Perpetua-Tools

Follow `CLAUDE.md` for repository architecture, runtime boundaries, and
workflow navigation. This file adds cross-agent guardrails that apply to all AI
coding agents working in this repo.

## Prime directives for agent-maintained records

- Treat vulnerability memory, lessons, audits, and review ledgers as append-only
  historical records. Do not erase, delete, replace, truncate, or rewrite prior
  entries unless the user explicitly instructs that exact destructive action.
- When a record is stale, defunct, remediated, duplicated, or superseded, update
  it additively: add or change status/notes/feedback fields, append a follow-up
  entry, or link to the replacement. Preserve the original evidence and dates.
- For JSON records, load and write with structured parsers (`json.load` /
  `json.dump(..., indent=4)` in Python). Never hand-edit by string
  concatenation, ad hoc patches, or regex substitutions.
- Before any destructive or ambiguity-prone record operation, use
  AskUserQuestions: ask the user which record to change, what status to apply,
  and whether deletion/replacement is truly intended.

## Git attribution

- Use the repo git hooks in `scripts/git/` when available.
- Primary author may be one of the approved owner emails or an approved
  well-known AI author such as `Codex <codex@openai.com>`.
- `Co-authored-by` may include well-known public AI/helper domains and markers
  (`openai.com`, `anthropic.com`, `cursor.com`, `cursor.sh`, `google.com`,
  `github.com`, `microsoft.com`, `azure.com`, subdomains; `codex`, `claude`,
  `anthropic`, `cursor`, etc.).
- Random or unattributable Gmail co-authors are blocked. Only the approved owner
  Gmail addresses may appear in `Co-authored-by`.
