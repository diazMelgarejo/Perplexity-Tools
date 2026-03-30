# Roadmap: v1.1+ — Deferred Items

**Status:** TODO — not scheduled for v1.0 RC

For the full v1.1+ roadmap including MCP-optional transport, Redis coordination,
and multi-instance PT, see:
[ultrathink-system/docs/ROADMAP_v1.1.md](https://github.com/diazMelgarejo/ultrathink-system/blob/main/docs/ROADMAP_v1.1.md)

## PT-specific v1.1 items:

### Tier 1 — MCP client infrastructure (PT only, no ultrathink-system changes needed)
- [ ] Create `orchestrator/ultrathink_mcp_client.py`
  - `UltrathinkMCPClient(server_cmd: list[str], timeout: float = 120.0)` class
  - `_start()`: spawn subprocess, send `initialize` JSON-RPC, verify `capabilities`
  - `_rpc(method, params) -> dict`: line-delimited JSON-RPC framing over stdin/stdout
  - `call_solve(task, task_type) -> dict`: send `tools/call` for `ultrathink_solve`
  - `stop()` + context manager (`__enter__`/`__exit__`)
  - Raise on: subprocess crash, timeout, stub-only response (no `result` key) — caller falls back to HTTP
- [ ] Add `call_ultrathink_mcp_or_bridge()` to `orchestrator/ultrathink_bridge.py`
  - Check `ULTRATHINK_MCP_SERVER_CMD` env var; if unset → HTTP only
  - Try MCP client; on any exception fall back to `call_ultrathink_bridge()`
  - Add `"transport": "mcp"` or `"transport": "http"` to response envelope
- [ ] Update `orchestrator/fastapi_app.py` call site (~5 lines) to use `call_ultrathink_mcp_or_bridge`
- [ ] Add `ULTRATHINK_MCP_SERVER_CMD` to `.env.example` with documentation
- [ ] Create `tests/test_ultrathink_mcp_client.py`
  - MCP success path (mock subprocess returning full result)
  - Subprocess crash → HTTP fallback
  - Stub response (task_id only, no `result`) → HTTP fallback
- [ ] Switch `httpx.post` (sync) to `httpx.AsyncClient` in `ultrathink_bridge.py`

### Tier 2 — MCP pipeline integration (requires ultrathink-system Tier 2 first)
- [ ] Update `call_ultrathink_mcp_or_bridge()` to trust and return MCP result (stop always falling back)
- [ ] End-to-end integration test: PT → MCP subprocess → Ollama → result round-trip

### Redis coordination (v1.1+)
- [ ] Redis optional backend for `.state/agents.json`
- [ ] Multi-instance PT coordination via Redis pub/sub
