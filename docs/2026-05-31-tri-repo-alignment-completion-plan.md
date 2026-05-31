# Tri-Repo Migration & Consolidation — Alignment & Completion Plan

> **Date:** 2026-05-31 · **Author:** Claude (Opus 4.8) · **Status:** active resume anchor
> **Canonical pair:** this doc (sequenced execution) + [`MIGRATION.md`](MIGRATION.md) (gate ladder)
> **Companions:** [`adapter-interface-contract.md`](adapter-interface-contract.md) ·
> [orama LESSONS](../../orama-system/docs/LESSONS.md) · [AlphaClaw Lessons](../../AlphaClaw/docs/Lessons.MD) ·
> [AlphaClaw Gate-2 steelman](../../AlphaClaw/docs/gate2-lib-mcp-deletion-steelman.md)

## Overarching goal (the single yardstick)

Perpetua-Tools (L2) is the **single control plane** that can directly start / stop /
query / reconfigure **any running AlphaClaw (L1)** and **any OpenClaw gateway**, with
**all non-main AlphaClaw feature capabilities absorbed into PT** functions/skills/servers.
Layering is immutable: **L1 AlphaClaw ← L2 Perpetua-Tools ← L3 orama-system** (never reverse).

## Verified current state (2026-05-31, 3-agent audit)

| Gate | Status | Note |
|------|--------|------|
| Gate 0 — Foundations | ✅ | repos renamed, PT `packages/` scaffold, code copied |
| Gate 1 — AlphaClaw adapter | ✅ | `packages/alphaclaw-adapter` (25 methods) + `orchestrator/alphaclaw_manager.py` |
| Gate 2 — MCP toolpack + local agents | 🟡 **partial** | `packages/alphaclaw-mcp` (14 tools) canonical; gaps below |
| Gate 3 — orama first flow | ❌ | `openclaw_bridge.py` still calls AlphaClaw directly |
| Gate 4 — RC (version-align) | ❌ | target **0.9.9.9** for all PT-owned (MCP stays `0.9.16.9`); see §Codex review |

- **PT → AlphaClaw control: COMPLETE** (lifecycle + config + watchdog + logs). Caveat: no `stopServer()` (PID-only, in-memory) — "can start" ≠ control-plane completeness.
- **PT → OpenClaw: via AlphaClaw by design.** PT manages OpenClaw configuration **only through AlphaClaw's public HTTP/MCP surface** (`/api/gateway/*`, `/api/models/config`, MCP redacted read-config) — *not* by writing `openclaw.json` directly (that would violate the L1/L2 boundary; AlphaClaw owns `openclaw.json`). Any direct-write recovery path must be separately documented as emergency-only.
- **`lib/mcp` (11 JS tools) + `lib/agents` are SUPERSEDED** by `packages/alphaclaw-mcp` (14 tools ⊇ 11) + `packages/local-agents`. **Not yet retired** — held until Gate 2 is green **and `stopServer()` exists**.

## The 8 gaps blocking the goal (work items)

