# Perplexity-Tools — Claude Code Mandatory Rules

> This file is loaded by Claude Code at the start of every session.
> All rules below are **non-negotiable** for every agent (ECC, AutoResearcher, Claude).

---

## 1. Continuous Learning — Always On

Every session **must** use [continuous-learning-v2](https://github.com/affaan-m/everything-claude-code/tree/main/skills/continuous-learning-v2).

- **Read first**: Load `.claude/lessons/LESSONS.md` at session start — this is the shared knowledge base across all agents and sessions.
- **Write back**: Append meaningful discoveries, patterns, and decisions to `.claude/lessons/LESSONS.md` before ending a session.
- **Instinct path**: Repo instincts live at `.claude/homunculus/instincts/inherited/Perplexity-Tools-instincts.yaml`.

## 2. ECC Post-Merge Workflow (Mandatory)

After **any** ECC Tools PR is merged into this repo, immediately run:

```bash
# 1. Pull latest
git pull origin main

# 2. Import instincts (run in Claude Code)
/instinct-import .claude/homunculus/instincts/inherited/Perplexity-Tools-instincts.yaml

# 3. Verify
/instinct-status

# 4. Commit any changes written by the import
git add -A && git commit -m "chore(ecc): post-merge instinct import sync"
git push origin main
```

Or use the `/ecc-sync` command (`.claude/commands/ecc-sync.md`).

## 3. Shared Lessons Path

The canonical lessons file is `.claude/lessons/LESSONS.md` — **same relative path in both PT and ultrathink-system**.

- ECC agents: read + write
- AutoResearcher agents: read + write
- Claude sessions: read at start, append before exit
- Auditable on GitHub at all times

## 4. AutoResearcher Integration

Primary mode: **uditgoenka/autoresearch Claude Code plugin** (runs anywhere).
Secondary mode: GPU runner via SSH for `ml-experiment` task types (optional Verify substrate).

### Plugin install (one-time, idempotent)
```bash
claude plugin marketplace add uditgoenka/autoresearch
claude plugin install autoresearch@autoresearch
```

### Activation (per session)
```
/autoresearch          # start a research loop
/autoresearch:debug    # verbose mode with reasoning trace
```

### Bridge (secondary GPU path — ml-experiment only)
```python
from orchestrator.autoresearch_bridge import preflight, is_gpu_idle
# Always check GPU lock before dispatching — Windows loads ONE model at a time
if is_gpu_idle():
    preflight(run_tag="my-experiment")
```

When running AutoResearcher swarms:
- Read `.claude/lessons/LESSONS.md` for prior experiment context
- Record new findings in `.claude/lessons/LESSONS.md` under a dated session entry
- Cross-reference ultrathink-system's `.claude/lessons/LESSONS.md` for joint context
- `AUTORESEARCH_REMOTE` env var selects the fork (default: uditgoenka/autoresearch)
- `AUTORESEARCH_BRANCH` env var selects the default sync branch (default: main)

## 5. Repository Identity

- **Role**: Top-level orchestrator (Repo #1) — hardware-aware model routing, fallback chains
- **Companion repo**: [ultrathink-system](https://github.com/diazMelgarejo/ultrathink-system) (Repo #2)
- **Skill**: `.claude/skills/Perplexity-Tools/SKILL.md`
- **Mother skill**: n/a (PT is the orchestrator)
