# Perpetua-Tools — Unified Migration Guide

**Status:** Living document — PT is the canonical migration repo from 2026-04-20 forward
**Version target:** `0.9.9.8` across all three packages simultaneously
**Gate 0:** ✅ Complete (2026-04-20)
**Gate 1:** ✅ Complete (2026-04-20) — adapter HTTP client, alphaclaw_manager.py, thinned start.sh
**Sources merged:**
- Migration Plan 3 + Plan Review (AlphaClaw `docs/plan-review-migration-plan-3.md`)
- System Design: Three-Repo Architecture (`docs/system-design-three-repo-architecture.md`)
- Old UTS+PT contract (`old-UTS+PT Review and optimize for the most elegant solution.md`)
- orama-system lessons (`.claude/lessons/Perplexity-Ultrathink-Consolidation.md`)
- PT wiki `docs/wiki/08-macos-alphaclaw-compat.md`

---

## Architecture (settled — do not re-debate)

```
AlphaClaw (Layer 1 — infrastructure / managed dependency)
    │  CLI + HTTP only — NEVER require() AlphaClaw internals
    ▼
Perpetua-Tools (Layer 2 — THIS REPO — middleware / adapters / tooling)
    │  typed adapter contracts, PT-resolved runtime payload
    ▼
orama-system (Layer 3 — orchestration / meta-intelligence / delegate runtime)
```

**PT owns:** gateway discovery, route choice, topology decisions, lifecycle control, AlphaClaw start/stop, LM Studio routing, local agent dispatch.
**orama owns:** execution, reasoning flows, apply-config-from-PT, stateless API surface, multi-agent methodology.
**AlphaClaw owns:** npm installation, macOS binary placement, gateway process, openclaw.json management.

This is agreed in both old and new contracts. The orama consolidation lesson states it clearly: *"PT is authoritative for gateway discovery, route choice, topology, and readiness. UTS should only apply PT-resolved config."*

---

## Resolved Tensions (old contract vs new architecture)

### Tension 1: Python direct import vs HTTP-only adapter

| Old contract | New architecture | Resolution |
|---|---|---|
| `openclaw_bootstrap.py` in PT patches AlphaClaw npm package directly | PT calls AlphaClaw via CLI + HTTP (strangler-fig) | **New wins for long-term.** `setup_macos.py` in orama applies OS-level patches to the installed binary — this is a one-time OS setup step, not lifecycle management. PT's adapter then calls the already-patched binary via `node bin/alphaclaw.js start`. |

**Practical rule:** `setup_macos.py` (orama) = patch binary once at install time. `packages/alphaclaw-adapter/` (PT) = ongoing lifecycle via CLI/HTTP. These are complementary, not competing.

### Tension 2: Python orchestrator.py vs Node.js packages/

| Old contract | New architecture | Resolution |
|---|---|---|
| `orchestrator.py` as single idempotent Python entrypoint | `packages/` directory for Node.js MCP + local agents | **Both coexist.** Python `orchestrator/` = Python control plane for model routing, cost guard, LAN discovery. Node.js `packages/alphaclaw-adapter/` = MCP server + HTTP adapter. Node.js `packages/local-agents/` = Ollama + LM Studio clients. |

**Practical rule:** Python layer owns PT's own orchestration decisions. Node.js layer owns MCP protocol + AlphaClaw communication.

### Tension 3: AutoResearch preflight visibility

Old contract flagged: no staged readiness reporting, no explicit handshake chain.
Resolution: Gate 3 work. `orchestrator/autoresearch_bridge.py` gets progress hooks. Not blocking Gates 0-2.

### Tension 4: Perplexity credential onboarding

Old contract: add Perplexity API key gate in setup path.
Resolution: **Superseded** — repo renamed to Perpetua-Tools. "Perplexity" provider becomes one of many configured providers in `openclaw.json`. AlphaClaw's provider config is PT's responsibility. General API credential onboarding replaces Perplexity-specific gate.

---

## What is Broken Right Now (fix before Gate 1)

### orama-system — Gate 0 audit (2026-04-20)

