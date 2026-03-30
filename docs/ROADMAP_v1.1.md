# Roadmap: v1.1+ — Deferred Items

**Status:** TODO — not scheduled for v1.0 RC

For the full v1.1+ roadmap including MCP-optional transport, Redis coordination,
and multi-instance PT, see:
[ultrathink-system/docs/ROADMAP_v1.1.md](https://github.com/diazMelgarejo/ultrathink-system/blob/main/docs/ROADMAP_v1.1.md)

## PT-specific v1.1 items:
- [ ] MCP client for ultrathink (`orchestrator/ultrathink_mcp_client.py`)
- [ ] Redis optional backend for `.state/agents.json`
- [ ] Switch `httpx.post` (sync) to `httpx.AsyncClient` in bridge
- [ ] Multi-instance PT coordination via Redis pub/sub
