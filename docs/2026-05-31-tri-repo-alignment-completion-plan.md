# Tri-Repo Migration & Consolidation — Alignment & Completion Plan

> **Date:** 2026-05-31 (revised 2026-05-31, decisions **D1–D5 locked** after code verification; **A+B variants combined**)
> **Author:** Claude (Opus 4.8) + Cursor agent (D1–D5 code-verification pass) · **Status:** active resume anchor
> **Canonical pair:** this doc (sequenced execution + locked decisions) + [`MIGRATION.md`](MIGRATION.md) (gate ladder)
> **Companions:** [`adapter-interface-contract.md`](adapter-interface-contract.md) ·
> [orama LESSONS](../../orama-system/docs/LESSONS.md) · [AlphaClaw Lessons](../../AlphaClaw/docs/Lessons.MD) ·
> [AlphaClaw Gate-2 steelman](../../AlphaClaw/docs/gate2-lib-mcp-deletion-steelman.md)

---

## Overarching goal (the single yardstick)

Perpetua-Tools (L2) is the **single control plane** that can directly start / stop /
query / reconfigure **any running AlphaClaw (L1)** and **any OpenClaw gateway**, with
**all non-main AlphaClaw feature capabilities absorbed into PT** functions/skills/servers.
Layering is immutable: **L1 AlphaClaw ← L2 Perpetua-Tools ← L3 orama-system** (never reverse).