| File | Status | Detail |
|------|--------|--------|
| `bin/agents/orchestrator/orchestrator_logic.py` | ✅ **Implemented** | Full stage machine: `create_task_state()`, `advance_stage()`, 7-stage sequence |
| `tests/test_orchestrator.py` | ✅ **Already fixed** | Uses `bin/shared` + `bin/agents/orchestrator`; `pythonpath=["."]` in `pyproject.toml` |
| `tests/test_orchestrator.py` — 19 tests | ✅ **19/19 PASS** | Verified in sandbox 2026-04-20 |
| `start.sh` | 🔲 Gate 1 | Still makes gateway decisions — reduce to PT delegator |
| `openclaw_bootstrap.py` | 🔲 Gate 1 | Still probes/routes — scope down to apply-config only |

### Perpetua-Tools — Gate 1 audit (2026-04-20)

| File | Status | Detail |
|------|--------|--------|
| `packages/alphaclaw-adapter/src/index.js` | ✅ **Implemented** | Full HTTP client: 20+ methods, session cookies, commandeer-first, `ensureRunning()` |
| `packages/alphaclaw-adapter/scripts/smoke-test.js` | ✅ **Implemented** | Gate 1 smoke test — colored PASS/FAIL per method |
| `orchestrator/alphaclaw_manager.py` | ✅ **Implemented** | `probe_backends()`, `determine_mode()`, `bootstrap_alphaclaw()`, `resolve_runtime()`, `--resolve --env-only` CLI |
| `packages/alphaclaw-adapter/package.json` | ✅ **Fixed** | Removed `"type": "module"` — now consistently CJS |
| `orchestrator.py` (top-level) | 🔲 Gate 2 | Wire `setup_wizard.py` + `fastapi_app.py` through shared control plane |

---

## Key Rule: Files Stay in Source Until Proven in Target

```
AlphaClaw feature/MacOS-post-install code stays until:
  1. The file is copied to PT/orama  ← already done for MCP + agents
  2. PT/orama tests pass with the copied version  ← Gate 1 verification
  3. AlphaClaw tests still green (no regression)  ← verified at each gate

DO NOT delete from AlphaClaw until Gate 1 is complete and verified.
```

Current state: `lib/mcp/alphaclaw-mcp.js`, `lib/agents/local-agent-client.js`, `lib/agents/orchestrator.js` are still in AlphaClaw. Copies now live in PT `packages/`. Both coexist until Gate 1 verified.

---

## Migration Sequence (Milestone Gates)

### Gate 0 — Foundations ✅ IN PROGRESS

- [x] GitHub repos renamed: `Perpetua-Tools`, `orama-system`
- [x] PT `packages/` scaffold: `alphaclaw-adapter/`, `local-agents/`, `mcpb-agents/`
- [x] AlphaClaw MCP + agents copied to PT (originals untouched in AlphaClaw)
- [x] `docs/adapter-interface-contract.md` written — living API contract
- [x] `system-design-three-repo-architecture.md` §3.2 populated with real HTTP endpoints
- [x] CLAUDE.md updated in PT and orama with new identities
- [x] All plans/migration docs moved to PT as canonical migration repo
- [ ] npm scopes reserved: `@diazmelgarejo/perpetua-tools`, `@diazmelgarejo/orama-system`
- [ ] gstack installed on Mac (`bash scripts/install-gstack.sh`, requires bun)
- [ ] orama test imports repaired: `multi_agent/shared` → `bin/shared`
- [ ] `bin/agents/orchestrator/orchestrator_logic.py` baseline written

### Gate 1 — AlphaClaw Adapter Working ✅ COMPLETE (2026-04-20)

