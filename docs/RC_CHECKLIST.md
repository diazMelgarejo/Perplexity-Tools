# v1.0 RC Deliverables — Stamp Criteria

This checklist defines the minimum bar for tagging `v1.0-rc` on both repos.
All items must be checked before pushing the tag.

---

## Infrastructure

- [x] Redis soft import in `orchestrator.py` — no `ImportError` if package absent
- [x] ECC sync gate — `ECC_SYNC_ENABLED` env var in `ecc_tools_sync.py` (default: true);
      `conftest.py` sets it to false at test session scope
- [x] Async httpx fix — `ultrathink_bridge.py` uses `httpx.AsyncClient` in the new
      `call_ultrathink_mcp_or_bridge()` wrapper (was blocking the FastAPI event loop)

## Transport

- [x] HTTP Bridge (`POST /ultrathink`, port 8001) — active v1.0 RC primary transport
- [x] MCP-Optional Tier 1 — `orchestrator/ultrathink_mcp_client.py` + `call_ultrathink_mcp_or_bridge()`
      with HTTP fallback; `ULTRATHINK_MCP_SERVER_CMD` env var for opt-in
- [x] `"transport": "mcp" | "http"` key surfaced in `/orchestrate` response envelope
- [ ] MCP Tier 2 (ultrathink-system real `_solve()` pipeline) — deferred to v1.1

## Tests & CI

- [x] 114/114 tests passing in Perplexity-Tools (108 pre-RC + 6 MCP client tests)
- [x] CI green on both repos (`.github/workflows/ci.yml`)
- [x] `tests/test_ultrathink_mcp_client.py` — MCP success path, MCP failure → HTTP fallback

## Documentation

- [x] Transport naming corrected: HTTP Bridge (v1.0 RC) / MCP-Optional (v1.1)
- [x] `docs/PERPLEXITY_BRIDGE.md` — MCP-Optional section with 3-state safety guarantee
- [x] `docs/SYNC_ANALYSIS.md` — updated to v0.9.9.0, v1.0-rc update entry added
- [x] `docs/api-reference.md` — MCP stub status documented, Tier 2 design noted
- [x] `docs/faq.md` — MCP transport status + recommended sequencing Q&A
- [x] Both `docs/ROADMAP_v1.1.md` — Tier 1 and Tier 2 checklists with sequencing guarantee
- [x] `.env.example` — `ULTRATHINK_MCP_SERVER_CMD` documented with opt-in notes
- [x] `CHANGELOG.md` — v1.0-rc entry added (both repos)

## Release Gate

- [x] Manual end-to-end smoke test (2026-03-30):
      `POST /orchestrate` `task_type=deep_reasoning` → ultrathink HTTP (port 8001)
      → Ollama `qwen3:4b-instruct` (localhost fallback) → non-empty `result` ✓
      Response: `status=created`, `transport=http`, result non-empty.
- [ ] `git tag v1.0-rc` pushed to `diazMelgarejo/Perplexity-Tools`
- [ ] `git tag v1.0-rc` pushed to `diazMelgarejo/ultrathink-system`

---

**Once all boxes are checked, stamp the tag:**
```bash
git tag v1.0-rc && git push origin v1.0-rc
```
