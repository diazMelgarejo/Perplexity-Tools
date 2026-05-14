# Perpetua-Tools — Claude Code Mandatory Rules

> This file is loaded by Claude Code at the start of every session.
> All rules below are **non-negotiable** for every agent (ECC, AutoResearcher, Claude).
>
> **Repo renamed**: Perplexity-Tools → Perpetua-Tools (2026-04-20, trademark risk eliminated)
> GitHub: <https://github.com/diazMelgarejo/Perpetua-Tools>

---

## § 0 — ABSOLUTE ARCHITECTURAL CONTRACTS (Never Change Without Full Contract Revision)

*Source: `orama-system/docs/2026-05-14--UNIFIED-ABSORPTION-PLAN.md` §§ 1–2.*
*Lockstep with orama-system `CLAUDE.md § 0` (commit `38ec5d9`). Both must stay in sync.*

### Terminology (enforced — grep must return 0 hits in active code)
| **Banned** | **Correct** | Scope |
|---|---|---|
| `coordinator` / `Coordinator` as a role name | `orchestrator` | All APIs, schemas, config keys, route names, doc headings |
| `Perplexity-Tools` | `Perpetua-Tools` | All active `.py`, config, non-historical docs |
| `deviceaffinity` | `affinity` | All JSON/YAML config, Python readers |
| `qwen3-coder:14b` | (no default — must be explicit or fail) | Env defaults, any hardcoded model string |
| `WIN_LM_STUDIO_HOST` / `WIN_LM_STUDIO_PORT` | `LM_STUDIO_WIN_ENDPOINTS` | Env vars, backend config |

### Eight governing principles
1. **"Orchestrator" is the only public control-plane term.** "Coordinator" may appear in prose comments explaining behavior, never in any public API, schema field, config key, route, or doc heading.
2. **Workers are one generic primitive.** All roles (executor, verifier, crystallizer, etc.) are specializations of `TaskEnvelope in → WorkerResult out`. One template, many overlays.
3. **PT is the runtime/state authority.** PT owns: job queue, hardware affinity, model routing, GPU safety, LAN routing, durable artifacts, session state. orama never holds durable state.
4. **orama is the methodology/planning authority.** orama owns: stage planning, role templates, prompt contracts, verification rubrics. It is stateless. It returns plans and summaries.
5. **Fail closed at gateways — discovery tools degrade gracefully.** `api_server.py` fails closed on missing `PERPETUATOOLSROOT` or affinity violations. `discover.py` and the network watcher warn and continue.
6. **Workers do not spawn sub-workers in V1.** `depth=0` validated server-side on `JobSpec` and `TaskEnvelope` — not a convention.
7. **JSON/Pydantic is the wire format. XML/tags are prompt-rendering only.** Never parse XML as Python inter-process protocol.
8. **Lockstep commits for shared contracts.** Any change to shared schema fields, exception classes, policy keys, or model IDs commits to both repos in the same session.

### Hardware routing invariants
- **`lmstudio-mac.baseUrl` is always `http://localhost:1234/v1`.** Mac LAN IP is discovery metadata only — written to `devices.yml.lan_ip` for documentation and Windows-side routing. Never in any Mac-local config.
- **Win host from env only.** `LM_STUDIO_WIN_ENDPOINTS` is the single env var (full URL). Default must be invalid so misconfiguration fails loudly. Never hardcode an IP.
- **One heavy model at a time on Windows GPU.** `asyncio.Lock` on `LMStudioWinBackend` for heavy models. Check `GPU: BUSY` in `swarm_state.md` before dispatching.

### Shared types ownership (PT is authoritative)
- All five shared types (`OrchestrationSession`, `TaskEnvelope`, `WorkerAssignment`, `WorkerResult`, `VerificationResult`) live in **PT** (`orchestrator/contracts.py`).
- orama imports them from PT. Never the reverse.
- All validators use Pydantic V2 `@field_validator`, never deprecated `@validator`.

### Verifier gate
- Crystallization is **never dispatched** without an approved `VerificationResult`.
- Enforced in code (`dispatch_crystallization` raises `PermissionError` if `verdict != "approved"`).

### V1 scope boundary
- MAESTRO/HITL gates and IDE session API are **deferred to v2**. Do not implement in v1.

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
| `orchestrator/orama_bridge.py` | Bridge to orama-system |
| `config/` | devices.yml, models.yml, routing.yml |
| `docs/adapter-interface-contract.md` | Living API contract — update after every AlphaClaw upstream merge |

### Key invariants

- PT drives AlphaClaw via `GET /health`, `GET /api/status`, `POST /api/gateway/restart`, etc. — see `docs/adapter-interface-contract.md`
- `ALPHACLAW_ROOT` env var tells PT where AlphaClaw is installed (default: sibling directory)
- No patch proposed by local agents is applied without Claude review (`proposeCodeEdit` returns diff only)
- All local agent backends: Ollama at `127.0.0.1:11434`, LM Studio Mac at `http://localhost:1234` (always localhost), LM Studio Win at `LM_STUDIO_WIN_ENDPOINTS` env var (IP is DHCP-dynamic — source of truth is `~/.openclaw/state/last_discovery.json`; never hardcode)

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