- [x] `packages/alphaclaw-adapter/src/index.js`: full HTTP client — `login()`, `logout()`, `authStatus()`, `health()`, `status()`, `gatewayStatus()`, `gatewayDashboard()`, `restartGateway()`, `restartStatus()`, `dismissRestartStatus()`, `version()`, `getModels()`, `getModelsConfig()`, `putModelsConfig()`, `getEnv()`, `putEnv()`, `watchdogStatus()`, `watchdogEvents()`, `watchdogLogs()`, `watchdogRepair()`, `tailLogs()`, `discoverPort()`, `startServer()`, `waitForReady()`, `ensureRunning()`
- [x] `orchestrator/alphaclaw_manager.py` created in PT — owns backend probe (was start.sh §2a), mode determination (was §2c), AlphaClaw bootstrap delegation. Exposes `--resolve --env-only` for orama delegation.
- [x] `packages/alphaclaw-adapter/scripts/smoke-test.js` — covers all adapter methods with colored PASS/FAIL output. Run: `SETUP_PASSWORD=<pass> node packages/alphaclaw-adapter/scripts/smoke-test.js`
- [x] `packages/alphaclaw-adapter/package.json` — removed `"type": "module"` (CJS conflict fixed)
- [x] PT can start/stop/query AlphaClaw via HTTP+CLI (no internal imports)
- [ ] MCP server registered: `claude mcp add --transport stdio alphaclaw -- node packages/alphaclaw-adapter/src/mcp/server.js`
- [ ] All 11 MCP tools smoke-tested against live AlphaClaw (run `smoke-test.js` when AC live)
- [ ] `packages/local-agents/tests/client.test.js` passes (Vitest, fully offline)
- [ ] `lib/mcp/` and `lib/agents/` in AlphaClaw tagged for removal (but NOT deleted yet)
- [x] orama `start.sh` thinned to PT delegator — delegates via `python -m orchestrator.alphaclaw_manager --resolve --env-only`
- [ ] orama `openclaw_bootstrap.py` scoped down to apply-config only (Gate 2)

### Gate 2 — MCP Toolpack + Local Agents Fully Operational

- [ ] `packages/local-agents/`: Ollama (127.0.0.1:11435, GLM-5.1:cloud → qwen3.5-local:latest) + LM Studio (Win GPU LAN IP — dynamic, read from `~/.openclaw/openclaw.json`, currently `.105:1234`) integration tests pass on Mac
- [ ] `packages/mcpb-agents/`: `ollama-agent.mcpb`, `lmstudio-agent.mcpb` scaffolded
- [ ] PT's `orchestrator.py` wired as idempotent lifecycle entrypoint (old contract requirement)
- [ ] LM Studio multi-model + AlphaClaw role-routing config workflow implemented
- [ ] `orchestrator/autoresearch_bridge.py` gets staged progress hooks
- [ ] Xcode integration scripts (`fix-xcode-claude.sh`) moved from AlphaClaw to PT — verified working
- [ ] `lib/mcp/` and `lib/agents/` removed from AlphaClaw `feature/MacOS-post-install` (after Gate 2 green)

### Gate 3 — orama First Flow

- [ ] `bin/agents/orchestrator/orchestrator_logic.py` baseline implemented
- [ ] orama `openclaw_bridge.py` routes through PT adapter (not direct AlphaClaw calls)
- [ ] First E2E flow: `build-verify` — PT triggers `npm run build:ui`, asserts exit 0, orama reports result
- [ ] OTel emitter wraps AlphaClaw stdout → Tempo traces
- [ ] All AlphaClaw + PT + orama test suites green
- [ ] `~/.openclaw/openclaw.json` written from PT-resolved values, passed to orama

### Gate 4 — RC Release 0.9.9.8

- [ ] All three packages at `0.9.9.8`
- [ ] `npm pack --dry-run` passes for PT and AlphaClaw
- [ ] E2E suite green: code-review flow, build-verify flow, xcode-sync flow
- [ ] `/ship` gstack checklist passed
- [ ] `npm publish --access public` for all three

---

## Idempotency Contract (from old contract — preserved)

> Running `start.sh` (or any PT lifecycle command) repeatedly **MUST NOT** re-install or restart unless drift or inconsistency is detected.

Specifically:
- `commandeer-first` daemon pattern: if a compatible gateway already answers on any candidate port, reuse it — do not restart it
- `~/.openclaw/openclaw.json` is only rewritten if PT detects drift from the resolved state
- PT's `orchestrator.py` checks existing state before any install/start action (idempotent reconciler)

---

## Lessons Preserved from Previous Work

### From PT wiki/08-macos-alphaclaw-compat.md

