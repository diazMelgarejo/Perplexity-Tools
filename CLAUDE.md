# Perpetua-Tools — Claude Code Mandatory Rules

> This file is loaded by Claude Code at the start of every session.
> All rules below are **non-negotiable** for every agent (ECC, AutoResearcher, Claude).
>
> **Repo renamed**: Perplexity-Tools → Perpetua-Tools (2026-04-20, trademark risk eliminated)
> GitHub: <https://github.com/diazMelgarejo/Perpetua-Tools>

---

## 1. Continuous Learning — Always On

Every session **must** use [continuous-learning-v2](https://github.com/affaan-m/everything-claude-code/tree/main/skills/continuous-learning-v2).

- **Read first**: Load `.claude/lessons/LESSONS.md` at session start — this is the shared knowledge base across all agents and sessions.
- **Write back**: Append meaningful discoveries, patterns, and decisions to `.claude/lessons/LESSONS.md` before ending a session.
- **Instinct path**: Repo instincts live at `.claude/homunculus/instincts/inherited/Perpetua-Tools-instincts.yaml`.

## 2. ECC Post-Merge Workflow (Mandatory)

After **any** ECC Tools PR is merged into this repo, immediately run:

```bash
# 1. Pull latest
git pull origin main

# 2. Import instincts (run in Claude Code)
/instinct-import .claude/homunculus/instincts/inherited/Perpetua-Tools-instincts.yaml

# 3. Verify
/instinct-status

# 4. Commit any changes written by the import
git add -A && git commit -m "chore(ecc): post-merge instinct import sync"
git push origin main
```

Or use the `/ecc-sync` command (`.claude/commands/ecc-sync.md`).

## 3. Shared Lessons Path

The canonical lessons file is **`docs/LESSONS.md`** (previously `.claude/lessons/LESSONS.md`, which now redirects here).

- ECC agents: read + write
- AutoResearcher agents: read + write
- Claude sessions: read at start, append before exit
- Auditable on GitHub at all times

| Resource | Purpose |
| --- | --- |
| [`SKILL.md`](SKILL.md) | Model selection rules + agent behavioral rules |
| [`docs/LESSONS.md`](docs/LESSONS.md) | Chronological session log — all agents, all dates |
| [`docs/wiki/README.md`](docs/wiki/README.md) | Wiki index — links to all lesson deep-dives |
| [`docs/wiki/07-multi-agent-collab.md`](docs/wiki/07-multi-agent-collab.md) | Version registry, scope claims, conflict recovery |

## 4. AutoResearcher Integration

Primary mode: **uditgoenka/autoresearch Claude Code plugin** (runs anywhere).
Secondary mode: GPU runner via SSH for `ml-experiment` task types (optional Verify substrate).

### Plugin install (one-time, idempotent)

```bash
claude plugin marketplace add uditgoenka/autoresearch
claude plugin install autoresearch@autoresearch
```

### Activation (per session)

```ascii
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
- Cross-reference orama-system's `.claude/lessons/LESSONS.md` for joint context
- `AUTORESEARCH_REMOTE` env var selects the fork (default: uditgoenka/autoresearch)
- `AUTORESEARCH_BRANCH` env var selects the default sync branch (default: main)

## 5. Repository Identity

- **Package**: `@diazmelgarejo/perpetua-tools@0.9.9.8`
- **Role**: Middleware / Adapters / Tooling (Layer 2 of the three-repo architecture)
- **AlphaClaw dependency**: drives AlphaClaw via CLI + HTTP only — NEVER via `require()` or internal imports
- **Companion repos**:
  - [AlphaClaw](https://github.com/diazMelgarejo/AlphaClaw) (Layer 1 — infrastructure, managed dependency)
  - [orama-system](https://github.com/diazMelgarejo/orama-system) (Layer 3 — orchestration, meta-intelligence)
- **Skill**: `.claude/skills/Perpetua-Tools/SKILL.md`
- **Mother skill**: n/a (PT is the adapter/middleware layer)

## 6. Three-Repo Architecture (read before any significant work)

```ascii
AlphaClaw (Layer 1 — infrastructure)
    │  CLI + HTTP only (no internal imports)
    ▼
Perpetua-Tools (Layer 2 — THIS REPO — middleware/adapters)
    │  typed adapter contracts
    ▼
orama-system (Layer 3 — orchestration/meta-intelligence)
```

### What lives in PT

| Path | Purpose |
|------|---------|
| `packages/alphaclaw-adapter/src/mcp/server.js` | MCP server (stdio) for AlphaClaw — register with `claude mcp add` |
| `packages/alphaclaw-adapter/src/index.js` | AlphaClaw HTTP+CLI adapter (Gate 1 stub) |
| `packages/local-agents/src/client.js` | Ollama + LM Studio unified client |
| `packages/local-agents/src/orchestrator.js` | Task dispatcher for local agents |
| `packages/local-agents/tests/client.test.js` | Vitest unit tests (fully offline) |
| `packages/mcpb-agents/` | Gate 2: `.mcpb` process-per-model definitions |
| `orchestrator/` | Python orchestration: control_plane, model_registry, lan_discovery, cost_guard |
| `orchestrator/ultrathink_bridge.py` | Bridge to orama-system (rename target: orama_bridge.py) |
| `config/` | devices.yml, models.yml, routing.yml |
| `docs/adapter-interface-contract.md` | Living API contract — update after every AlphaClaw upstream merge |

### Key invariants

- PT drives AlphaClaw via `GET /health`, `GET /api/status`, `POST /api/gateway/restart`, etc. — see `docs/adapter-interface-contract.md`
- `ALPHACLAW_ROOT` env var tells PT where AlphaClaw is installed (default: sibling directory)
- No patch proposed by local agents is applied without Claude review (`proposeCodeEdit` returns diff only)
- All local agent backends: Ollama at `127.0.0.1:11435`, LM Studio at `192.168.254.101:1234`

### MCP server registration (after Gate 1)

```bash
cd /path/to/Perpetua-Tools
claude mcp add --transport stdio alphaclaw -- node packages/alphaclaw-adapter/src/mcp/server.js
```

### Running local agent tests

```bash
cd packages/local-agents
node --experimental-vm-modules ../../node_modules/.bin/vitest run
```

## 7. gstack

gstack v1.3 is the agent skill framework for web browsing, planning, and review.

**Rules:**

- ALWAYS use `/browse` for web browsing — NEVER `mcp__Claude_in_Chrome__*` directly
- Use `/plan-eng-review` before any Gate 0→1 transition
- Use `/ship` before any `npm publish`

Install: `bash scripts/install-gstack.sh` (requires bun). See AlphaClaw `CLAUDE.md §gstack` for full skill table.
