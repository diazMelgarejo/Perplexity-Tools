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
| Gate 4 — RC 0.9.9.8 | ❌ | not started |

- **PT → AlphaClaw control: COMPLETE** (lifecycle + config + watchdog + logs). Caveat: no `stopServer()` (PID-only, in-memory).
- **PT → OpenClaw: via AlphaClaw by design** (AlphaClaw owns the gateway child process; PT drives it through `/api/gateway/*` + writes `openclaw.json`).
- **`lib/mcp` (11 JS tools) + `lib/agents` are SUPERSEDED** by `packages/alphaclaw-mcp` (14 tools ⊇ 11) + `packages/local-agents`. **Not yet retired** — held until Gate 2 is green.

## The 8 gaps blocking the goal (work items)

1. **Gate 2 verification** — run the live authenticated 14-tool smoke-test; confirm `packages/local-agents` Vitest passes.
2. **Retire `lib/mcp` + `lib/agents`** in AlphaClaw (after #1): `git rm` the 3 JS files + orphan test `tests/server/local-agent-client.test.js`, repoint/remove the `.mcp.json` entry. See the steelman doc.
3. **orama `openclaw_bridge.py` → route through PT adapter** (Gate 3), not direct AlphaClaw calls.
4. **Add PT `stopServer()`** + a PID file so AlphaClaw can be stopped cross-process.
5. **Confirm `agent_launcher.py`** exists in PT root (a `probe_backends()` dependency) or harden the fallback.
6. **Scaffold `packages/mcpb-agents/`** (`ollama-agent.mcpb`, `lmstudio-agent.mcpb`) into real, executable agent defs.
7. **Wire top-level `orchestrator.py`** as the idempotent lifecycle entrypoint (`setup_wizard.py` + `fastapi_app.py`). *(LM Studio endpoint bug already fixed 2026-05-31: `bd6aeda`.)*
8. **Gate 3 E2E `build-verify` flow** + **Gate 4** RC packaging at `0.9.9.8`.

## Sequenced roadmap

- **Phase G2 (close Gate 2):** #5 → #6 → #7 → #1 (live smoke-test) → #2 (retire lib/mcp) → #4 (stopServer).
- **Phase G3:** #3 (bridge reroute) → #8a (build-verify E2E) → OTel emitter.
- **Phase G4:** version-align all three to `0.9.9.8`, `npm pack --dry-run`, `/ship`, publish.

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

## Cross-links

- Gate ladder: [`MIGRATION.md`](MIGRATION.md)
- AlphaClaw HTTP surface: [`adapter-interface-contract.md`](adapter-interface-contract.md)
- Retirement plan: [`../../AlphaClaw/docs/gate2-lib-mcp-deletion-steelman.md`](../../AlphaClaw/docs/gate2-lib-mcp-deletion-steelman.md)
- Session lessons: [PT](LESSONS.md) · [orama](../../orama-system/docs/LESSONS.md) · [AlphaClaw](../../AlphaClaw/docs/Lessons.MD)
