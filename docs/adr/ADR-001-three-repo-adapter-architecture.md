# ADR-001: Three-Repo Layered Architecture with HTTP-Only AlphaClaw Adapter

**Status:** Accepted
**Date:** 2026-04-20
**Deciders:** cyre (diazMelgarejo)

---

## Context

AlphaClaw (`diazMelgarejo/AlphaClaw`) is a macOS ARM64 port of `chrysb/alphaclaw` — an active upstream. The system must evolve to support Claude Code, Xcode 26 mcpbridge, Ollama, and LM Studio agents co-managing AlphaClaw installations, while keeping the fork clean and upstreamable.

Two companion repos exist (`Perpetua-Tools` → renamed `Perpetua-Tools`, `orama-system` → renamed `orama-system`) that accumulated orchestration logic in conflict with each other. The previous contract had gateway routing split between PT and orama, direct Python patching of the AlphaClaw npm package, and no stable interface boundary.

**Forces at play:**
- AlphaClaw tracks an active upstream (`chrysb/alphaclaw`). Every internal import creates a merge conflict surface.
- orama-system must remain a stateless execution layer — it must not re-own gateway decisions.
- Local agents (Ollama, LM Studio) need a unified client that works offline and survives backend failures.
- MCP protocol requires a standalone stdio server process — not an HTTP endpoint inside AlphaClaw.
- The rename from Perpetua-Tools eliminates trademark risk (`Perplexity` is an active AI company).

---

## Decision

Adopt a **three-repo layered architecture** where PT drives AlphaClaw exclusively through its **CLI and HTTP surface** — never via `require()` or direct file patching at runtime.

```
AlphaClaw (Layer 1 — infrastructure / managed dependency)
    │  node bin/alphaclaw.js + GET /health, /api/status, etc.
    ▼
Perpetua-Tools (Layer 2 — middleware / adapters / tooling)
    │  typed adapter contract (docs/adapter-interface-contract.md)
    ▼
orama-system (Layer 3 — orchestration / meta-intelligence / delegate runtime)
```

**PT is the single authoritative control plane** for: gateway discovery, route choice, lifecycle (start/stop/restart), LM Studio routing, and local agent dispatch. orama only applies PT-resolved config and exposes execution interfaces.

---

## Options Considered

### Option A: HTTP-only adapter (chosen)

PT spawns `node bin/alphaclaw.js start` and communicates via `GET /health`, `GET /api/status`, `POST /api/gateway/restart`, etc. The AlphaClaw MCP server (`packages/alphaclaw-adapter/src/mcp/server.js`) is a standalone stdio process managed by PT.

| Dimension | Assessment |
|-----------|------------|
| Upstream coupling | **Low** — zero imports from AlphaClaw internals |
| Latency | Slightly higher (HTTP round-trip) but irrelevant at human-interaction timescales |
| Crash isolation | **High** — AlphaClaw crash doesn't kill PT or MCP server |
| Testability | **High** — adapter can be tested with mock HTTP server |
| Upstreamability | **High** — AlphaClaw stays a clean fork, PRs mergeable |

**Pros:** Zero coupling to upstream internals; adapter absorbs churn from upstream merges; MCP server survives AlphaClaw restarts; strangler-fig lets us migrate incrementally.
**Cons:** Slightly more ceremony to add new capabilities (must add HTTP endpoint + adapter method).

### Option B: Python direct import (rejected)

PT imports AlphaClaw internals via `require()` or calls `openclaw_bootstrap.py` methods directly.

| Dimension | Assessment |
|-----------|------------|
| Upstream coupling | **High** — every upstream merge is a potential breaking change |
| Crash isolation | **Low** — tight process coupling |
| Testability | **Low** — requires AlphaClaw's full dependency tree |
| Upstreamability | **Low** — fork diverges, upstream PRs rejected |

Rejected. Identified in old contract as the source of gateway decision authority being split.

### Option C: Function inside AlphaClaw's Express server

Mount an `/mcp` HTTP route in AlphaClaw that speaks JSON-RPC 2.0 over HTTP.

| Dimension | Assessment |
|-----------|------------|
| Upstream coupling | **High** — MCP logic lands in AlphaClaw |
| Crash isolation | **None** — AlphaClaw crash kills MCP |
| Upstreamability | **Low** — violates "no PT code in AlphaClaw" invariant |

Rejected immediately. Violates the core invariant.

---

## Trade-off Analysis

**Key trade-off accepted:** HTTP adapter adds a layer of indirection. In exchange, we get zero upstream coupling — when `chrysb/alphaclaw` merges a breaking change, only `docs/adapter-interface-contract.md` and `packages/alphaclaw-adapter/src/index.js` need updating, not orama or any consumer of PT's API.

