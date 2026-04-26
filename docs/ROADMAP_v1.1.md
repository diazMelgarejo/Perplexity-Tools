# Roadmap: v1.1+ — Deferred Items

**Status:** TODO — not scheduled for v1.0 RC

For the full v1.1+ roadmap including MCP-optional transport, Redis coordination,
and multi-instance PT, see:
[orama-system/docs/ROADMAP_v1.1.md](https://github.com/diazMelgarejo/orama-system/blob/main/docs/ROADMAP_v1.1.md)

---

## 0. Shield git repo from saving SOUL.md → IDENTITY.md → USER.md → task context → memory, should be gitignored.

Only specialized "AGENTS.md" should exist and be reproduced for agent alignment and assignment?

Only the top-level orchestrator and final validator has elevated privileged access, all other agent sessions are always ephemeral and least privileged.

---

## 1. PT-specific v1.1 items:

### Implementation Order — Read Before Starting

> **Do Tier 2 (orama-system server pipeline) before Tier 1 (PT client infrastructure).**
>
> Tier 2 is tracked in [orama-system/docs/ROADMAP_v1.1.md](https://github.com/diazMelgarejo/orama-system/blob/main/docs/ROADMAP_v1.1.md).
> Tier 1 work here starts only after Tier 2 is merged and tested.
>
> **The HTTP bridge stays fully functional at every intermediate state.**
> No PT feature breaks if MCP work is incomplete or abandoned mid-flight:
> - Before Tier 2: MCP client (if built) detects stub response and falls back to HTTP automatically.
> - After Tier 2, before Tier 1: Ollama pipeline runs in MCP server; HTTP bridge unchanged, still primary.
> - After both tiers: PT tries MCP, falls back to HTTP on any subprocess failure. HTTP is never removed.

### Tier 1 — MCP client infrastructure (PT only, no orama-system changes needed)
- [ ] Create `orchestrator/orama_mcp_client.py`
  - `OramaMCPClient(server_cmd: list[str], timeout: float = 120.0)` class
  - `_start()`: spawn subprocess, send `initialize` JSON-RPC, verify `capabilities`
  - `_rpc(method, params) -> dict`: line-delimited JSON-RPC framing over stdin/stdout
  - `call_solve(task, task_type) -> dict`: send `tools/call` for `orama_solve`
  - `stop()` + context manager (`__enter__`/`__exit__`)
  - Raise on: subprocess crash, timeout, stub-only response (no `result` key) — caller falls back to HTTP
- [ ] Add `call_orama_mcp_or_bridge()` to `orchestrator/orama_bridge.py`
  - Check `ORAMA_MCP_SERVER_CMD` env var; if unset → HTTP only
  - Try MCP client; on any exception fall back to `call_orama_bridge()`
  - Add `"transport": "mcp"` or `"transport": "http"` to response envelope
- [ ] Update `orchestrator/fastapi_app.py` call site (~5 lines) to use `call_orama_mcp_or_bridge`
- [ ] Add `ORAMA_MCP_SERVER_CMD` to `.env.example` with documentation
- [ ] Create `tests/test_orama_mcp_client.py`
  - MCP success path (mock subprocess returning full result)
  - Subprocess crash → HTTP fallback
  - Stub response (task_id only, no `result`) → HTTP fallback
- [ ] Switch `httpx.post` (sync) to `httpx.AsyncClient` in `orama_bridge.py`

### Tier 2 — MCP pipeline integration (requires orama-system Tier 2 first)
- [ ] Update `call_orama_mcp_or_bridge()` to trust and return MCP result (stop always falling back)
- [ ] End-to-end integration test: PT → MCP subprocess → Ollama → result round-trip

### Redis coordination (v1.1+)
- [ ] Redis optional backend for `.state/agents.json`
- [ ] Multi-instance PT coordination via Redis pub/sub