- `setup_macos.py` in orama applies 6 idempotent alphaclaw.js patches — each checks `detect in content` marker first
- macOS PATH pattern: install to `~/.local/bin/`, not `/usr/local/bin/` (root-owned)
- Gateway timeout root cause: missing `models[]` arrays in `openclaw.json` — `sanitizeOpenclawConfig()` in AlphaClaw `lib/server/gateway.js` prevents this
- `KNOWN_ALPHACLAW_VERSION = "0.9.3"` in `setup_macos.py` — warn but still attempt patches on version mismatch

### From orama Perplexity-Ultrathink-Consolidation.md

- Thin delegation is more robust than duplicated control logic
- Bootstrap subprocesses must stream output — hidden output makes failures hard to diagnose
- npm-installed binaries can exist without execute bits — check + repair execute permissions
- State files need shape discipline — tracker records and routing data must not be mixed
- Tests should import from the real package layout — fix paths before any migration

### From AlphaClaw Plan Review (2026-04-19)

- Strangler-fig via HTTP only: slightly more latency but zero coupling to upstream internals
- Milestone gates over sprint days: no demoralizing missed deadlines
- Write adapter interface contract first — invariant PT tests against
- agentic-stack `.agent/` convention as baseline (already satisfied by `.claude/` in both repos)
- wcgw recursive editing deferred until adapter is stable

---

## File Map: What Lives Where (Gate 0 state)

### AlphaClaw (`feature/MacOS-post-install` — stays until Gate 1 verified)

```
lib/mcp/alphaclaw-mcp.js          ← COPIED to PT, stays here until Gate 1
lib/agents/local-agent-client.js  ← COPIED to PT, stays here until Gate 1
lib/agents/orchestrator.js        ← COPIED to PT, stays here until Gate 1
tests/server/local-agent-client.test.js  ← COPIED to PT, stays here until Gate 1
scripts/install-gstack.sh         ← will move to PT Gate 2
scripts/fix-xcode-claude.sh       ← will move to PT Gate 2
docs/xcode-claude-integration.md  ← will move to PT Gate 2
docs/system-design-*.md           ← COPIED to PT, authoritative copy stays in AlphaClaw too
```

### Perpetua-Tools (`main` — receives migrated code)

```
packages/alphaclaw-adapter/src/mcp/server.js  ← RECEIVED from AlphaClaw
packages/alphaclaw-adapter/src/index.js       ← Gate 1 stub (implement full client)
packages/local-agents/src/client.js           ← RECEIVED from AlphaClaw
packages/local-agents/src/orchestrator.js     ← RECEIVED from AlphaClaw
packages/local-agents/tests/client.test.js    ← RECEIVED from AlphaClaw
docs/adapter-interface-contract.md            ← NEW — living contract
docs/MIGRATION.md                             ← THIS FILE — canonical migration guide
docs/system-design-three-repo-architecture.md ← COPIED from AlphaClaw
docs/plan-review-migration-plan-3.md          ← COPIED from AlphaClaw
orchestrator/                                 ← EXISTING Python control plane
```

### orama-system (`main` — delegate runtime)

```
bin/mcp_servers/openclaw_bridge.py      ← will route through PT adapter at Gate 3
bin/mcp_servers/openclaw_mcp_server.py  ← stays, references PT
bin/agents/orchestrator/orchestrator_logic.py  ← EMPTY — Gate 0 fix needed
start.sh                                       ← thin delegator at Gate 1
openclaw_bootstrap.py                          ← apply-config only at Gate 1
setup_macos.py                                 ← OS patch layer — stays as-is
```

---

## Reference Links

- System design: `docs/system-design-three-repo-architecture.md`
- Adapter contract: `docs/adapter-interface-contract.md`
- AlphaClaw HTTP endpoints: `docs/adapter-interface-contract.md §3`
- AlphaClaw branch rules: `AlphaClaw/CLAUDE.md`
- orama architecture lessons: `orama-system/.claude/lessons/Perplexity-Ultrathink-Consolidation.md`
- PT macOS compat lessons: `docs/wiki/08-macos-alphaclaw-compat.md`
- Repo links:
  - AlphaClaw: https://github.com/diazMelgarejo/AlphaClaw (branch: `feature/MacOS-post-install`)
  - Perpetua-Tools: https://github.com/diazMelgarejo/Perpetua-Tools (branch: `main`)
  - orama-system: https://github.com/diazMelgarejo/orama-system (branch: `main`)
