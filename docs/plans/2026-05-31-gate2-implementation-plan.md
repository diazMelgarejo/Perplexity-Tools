# Gate 2 Implementation Plan — Work Items #4, #6, #7

> **Date:** 2026-05-31 · **Status:** in progress on `main`
> **Parent:** [`docs/2026-05-31-tri-repo-alignment-completion-plan.md`](../2026-05-31-tri-repo-alignment-completion-plan.md)
> **Gate ladder:** [`docs/MIGRATION.md`](../MIGRATION.md)

## Scope

| # | Deliverable | SSEA |
|---|-------------|------|
| **7** | `openclaw_config` + `role_routing` on `reconcile_gateway()` / runtime payload | **ACC** — enables orama `apply_runtime_payload` (**D2-B**) |
| **4** | `stopServer()` + PID file in `packages/alphaclaw-adapter` | **SAF** — cross-process lifecycle |
| **6a** | `packages/local-agents` Vitest runnable (package `devDependency`) | **EFF** |
| **6b** | `packages/mcpb-agents` → canonical paths + `mcp-stdio.mjs` entry | **ACC** — community `.mcpb` pattern |

Out of scope for this commit: live AlphaClaw smoke, `lib/mcp` retirement, Gate 3 bridge.

## Phase 1 — Wire `openclaw_config` (#7)

### Design

1. `alphaclaw_bootstrap.py --bootstrap --json` already returns `openclaw_config` and `role_routing`.
2. `bootstrap_alphaclaw()` in `alphaclaw_manager.py` will capture JSON stdout (stderr streamed only when not using capture).
3. `AlphaClawState` gains `gateway_url`, `openclaw_config`, `role_routing`.
4. `reconcile_gateway()` copies them into `gateway` section of runtime payload.
5. orama `apply_runtime_payload()` can consume `.state/runtime_payload.json` without re-bootstrap.

### Verification

```bash
python -m pytest tests/test_control_plane.py -q
python orchestrator.py bootstrap --non-interactive --json  # manual: inspect .state/runtime_payload.json
```

### Rollback

Revert `orchestrator/alphaclaw_manager.py` + `orchestrator/control_plane.py`; payload consumers ignore unknown keys.

## Phase 2 — `stopServer()` + PID file (#4)

### Design

- PID file: `$ALPHACLAW_PID_FILE` or `$ALPHACLAW_ROOT/alphaclaw-server.pid` (default under install dir).
- `startServer()` writes PID after spawn; `stopServer()` sends SIGTERM, waits, unlinks file.
- `ensureRunning()` unchanged; commandeer path does not write PID (no child owned).

### Verification

```bash
cd packages/alphaclaw-adapter && npm test  # stop-server unit tests
```

## Phase 3 — Vitest (#6a)

- Add `vitest` to `packages/local-agents/package.json` `devDependencies`.
- Script: `vitest run` via `npx` (no repo-root `node_modules`).

```bash
cd packages/local-agents && npm install && npm test
node --test packages/local-agents/tests/path-boundary.test.cjs
```

## Phase 4 — mcpb agents (#6b)

### Canonical paths (from `packages/mcpb-agents/`)

| Bundle | Entry |
|--------|--------|
| `ollama-agent.mcpb` | `../local-agents/src/mcp-stdio.mjs` + `--backend ollama` |
| `lmstudio-agent.mcpb` | `../local-agents/src/mcp-stdio.mjs` + `--backend lmstudio` |

### `mcp-stdio.mjs`

- Stdio MCP server (SDK) exposing `local_agent_*` tools pinned to one backend.
- Reuses `orchestrator.js` delegates + path boundary from `local-agents`.

### Community validation

- Paths resolve to `packages/local-agents` (not repo-root `local-agents/`).
- Each bundle is a separate process (process-per-model pattern per Claude-Desktop-LLM / MCPB references).

## Execution order

```text
#7 openclaw_config → #4 stopServer → #6a vitest → #6b mcpb → pytest control_plane
```

## Post-merge gates (not this PR)

1. Live `smoke-test.js` with D4 auth precedence.
2. Retire AlphaClaw `lib/mcp` on `feature/MacOS-post-install` @ `b540eca1`.
3. Gate 3: orama bridge via PT adapter.
