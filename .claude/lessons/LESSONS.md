# Lessons — Shared Knowledge Base

> **Canonical path**: `.claude/lessons/LESSONS.md` (same in PT and ultrathink-system)
> **Purpose**: GitHub-auditable persistent memory across all ECC, AutoResearcher, and Claude sessions.
>
> **Rules**:
> - Read this file at the start of every session
> - Append new learnings before ending a session
> - Keep entries dated and agent-tagged
> - Cross-reference companion repo: [ultrathink-system/.claude/lessons/LESSONS.md](https://github.com/diazMelgarejo/ultrathink-system/blob/main/.claude/lessons/LESSONS.md)

## continuous-learning-v2

This repo uses [continuous-learning-v2](https://github.com/affaan-m/everything-claude-code/tree/main/skills/continuous-learning-v2) for all agents.
Instincts: `.claude/homunculus/instincts/inherited/Perplexity-Tools-instincts.yaml`
Import command: `/instinct-import .claude/homunculus/instincts/inherited/Perplexity-Tools-instincts.yaml`

---

## Sessions Log

<!-- Append entries below. Format:
## YYYY-MM-DD — <agent: ECC | AutoResearcher | Claude> — <brief topic>
### What was learned
- bullet points
### Decisions made
- bullet points
### Open questions
- bullet points
-->

---

## 2026-04-07 — Claude — Idempotent installs: subprocess permissions + model auto-discovery

### What was learned

- **`capture_output=True` silences bootstrap scripts** — never use it in user-facing install flows; let stdout/stderr stream through so the user can see progress and errors
- **`npm install -g` does not guarantee execute bits** on all platforms/nvm configs — the installed binary exists and is found by `shutil.which()` but raises `PermissionError: [Errno 13]` when Python tries to execute it via `subprocess.run()`
- **`PermissionError` is NOT a `subprocess.CalledProcessError`** — must be caught separately; an unhandled `PermissionError` crashes the entire bootstrap with a traceback instead of a clean error message
- **Hardcoded model names break inference** — LM Studio returns `400 Bad Request` and Ollama returns `404 Not Found` when the configured model isn't loaded; always resolve via `GET /v1/models` (LM Studio) or `GET /api/tags` (Ollama) before sending inference requests
- **Windows GPU models cannot be called on Mac memory** — Windows LM Studio at `192.168.254.103:1234` must be called remotely over LAN; `192.168.254.101:1234` is Mac's own LM Studio instance — never cross these
- **AgentTracker `agents.json` must not share path with routing state** — flat routing dicts (`{"mode": "distributed"}`) cause `AgentRecord(**v)` to raise `TypeError: argument after ** must be a mapping, not str`; `_load()` must `isinstance(v, dict)` guard every entry

### Decisions made

- `_resolve_ollama_model()` and `_resolve_lmstudio_model()` added to `scripts/launch_researchers.py` — called at startup of each researcher before `tracker.register()`; remap to first available model if preferred is absent
- `openclaw_bootstrap.py` auto-`chmod +x` the openclaw binary immediately after `npm install -g` if execute bit is missing
- `AgentTracker._load()` now skips non-dict entries and rewrites the file clean rather than crashing

### Prevention Rules (encode in all future idempotent installs)

1. No `capture_output=True` in bootstrap/install subprocess calls
2. After `npm install -g <pkg>`, always verify and fix `S_IXUSR` before running the binary
3. Catch `PermissionError` separately from `CalledProcessError` in every subprocess block
4. Never hardcode model names — query `/v1/models` or `/api/tags` at runtime
5. Keep AgentTracker's `agents.json` on a distinct path from any routing/config state file
6. All typed-record `_load()` methods must `isinstance(v, dict)` before `**v` unpacking

### Commits
- `3c9a4a8` (UTS) — fix(bootstrap): handle PermissionError + auto chmod +x after npm install
- `23bd01d` (UTS) — fix(bootstrap): remove capture_output=True
- `ffb1be0` (PT)  — fix(researchers): auto-discover loaded model via /v1/models + /api/tags
- `d9e4f50` (PT)  — fix(tracker): handle stale routing data in agents.json