**Resolved tension — macOS patching vs lifecycle management:** `setup_macos.py` in orama applies 6 idempotent patches to the AlphaClaw npm binary at OS-install time (one-time, macOS-only). This is OS-level setup, not lifecycle management. PT's adapter then calls the already-patched binary. These are complementary, not competing.

**Resolved tension — Python control plane vs Node.js packages:** Python `orchestrator/` in PT owns PT's own orchestration decisions (model routing, cost guard, LAN discovery, autoresearch). Node.js `packages/` owns MCP protocol + AlphaClaw HTTP communication. Both coexist in PT with no conflict.

---

## Verified Pre-Conditions (Gate 0 audit, 2026-04-20)

All three old-contract concerns resolved before Gate 1 work begins:

| Concern | Status | Evidence |
|---------|--------|---------|
| `bin/agents/orchestrator/orchestrator_logic.py` empty | ✅ **Resolved** | Full implementation: `create_task_state()`, `advance_stage()`, stage machine |
| `tests/test_orchestrator.py` stale imports | ✅ **Resolved** | Already uses `bin/shared` + `bin/agents/orchestrator`; `pythonpath=["."]` in `pyproject.toml` |
| orama orchestrator tests passing | ✅ **19/19 PASS** | Verified in sandbox against live code |
| Gateway decision authority split | ✅ **Resolved by architecture** | PT is sole authority; orama delegates |

---

## Consequences

**What becomes easier:**
- AlphaClaw upstream merges: diff `adapter-interface-contract.md`, update one adapter file
- Testing PT without running AlphaClaw: mock the HTTP surface
- Adding new MCP tools: add to `packages/alphaclaw-adapter/src/mcp/server.js`, no AlphaClaw change needed
- orama stays stateless: it reads PT-resolved config, never makes gateway decisions

**What becomes harder:**
- Adding a capability that has no AlphaClaw HTTP endpoint requires either: (a) adding the endpoint upstream, or (b) using the CLI surface
- Debugging requires understanding two process boundaries (PT ↔ AlphaClaw)

**What we'll need to revisit:**
- Gate 1: full `packages/alphaclaw-adapter/src/index.js` — implement `status()`, `login()`, `gatewayStatus()`, `restartGateway()`, `tailLogs()`
- Gate 2: `start.sh` in orama → thin PT delegator; `openclaw_bootstrap.py` → apply-config only
- Gate 3: `openclaw_bridge.py` in orama routes through PT adapter instead of direct AlphaClaw calls
- `ALPHACLAW_ROOT` env var must be set correctly when PT and AlphaClaw are not siblings

---

## Action Items

### Gate 0 (complete)
- [x] Scaffold `packages/alphaclaw-adapter/`, `packages/local-agents/`, `packages/mcpb-agents/`
- [x] Copy AlphaClaw MCP server + local agent client + orchestrator to PT packages/
- [x] Update import paths in PT test file (`../../lib/agents/` → `../src/`)
- [x] Write `docs/adapter-interface-contract.md` with verified HTTP endpoints
- [x] Update CLAUDE.md in PT and orama with new identities
- [x] Verify orama 19/19 tests pass
- [x] Copy `install-gstack.sh` and `fix-xcode-claude.sh` to PT scripts/

### Gate 1 (next)
- [ ] Implement full `packages/alphaclaw-adapter/src/index.js` HTTP client
- [ ] Register MCP server: `claude mcp add --transport stdio alphaclaw -- node packages/alphaclaw-adapter/src/mcp/server.js`
- [ ] Smoke-test all 11 MCP tools against live AlphaClaw
- [ ] Reduce orama `start.sh` to PT delegator
- [ ] Scope `openclaw_bootstrap.py` to apply-config only
- [ ] Tag `lib/mcp/` + `lib/agents/` in AlphaClaw for removal (do not delete yet)

### Gate 2 (after Gate 1 green)
- [ ] `packages/mcpb-agents/`: `ollama-agent.mcpb`, `lmstudio-agent.mcpb`
- [ ] Wire PT `orchestrator.py` as idempotent lifecycle entrypoint
- [ ] Move gstack install + Xcode scripts from AlphaClaw to PT (scripts already copied)
- [ ] Remove `lib/mcp/` + `lib/agents/` from AlphaClaw `feature/MacOS-post-install`

---

## References

- `docs/MIGRATION.md` — full migration sequence
- `docs/adapter-interface-contract.md` — living HTTP contract
- `docs/system-design-three-repo-architecture.md` — architecture diagram + milestone gates
- `docs/plan-review-migration-plan-3.md` — critique and steelman
- `orama-system/.claude/lessons/Perplexity-Orama-Consolidation.md` — lessons from prior work
- `docs/wiki/08-macos-alphaclaw-compat.md` — macOS patching lessons
