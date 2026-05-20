# Perpetua-Tools — Claude Code Navigation

> Renamed: Perplexity-Tools → Perpetua-Tools (2026-04-20, trademark risk eliminated)
> Package: `@diazmelgarejo/perpetua-tools@0.9.9.8` · Role: Layer 2 — Middleware/Adapters
> GitHub: <https://github.com/diazMelgarejo/Perpetua-Tools>

---

## Meta-rule: Progressive Disclosure (Horse Pulls Cart)

**Documents own content. This file navigates.**
Skills operationalize docs — they don't copy them.
Full cross-repo instructions → [`../../CLAUDE-instru.md`](../../CLAUDE-instru.md)

---

## § 0 — Architectural Contracts

**Source of truth:** [`../orama-system/docs/2026-05-14--UNIFIED-ABSORPTION-PLAN.md`](../orama-system/docs/2026-05-14--UNIFIED-ABSORPTION-PLAN.md) §§ 0–2.
**Lockstep:** PT and orama-system CLAUDE.md §0 must stay aligned — any structural change commits to both repos.

| Topic | Where |
|-------|-------|
| Banned terminology (coordinator → orchestrator, etc.) | [Unified Plan § 1](../orama-system/docs/2026-05-14--UNIFIED-ABSORPTION-PLAN.md) |
| 8 governing principles | [Unified Plan § 1](../orama-system/docs/2026-05-14--UNIFIED-ABSORPTION-PLAN.md) |
| **Hard requirements** (Mac: Ollama + qwen3.5:9b-nvfp4 + bge-m3; Win: LM Studio) | [Unified Plan § 2](../orama-system/docs/2026-05-14--UNIFIED-ABSORPTION-PLAN.md) · [`../../CLAUDE-instru.md § 6`](../../CLAUDE-instru.md) |
| **Shared types** (`OrchestrationSession`, `TaskEnvelope`, `WorkerAssignment`, `WorkerResult`, `VerificationResult`) | PT owns them in `orchestrator/contracts.py` — orama imports from PT, never reverse |
| Verifier gate (crystallization blocked without approved VerificationResult) | [Unified Plan § 2](../orama-system/docs/2026-05-14--UNIFIED-ABSORPTION-PLAN.md) |
| V1 scope (MAESTRO/HITL deferred) | [Unified Plan § 2](../orama-system/docs/2026-05-14--UNIFIED-ABSORPTION-PLAN.md) |
| AlphaClaw adapter surface | [`docs/adapter-interface-contract.md`](docs/adapter-interface-contract.md) |
| HITL accountability | [`../orama-system/docs/HUMAN-IN-LOOP-ACCOUNTABILITY.md`](../orama-system/docs/HUMAN-IN-LOOP-ACCOUNTABILITY.md) |
| Search frugality rule (gbrain → CRG → Brave → Perplexity → Grok) | [`../orama-system/bin/orama-system/skills/openclaw-skills/references/universal-skill-protocol.md`](../orama-system/bin/orama-system/skills/openclaw-skills/references/universal-skill-protocol.md) § Search Frugality Rule |
| Win coder pool (`$WIN_CODER_ENDPOINTS`, always-utilized before Mac-local) | [`../orama-system/bin/orama-system/skills/openclaw-skills/references/universal-skill-protocol.md`](../orama-system/bin/orama-system/skills/openclaw-skills/references/universal-skill-protocol.md) § Windows Coder Policy |

**Quick invariants:**
- `orchestrator` only — never `coordinator` in public APIs, schemas, config, or headings
- PT is **runtime/state authority**: job queue, hardware affinity, model routing, GPU safety, LAN routing, durable artifacts
- orama is stateless (planning/methodology only); imports shared types from PT, never the reverse
- `@field_validator` (Pydantic V2) — never deprecated `@validator`
- AlphaClaw: CLI + HTTP only — never `require()` or internal imports
- **Mac hard requirements:** Ollama (`localhost:11434`) with `qwen3.5:9b-nvfp4` + `bge-m3` — probe on startup; fail closed if absent
- **Win hard requirement:** LM Studio at `$LM_STUDIO_WIN_ENDPOINTS` — fail loudly if unreachable
- **Optional:** LM Studio Mac (secondary fallback only), cloud APIs, all other local models

---

## § 1 — Continuous Learning

Every session: read [`docs/LESSONS.md`](docs/LESSONS.md) at start; append before exit.
Cross-repo companion: [`../orama-system/docs/LESSONS.md`](../orama-system/docs/LESSONS.md)
Instinct path: `.claude/homunculus/instincts/inherited/Perpetua-Tools-instincts.yaml`

---

## § 2 — ECC Post-Merge Workflow

After any ECC Tools PR merges:

```bash
git pull origin main
/instinct-import .claude/homunculus/instincts/inherited/Perpetua-Tools-instincts.yaml
/instinct-status
git add -A && git commit -m "chore(ecc): post-merge instinct import sync" && git push origin main
```

---

## § 3 — Session Resources

| Resource | Purpose |
|----------|---------|
| [`SKILL.md`](SKILL.md) | Model selection rules + agent behavioral rules |
| [`docs/LESSONS.md`](docs/LESSONS.md) | Chronological session log |
| [`docs/wiki/README.md`](docs/wiki/README.md) | Wiki index |
| [`docs/adapter-interface-contract.md`](docs/adapter-interface-contract.md) | Living AlphaClaw API surface — update after every upstream merge |
| [`docs/wiki/07-multi-agent-collab.md`](docs/wiki/07-multi-agent-collab.md) | Version registry, scope claims, conflict recovery |
| [`../orama-system/docs/2026-05-14--UNIFIED-ABSORPTION-PLAN.md`](../orama-system/docs/2026-05-14--UNIFIED-ABSORPTION-PLAN.md) | Canonical architecture — PT is L2 in this plan |

---

## § 4 — AutoResearcher

Plugin: `uditgoenka/autoresearch`. Per-session: `/autoresearch`.
Read + write `docs/LESSONS.md` around experiments. GPU guard: check `GPU: BUSY` in `swarm_state.md` before dispatch.
Full spec: [`docs/wiki/07-multi-agent-collab.md`](docs/wiki/07-multi-agent-collab.md)

---

## § 5 — Three-Repo Architecture

```
AlphaClaw (L1 — infra, CLI+HTTP only) → Perpetua-Tools (L2 — THIS REPO) → orama-system (L3 — orchestration)
```

**PT owns:** `orchestrator/contracts.py` (shared types), `orchestrator/`, `config/`, `packages/`.
**PT drives AlphaClaw via:** REST endpoints documented in [`docs/adapter-interface-contract.md`](docs/adapter-interface-contract.md).
**orama drives PT via:** `orchestrator/orama_bridge.py`.

MCP server registration:
```bash
claude mcp add --transport stdio alphaclaw -- node packages/alphaclaw-adapter/src/mcp/server.js
```

Full architecture: [`../orama-system/docs/2026-05-14--UNIFIED-ABSORPTION-PLAN.md`](../orama-system/docs/2026-05-14--UNIFIED-ABSORPTION-PLAN.md)
As-built: [`../orama-system/docs/v2/`](../orama-system/docs/v2/)

---

## § 6 — Git Hygiene

- Commit identity: `cyre <Lawrence@cyre.me>` or `Codex <codex@openai.com>`
- Dated branches: `yyyy-mm-dd-NNN-brief-summary`
- Lockstep commits: changes to shared schema fields, exception classes, or policy keys commit to **both repos in the same session**
- Never commit `.env`, `.env.local`

---

## § 7 — gstack

gstack v1.37.0.0 at `~/.claude/skills/gstack`.
- ALWAYS use `/browse` for web — NEVER `mcp__claude-in-chrome__*` directly
- `/plan-eng-review` before any Gate 0→1 transition; `/ship` before `npm publish`

---

## GBrain Search Guidance (configured by /sync-gbrain)
<!-- gstack-gbrain-search-guidance:start -->

GBrain is set up and synced on this machine. The agent should prefer gbrain
over Grep when the question is semantic or when you don't know the exact
identifier yet.

**This worktree is pinned to a worktree-scoped code source** via the
`.gbrain-source` file in the repo root (kubectl-style context). Any
`gbrain code-def`, `code-refs`, `code-callers`, `code-callees`, or `query`
call from anywhere under this worktree routes to that source by default —
no `--source` flag needed.

Two indexed corpora available via the `gbrain` CLI:
- This worktree's code (auto-pinned via `.gbrain-source` → `gstack-code-ools-27e2b79c-df8a28`).
- `~/.gstack/` curated memory (registered as `gstack-brain-lawrencecyremelgarejo` source).

Prefer gbrain when:
- "Where is X handled?" / semantic intent, no exact string yet:
    `gbrain search "<terms>"` or `gbrain query "<question>"`
- "Where is symbol Y defined?" / symbol-based code questions:
    `gbrain code-def <symbol>` or `gbrain code-refs <symbol>`
- "What calls Y?" / "What does Y depend on?":
    `gbrain code-callers <symbol>` / `gbrain code-callees <symbol>`
- "What did we decide last time?" / past plans, retros, learnings:
    `gbrain search "<terms>" --source gstack-brain-lawrencecyremelgarejo`

Grep is still right for known exact strings, regex, multiline patterns, and
file globs. Run `/sync-gbrain` after meaningful code changes.

<!-- gstack-gbrain-search-guidance:end -->