1. **`packages/local-agents` test path is broken (HARD BLOCKER).** Its script references `../../node_modules/.bin/vitest`, but there's no root `node_modules`/`package.json` — the gate is unrunnable as written. Fix: give the package its own `vitest` devDep + lock, OR add a root workspace `package.json`, OR document the exact install command. *(Codex verified the failure.)*
2. **`packages/mcpb-agents` is scaffold-only (HARD BLOCKER, not polish).** `.mcpb` files have empty `tools` objects and `args` point to `../../local-agents/src/orchestrator.js`, which from `packages/mcpb-agents/` resolves to `PT/local-agents` (outside `packages/`) — **wrong path**. Make them real, executable agent defs with correct `packages/local-agents` paths.
3. **Add PT `stopServer()`** (PID-file-backed) + cross-process start/commandeer/stop tests. **Must precede retirement** — "can start" without "can stop" is not control-plane completeness.
4. **Clarify top-level `orchestrator.py` (re-scope).** It already imports `bootstrap_runtime_sync`/`load_runtime_payload` from `orchestrator.control_plane` and has `bootstrap`/`state`/`serve` subcommands (serve = "legacy FastAPI app"). Real work item is **deciding** the canonical boundaries — split into: CLI contract · API contract (`fastapi_app`) · setup-wizard contract · runtime-payload contract. Not "wire from scratch." *(LM Studio `/v1/chat/completions` bug already fixed: `bd6aeda`.)*
5. **Confirm `agent_launcher.py`** exists in PT root (a `probe_backends()` dependency) or harden the fallback.
6. **Gate 2 verification (live):** authenticated 14-tool smoke-test with the non-logging secret flow (see auth precedence below); confirm `packages/local-agents` tests pass (after #1); capture a proof artifact.
7. **Retire `lib/mcp` + `lib/agents`** in AlphaClaw (after #3+#6): `git rm` the 3 JS files + orphan test `tests/server/local-agent-client.test.js`, repoint/remove the `.mcp.json` entry, re-run AlphaClaw + PT-MCP tests + smoke-test. See the steelman doc + the destructive-step spec below.
8. **Gate 3:** orama `openclaw_bridge.py` → route through PT adapter (not direct); E2E `build-verify` flow; OTel emitter. **Gate 4:** version-align (below), `npm pack --dry-run`, `/ship`, publish.

## Sequenced roadmap (revised per Codex review)

1. **Preflight every repo** (before any destructive step) — `git status --short --branch`, `git remote -v`, `git rev-parse --short HEAD`; refuse if all three repos aren't present; paste results into session notes.
2. **PT-local reproducibility:** fix `#1` (local-agents test path) + `#2` (mcpb-agents paths/tools).
3. **Lifecycle completeness:** `#3` (PID-file `stopServer()` + start/commandeer/stop tests).
4. **Clarify entrypoints:** `#4` (CLI vs API vs wizard vs runtime-payload contracts).
5. **Gate-2 local tests:** `packages/alphaclaw-mcp` build/test (✅ passes per Codex) + `packages/local-agents` tests.
6. **Live authenticated smoke-test:** `#6` (non-logging secret; proof artifact; all 14 tools).
7. **Retire AlphaClaw legacy MCP/agents:** `#7` (exact file list; re-run AlphaClaw + PT-MCP + smoke after).
8. **Gate 3:** orama bridge reroute + E2E build-verify.
9. **Version/release:** resolve target → align files → `npm pack --dry-run` / package checks.

## Resume instructions for the next agent (READ FIRST)

- **gbrain CLI:** `set -a; source ~/.gbrain/.env; set +a` before any `gbrain` call (DB URL lives in env, not config.json). Config has `prepare:false` (Supabase pooler fix). The `mcp__gbrain__*` MCP tools may be disconnected — reconnect via `/mcp` or use the CLI. See [orama gstack/SKILL.md §GBrain Ops](../../orama-system/bin/orama-system/gstack/SKILL.md).
- **CRG (code-review-graph):** registry is **empty** — build per repo (`build_or_update_graph_tool` + `embed_graph_tool`) before relying on it. gbrain is the working semantic tool today.
- **orama-system safety:** a background **guardian** auto-restores `orama-system` if it vanishes (log: `~/.orama-guard.log`; offline mirror: `~/.orama-system-backup.git`). If it vanished, check that log + the user's `sudo fs_usage` output for the culprit process. Root cause is NOT OneDrive/iCloud (both cleared) — likely Finder/IDE keep-both.
- **Duplicates:** 209 files + 23 folders quarantined at `~/dup-quarantine-2026-05-31/` (nothing deleted; merge-review showed all unique content was stale). **Never Finder-copy tracked files** — run the dup-check at session start (AlphaClaw `wiki/07`). `.git.corrupted/` dirs in AlphaClaw + PT are separate salvage backups, left untouched.
- **Live smoke-test gate (for #1/#2):** stand up AlphaClaw + run `packages/alphaclaw-adapter/scripts/smoke-test.js` against it using the user's `~/.alphaclaw` `SETUP_PASSWORD` (**ask the user — never hardcode it**). Build + transport were verified GREEN 2026-05-31; only authenticated endpoints remain unproven. Do this in the **main session** (subagent Bash is sandboxed — can't run git/npm/node).
- **Repos / branches:** AlphaClaw `feature/MacOS-post-install` (`5972f7b6`+), Perpetua-Tools `main`, orama-system `main`. All pushed to GitHub (`diazMelgarejo/*`). orama-system local checkout is volatile — re-clone if absent.
- **Stale LM Studio IP:** discovery self-corrects `config/devices.yml` to the live IP (win `.104:1234`). Don't hardcode; the `.101`/`.108` references are stale.

## v2.0 requirement — multi-agent WRITE orchestration (added 2026-05-31)

The deepest gap surfaced this session: multiple AI agents (Claude Code, Cursor cloud
agents, Codex) write to the same three repos with **no write-coordination**. Failures
*this session alone*:

- PT was silently checked out on a Cursor agent's branch (`cursor/critical-bug-investigation-96b5`); a routine docs commit collided with it and a Cursor WIP commit (`fc9f5ee fix(user-input)`) got promoted to `main` while untangling a rejected push.
- `orama-system` vanished from disk **twice** (not OneDrive/iCloud — likely an agent/IDE op).
- Earlier: a Cursor agent **rewrote git history** (forcing a full gbrain resync); ~1,100 macOS keep-both dup files accrued from agents/IDEs copying tracked files.

**Root issue:** the migration makes PT the control plane for the *runtime*
(AlphaClaw/OpenClaw) but there is **no orchestration of agent writes to the repos** —
no branch-ownership registry, no per-repo/branch locks, no "who is working where" state.
Runtime control (Gate 1-2) does not extend to the dev swarm.

**v2.0 fix direction (extends "single control plane" to the agent swarm):**
1. **Enforce worktree-per-agent** — the mechanism exists (orama `scripts/worktree-bootstrap.sh` + `docs/v2/22-worktree-parallel-agents.md`) but isn't *enforced*; no two agents should share a working tree / branch checkout.
2. **PT-owned branch-ownership + activity registry** — which agent owns which branch; reject commits to a branch another active agent owns.
3. **Per-repo/branch write locks** with stale-takeover (model: the gbrain sync lock).
4. **Pre-push gate** refusing to promote another agent's WIP commit to `main` (the `fc9f5ee` incident).
5. Treat the human + each agent as participants the orchestrator **schedules** — not free-for-all writers.

This is a Gate-3 / v2.0 **orchestration** concern, distinct from Gate-2 runtime control, and arguably the highest-leverage fix for stability.

## Codex review — accepted revisions (2026-05-31)

Reviewed by Codex (relentless): [`../../v1/2026-05-31-tri-repo-alignment-plan-code-review.md`](../../v1/2026-05-31-tri-repo-alignment-plan-code-review.md). Accepted points folded into the gaps/roadmap above; the rest:

**Version coherence — the target was incoherent.** PT is internally split (per Codex):

| Component | Current | Target |
|-----------|---------|--------|
| Python package | 0.9.9.9 | **0.9.9.9** |
| `orchestrator.__version__` | 0.9.9.7 | **0.9.9.9** |
| `fastapi_app` version | 0.9.9.7 | **0.9.9.9** |
| adapter package | 0.9.9.9 | **0.9.9.9** |
| local-agents package | 0.9.9.9 | **0.9.9.9** |
| configs | 0.9.9.8 | **0.9.9.9** |
| `alphaclaw-mcp` | 0.9.16.9 | **0.9.16.9** (tracks AlphaClaw feature lineage) |

→ Gate 4 aligns all PT-owned to **0.9.9.9**; MCP stays `0.9.16.9`. (Re-verify the actuals at Gate 4.)

**Smoke-test auth precedence** (replaces "ask the user" — wrong for a non-interactive agent env):
1. `SETUP_PASSWORD` from environment → 2. AlphaClaw `.env` (per adapter contract) → 3. explicit human-provided secure secret mechanism → 4. **fail closed**. The smoke-test MUST assert **no secret is printed**.

**Destructive-step spec** (required for every cross-repo destructive op, after the preflight): repo path · branch · remote · exact SHA · files to remove · exact tests before/after · rollback command · proof-artifact path.

**Steelman (review concurred):** L1/L2/L3 architecture sound · retirement-caution correct · single-yardstick is a good acceptance criterion · **v2.0 write-coordination = highest-value insight** · no-hardcode-stale-IP correct.

## Cross-links

- Gate ladder: [`MIGRATION.md`](MIGRATION.md)
- AlphaClaw HTTP surface: [`adapter-interface-contract.md`](adapter-interface-contract.md)
- Retirement plan: [`../../AlphaClaw/docs/gate2-lib-mcp-deletion-steelman.md`](../../AlphaClaw/docs/gate2-lib-mcp-deletion-steelman.md)
- Session lessons: [PT](LESSONS.md) · [orama](../../orama-system/docs/LESSONS.md) · [AlphaClaw](../../AlphaClaw/docs/Lessons.MD)