**Acceptance test (how we know the yardstick is met):** PT can *start, stop, query, and
reconfigure* a live AlphaClaw + OpenClaw gateway entirely through its own surfaces — measured
by decisions **D1–D5** and the **SSEA** gates below. "Can start" without "can stop" (the
current `stopServer` gap — Work item #4) does **not** satisfy this goal.

---

## Resolved decisions (2026-05-31, human + code-verified)

| ID | Decision | Code basis |
|----|----------|------------|
| **D1** | Gate 4 / PT-owned surfaces → **`0.9.9.9`**. Keep **`packages/alphaclaw-mcp` at `0.9.16.9`**. | `pyproject.toml`, `packages/*/package.json` already `0.9.9.9`; bump `orchestrator/*` + configs from `0.9.9.7`/`0.9.9.8`. |
| **D2** | **A + B** — see § Config & agent creation (below). | `alphaclaw_bootstrap.py` writes config + workspaces; orama `apply_runtime_payload()` applies PT payload; **gap:** `reconcile_gateway()` does not yet attach `openclaw_config`. |
| **D3** | AlphaClaw **`feature/MacOS-post-install`** @ **`b540eca1`**. `lib/mcp` + `lib/agents` **present** on that branch. | `git ls-tree origin/feature/MacOS-post-install`: `lib/mcp/alphaclaw-mcp.js`, `lib/agents/*.js`. |
| **D4** | Smoke auth precedence **`1 > 2 > 3 > 4`**. **Fail-closed: NO** (bootstrap may use default password when non-interactive). | `alphaclaw_bootstrap._gather_alphaclaw_credentials()`; orama inline fallback refuses without `SETUP_PASSWORD` unless `ORAMA_INSECURE_DEV=1`. |
| **D5** | **C — Both entrypoints**, documented roles. | `orchestrator.py` CLI + legacy app; `orchestrator/fastapi_app.py` supervisor HTTP (tests target this). |

---

## SSEA tags

| Tag | Meaning |
|-----|---------|
| **SEC** | Secrets, auth, L1/L2 boundaries |
| **SAF** | No wrong-branch deletes; no orphan gateways |
| **EFF** | Prove replacements before retirement |
| **ACC** | Gates match actual code paths |

---

## Verified current state

| Gate | Status | Note |
|------|--------|------|
| Gate 0 | ✅ | repos renamed, PT `packages/` scaffold, code copied |
| Gate 1 | ✅ | `packages/alphaclaw-adapter` (25 methods) + `orchestrator/alphaclaw_manager.py` |
| Gate 2 | 🟡 | Blockers: `stopServer`, tests, mcpb paths, smoke |
| Gate 3 | ❌ | `openclaw_bridge.py` bypasses PT (direct OpenClaw gateway) |
| Gate 4 | ❌ | Align to **D1** (`0.9.9.9`) |

- **Stop gap (`ACC`):** `packages/alphaclaw-adapter` has `startServer` / `ensureRunning` only; no `stopServer`; PID in-memory on detached child.
- **Retirement held (`SAF`):** AlphaClaw `lib/mcp` (11 JS tools) + `lib/agents` are **superseded** by PT `packages/alphaclaw-mcp` (14 tools ⊇ 11) + `packages/local-agents`, but live only on the **D3** branch and stay until Gate 2 is green.

---

## Config & agent creation (D2 — code-verified)

Two **distinct** "agent" concepts — do not conflate:

| Layer | Artifact | Purpose |
|-------|----------|---------|
| **OpenClaw runtime** | `~/.openclaw/openclaw.json` → `agents.list[]` | Gateway routing (`mac-researcher`, `coder`, `orchestrator`, …). Used by `openclaw_bridge.chat(agent_id, …)`. |
| **orama methodology** | `orama-system/bin/config/agent_registry.json` | Ultrathink stage agents (context, architect, executor, …). **Not** written into `openclaw.json` by bootstrap. |

### D2-A — Normal ops + bootstrap (PT / L2)

| Mode | Who writes `openclaw.json` | **SEC** |
|------|---------------------------|---------|
| **Bootstrap / recovery** | `Perpetua-Tools/alphaclaw_bootstrap.py` → `_write_openclaw_config()` + `_ensure_agent_workspaces()` | Reads `PT_AGENTS_STATE` / `.state/routing.json`; copies `SOUL.md` from `PT/bin/agents/<role>/` into `~/.openclaw/agents/<role>/`. |
| **Normal reconfigure** | AlphaClaw **`PUT /api/models/config`** (via adapter / MCP) | PT never logs `SETUP_PASSWORD`; MCP redacts secrets on read. |

**Agent list creation (OpenClaw):** `build_openclaw_config()` in `alphaclaw_bootstrap.py` builds `agents.list` (ids, `model.primary`, `workspace` paths) from PT routing state — not from orama `agent_registry.json`.

### D2-B — orama apply path (L3 override)

When PT has already resolved a runtime payload in memory, orama may apply it **without** re-running full bootstrap:

- **File:** `orama-system/scripts/openclaw_bootstrap.py` → `apply_runtime_payload(payload, force=)`
- **Behavior:** Writes `payload["gateway"]["openclaw_config"]` to `~/.openclaw/openclaw.json` (merge/skip if equal), then `_ensure_agent_workspaces()`.
- **Test:** `orama-system/tests/test_openclaw_bootstrap.py::test_apply_runtime_payload_writes_pt_resolved_config`

**CLI bootstrap** still **delegates** to PT when `PT_HOME/alphaclaw_bootstrap.py` exists (`bootstrap_openclaw()` subprocess).

### Implementation gap (`ACC` — Gate 2/3 follow-up)

`orchestrator/control_plane.reconcile_gateway()` returns gateway status but **does not** include `openclaw_config` today (unlike the mocked shape in `tests/test_control_plane.py`). `alphaclaw_manager.RuntimePayload` also omits `openclaw_config`.

**Required for D2-B in production:** after `alphaclaw_bootstrap` / reconcile, attach `openclaw_config` to `.state/runtime_payload.json` → orama calls `apply_runtime_payload` OR orama only uses PT subprocess bootstrap (already delegated).

**orama inline fallback** (no PT): writes its own simplified `openclaw.json` — **SEC:** refuses start without `SETUP_PASSWORD` unless `ORAMA_INSECURE_DEV=1` (stricter than PT bootstrap default-password path per **D4**).

> **L1/L2 boundary (SEC):** in normal ops PT manages OpenClaw config **only through AlphaClaw's public HTTP/MCP surface** (`PUT /api/models/config`). Direct file writes to `openclaw.json` are reserved for the documented bootstrap/recovery path above — never a routine PT operation.

---

## Entrypoints (D5 — code-verified)

| Surface | Command / module | Role |
|---------|------------------|------|
| **CLI lifecycle** | `python orchestrator.py bootstrap \| state \| serve` | `bootstrap` → `control_plane.bootstrap_runtime_sync()`; `serve` → legacy FastAPI in `orchestrator.py` (port 8000). |
| **Supervisor HTTP** | `orchestrator.fastapi_app:app` | Jobs, routing, redacted runtime read — **primary test target** (`tests/test_*` import `fastapi_app`). |
| **orama delegation** | `python -m orchestrator.alphaclaw_manager --resolve` | Emits `RuntimePayload` JSON for `start.sh` (no `openclaw_config` yet — see gap above). |
| **Setup wizard** | `setup_wizard.py` | Interactive hardware/env; not the canonical HTTP server. |

---

## Mandatory preflight (before `git rm` / promote to `main`)

```bash
cd /path/to/repo && git status --short --branch && git remote -v && git rev-parse --short HEAD
```

**D3 retirement preflight (AlphaClaw):**

```bash
cd AlphaClaw && git checkout feature/MacOS-post-install && git rev-parse --short HEAD
# Expect: b540eca1 (or newer on same branch — re-verify lib/mcp exists)
git ls-tree -r HEAD --name-only | rg '^lib/(mcp|agents)/'
```

**Destructive-step spec (every cross-repo `git rm` / promote):** name repo path · branch · remote · exact SHA · files to remove · tests to run before/after · rollback command · proof artifact path. Paste preflight output into session notes before proceeding.

---

## Work items (8 gaps)

| # | Item | SSEA |
|---|------|------|
| 1 | Live smoke + `local-agents` tests | **SEC:** auth order D4; no password in logs |
| 2 | Retire `lib/mcp` on **D3** branch only | **SAF** after #4 and #1 |
| 3 | Gate 3: orama → PT adapter (not direct `OPENCLAW_GATEWAY`) | **ACC** |
| 4 | `stopServer()` + PID file + tests | **SAF** before #2 |
| 5 | Verify `agent_launcher.py` probe (exists at PT root) | **ACC** |
| 6 | Fix `mcpb-agents` → `../local-agents/src/orchestrator.js` (empty `tools`, wrong relative paths) | **ACC** |
| 7 | Document entrypoints (D5 — done in this doc); wire `openclaw_config` in payload | **EFF** |
| 8 | Gate 3 E2E + Gate 4 @ **0.9.9.9** | **ACC** |

---

## Phase G2 sequence (`EFF`)

```text
Preflight → #5 → #6 → #7 (payload openclaw_config wire-up) → #4 (stopServer) → #1 (live smoke) → #2 (retire lib/mcp)
```

> Sequencing rule (`EFF`/`SAF`): `stopServer()` (#4) precedes retiring `lib/mcp` (#2) — never delete the old MCP before PT owns cross-process stop/restart.

---

## Gate 2 — tests & smoke

### `packages/local-agents`

Fix vitest path (add `devDependency` or root workspace — the script references a missing `../../node_modules/.bin/vitest`), then:

```bash
cd packages/local-agents && npm install && npm test
```

### `packages/alphaclaw-mcp`

```bash
cd packages/alphaclaw-mcp && npm install && npm test
```

### Live smoke (`D4`)

Resolve password in order:

1. `SETUP_PASSWORD` env
2. `$ALPHACLAW_ROOT/.env` (implement in smoke script if not env-set)
3. `~/.alphaclaw/.env`
4. Ask human

**Fail-closed NO:** non-interactive bootstrap may use the default password (`alphaclaw_bootstrap.py`); smoke may still **skip** auth tests if unset (`smoke-test.js` today). Prefer setting env for real gate runs. **Assert no secret is printed.**

```bash
SETUP_PASSWORD='…' node packages/alphaclaw-adapter/scripts/smoke-test.js
```

---

## Gate 3 — bridge (`ACC`)

`openclaw_bridge.py` posts to `OPENCLAW_GATEWAY/v1/chat/completions` with `model: agent_id`.
Gate: route through PT so L3 never holds L1 secrets and PT owns routing.

---

## Gate 4 — versioning (`D1`)

| Surface | Target |
|---------|--------|
| PT pip + packages (except MCP) | `0.9.9.9` |
| `orchestrator.py`, `fastapi_app`, `orchestrator/__init__.py`, `config/*.yml`, `SKILL.md` | `0.9.9.9` |
| `packages/alphaclaw-mcp` | `0.9.16.9` (unchanged — tracks AlphaClaw feature lineage) |
| orama-system (lockstep policy) | align when PT bumps |

---

## AlphaClaw retirement (D3)

**Branch:** `feature/MacOS-post-install`
**Verified SHA:** `b540eca1`
**Files present:** `lib/mcp/alphaclaw-mcp.js`, `lib/agents/local-agent-client.js`, `lib/agents/orchestrator.js` (all syntax-valid + registered in `.mcp.json`; the 4 `local_agent_*` tools default to stale LM Studio `.101`/Ollama `11435` endpoints, env-overridable).

Follow the steelman on that branch **after Gate 2 green**. `main` in cloud clones may **not** contain these paths — do not retire on `main` alone.

---

## Resume instructions for the next agent (READ FIRST)

- Decisions **D1–D5** are locked above; do not re-debate without human override.
- Run § Mandatory preflight every session before destructive work. Live smoke runs in the **main session** (subagent Bash is sandboxed — can't run git/npm/node).
- **gbrain CLI:** `set -a; source ~/.gbrain/.env; set +a` before any `gbrain` call (DB URL lives in env, not config.json). Config has `prepare:false` (Supabase pooler fix). The `mcp__gbrain__*` MCP tools may be disconnected — reconnect via `/mcp` or use the CLI. See [orama gstack/SKILL.md §GBrain Ops](../../orama-system/bin/orama-system/gstack/SKILL.md).
- **CRG (code-review-graph):** registry was empty — build per repo (`build_or_update_graph_tool` + `embed_graph_tool`) before relying on it. gbrain is the working semantic tool today.
- **orama-system safety:** a background **guardian** auto-restores `orama-system` if it vanishes (`~/.orama-guard.log`; offline mirror `~/.orama-system-backup.git`). Root cause is NOT OneDrive/iCloud (both cleared) — likely Finder/IDE keep-both. Local checkout is volatile — re-clone if absent.
- **Duplicates:** 209 files + 23 folders quarantined at `~/dup-quarantine-2026-05-31/` (nothing deleted; merge-review showed all unique content was stale). **Never Finder-copy tracked files** — run the dup-check at session start (AlphaClaw `wiki/07`). `.git.corrupted/` dirs in AlphaClaw + PT are separate salvage backups, left untouched.
- **Repos / branches:** AlphaClaw `feature/MacOS-post-install` (D3 @ `b540eca1`+), Perpetua-Tools `main`, orama-system `main`. All pushed to GitHub (`diazMelgarejo/*`).
- **Stale LM Studio IP:** discovery self-corrects `config/devices.yml` to the live IP (win `.104:1234`). Don't hardcode; the `.101`/`.108` references are stale.

---

## v2.0 — multi-agent WRITE orchestration (`SAF`)

The deepest gap this migration surfaced: multiple AI agents (Claude Code, Cursor cloud
agents, Codex) write to the same three repos with **no write-coordination**. Concrete
failures *this session*:

- PT was silently checked out on a Cursor agent's branch; a routine docs commit collided and a Cursor WIP commit got promoted to `main` while untangling a rejected push (and recurred — detached-HEAD churn lost a plan-revision commit, recovered via reflog).
- `orama-system` vanished from disk **twice** (not OneDrive/iCloud — likely an agent/IDE op).
- Earlier: a Cursor agent **rewrote git history** (forcing a full gbrain resync); ~1,100 macOS keep-both dup files accrued from agents/IDEs copying tracked files.

**Root issue:** the migration makes PT the control plane for the *runtime*
(AlphaClaw/OpenClaw) but there is **no orchestration of agent writes to the repos** — no
branch-ownership registry, no per-repo/branch locks, no "who is working where" state.
Runtime control (Gate 1-2) does not extend to the dev swarm.

**Fix direction (extends "single control plane" to the agent swarm):**
1. **Enforce worktree-per-agent** — the mechanism exists (orama `scripts/worktree-bootstrap.sh` + `docs/v2/22-worktree-parallel-agents.md`) but isn't *enforced*; no two agents share a working tree / branch checkout.
2. **PT-owned branch-ownership + activity registry** — which agent owns which branch; reject commits to a branch another active agent owns.
3. **Per-repo/branch write locks** with stale-takeover (model: the gbrain sync lock).
4. **Pre-push gate** refusing to promote another agent's WIP commit to `main`.
5. Treat the human + each agent as participants the orchestrator **schedules** — not free-for-all writers.

This is a Gate-3 / v2.0 **orchestration** concern, distinct from Gate-2 runtime control, and arguably the highest-leverage fix for stability. See [`LESSONS.md`](LESSONS.md).

---

## Cross-links

- [`MIGRATION.md`](MIGRATION.md) — gate ladder (Gate 4 = `0.9.9.9`)
- [`adapter-interface-contract.md`](adapter-interface-contract.md) — AlphaClaw HTTP surface
- Retirement: [`../../AlphaClaw/docs/gate2-lib-mcp-deletion-steelman.md`](../../AlphaClaw/docs/gate2-lib-mcp-deletion-steelman.md) on **D3** branch
- Session lessons: [PT](LESSONS.md) · [orama](../../orama-system/docs/LESSONS.md) · [AlphaClaw](../../AlphaClaw/docs/Lessons.MD)

---

## Document changelog

| Date | Change |
|------|--------|
| 2026-05-31 | Initial plan (variant A — Codex-folded revision) |
| 2026-05-31 | Locked D1–D5; code-verified D2 agent paths + `apply_runtime_payload` gap; D3 `b540eca1`; reordered G2 (variant B / PR #67) |
| 2026-05-31 | **Combined A+B:** B's D1–D5 / SSEA / code-verified structure + A's full "single yardstick" goal, detailed resume instructions, and full v2.0 section. One canonical conflict-free plan. |
