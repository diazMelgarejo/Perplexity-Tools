# RAG Memory Pipeline — v1 Backport Release Notes

**Date:** 2026-05-22
**Branch:** `feat/rag-backport-v1`
**Commit:** `c689886`
**Status:** Released — 345 tests passing (2 skipped), 0 regressions

---

## What shipped

Four modules backported from the v2 RAG design
(`orama-system/docs/superpowers/plans/2026-05-21-rag-memory-v1-plan.md`)
into `diazMelgarejo/Perpetua-Tools`. All three bug-class gaps identified by
external reviewers (Codex GPT-5.5 + Antigravity Gemini 3.5 Flash, 2026-05-21)
are applied.

### New modules

| File | Purpose | Notes |
|------|---------|-------|
| `orchestrator/gossip_bus.py` | Async SQLite event log with FTS5 BM25 keyword search | Gap 2 fix: `_sanitize_fts_query()` strips FTS5 operators before MATCH so real prompts never silently lose keyword recall |
| `orchestrator/memory_embed.py` | Ollama bge-m3 embed helper (httpx) + `probe_embed_dim()` | Gap 1 fix: dynamic dim discovery — EMBED_MODEL switches no longer corrupt LanceDB schema |
| `orchestrator/memory_store.py` | LanceDB `EmbeddingStore(dim=...)` + `get_lance_store()` singleton | Gap 1 fix: dim parameterized, path+dim keyed singletons, run_in_executor async wrapper |
| `orchestrator/memory_rrf.py` | Pure Reciprocal Rank Fusion (k=60) | Zero deps; merges FTS5 + LanceDB hits, deduplicates, falls back gracefully to FTS5-only |

### Modified files

| File | Change |
|------|--------|
| `orchestrator/fastapi_app.py` | `_bg_startup_tasks` set holds strong reference to `routing-bg` task (Gap 3 / D_GCG-1: prevents GC of in-flight `asyncio.create_task` result) |
| `pyproject.toml` | `aiosqlite>=0.19` added to core deps; `lancedb>=0.6` + `pyarrow>=14.0` added as optional `[rag]` extras |

### New tests

| File | Count | Coverage |
|------|-------|---------|
| `tests/test_gossip_bus.py` | 16 | FTS5 search, sanitizer, emit, embed_status, GC guard (real behavioral), tail() |
| `tests/test_memory_rrf.py` | 6 | Pure RRF merge cases, dedup, top-n, empty inputs |
| `tests/test_memory_store.py` | 7 | LanceDB add/search, empty store, dim env var, singleton keying |

---

## Gap fixes applied

### Gap 1 — Vector dimension mismatch (HARD BUG, Gemini 3.5 critique)

**Before:** LanceDB schema hardcoded `dim=1024`. Switching `EMBED_MODEL` (e.g.
to `nomic-embed-text` at 768 dims) caused schema/write mismatch on first `add()`.

**Fix:**
- `EmbeddingStore.__init__(db_path, *, dim: int = 1024)` — dim is now a parameter
- `probe_embed_dim()` — synchronous Ollama probe at startup; cached process-wide
- `get_lance_store(db_path, *, dim=None)` — resolves dim via: explicit arg →
  `EMBED_DIM` env var → live probe → fallback 1024
- Singleton key includes dim: `"path::dim1024"` so model switches get fresh schemas

### Gap 2 — FTS5 special character silent failure (UX BUG, Gemini 3.5 critique)

**Before:** FTS5 `MATCH` on prompts containing `"`, `:`, `*`, `(`, `)` etc. raised
`OperationalError`, caught by the bare `except`, and returned `[]` — silently
dropping all keyword recall for that query.

**Fix:** `_sanitize_fts_query(query)` strips all FTS5 reserved characters and
lowercases operator keywords (`AND/OR/NOT/NEAR`) before the `MATCH` call.
The `try/except` remains as defence-in-depth.

### Gap 3 — GC guard test was a tautology (TEST BUG, Gemini 3.5 critique)

**Before:** `assert isinstance(_pending_embeds, set)` — trivially true, tests
nothing about the GC-prevention mechanism.

**Fix:** `test_pending_embeds_set_prevents_gc` patches `_embed_and_store` with
an `asyncio.sleep(0.1)` coroutine, then:
1. Asserts `len(_pending_embeds) == 1` during the active window
2. Asserts `len(_pending_embeds) == 0` after the done-callback fires

---

## Architecture notes

### Fail-closed posture
- FTS5 is always available (zero optional deps, stdlib SQLite)
- LanceDB and Ollama are optional; any failure marks `embed_status='failed'`
  and the row is skipped in semantic search — FTS5 still works
- `GossipBus.search()` never raises; returns `[]` on any failure

### Relation to v2 design

This backport implements Items 1–4 from the v1 Backport Candidates table in
the v2 RAG plan. Items 5–7 (GbrainSearchTool, MemoryNode, dispatch_node
wiring) are deferred:
- GbrainSearchTool: conditional on v1 having `@tool` decorator equivalent
- MemoryNode: deferred (requires v2 graph model)
- dispatch_node: deferred (v1 already has LLM dispatch)

The v2.1 EmbeddingCircuitBreaker and v2.5 Reaper daemon remain in
`orama-system/docs/v2/18-rag-and-memory-design.md` for the next sprint.

### Dependency footprint

- **Core:** `aiosqlite>=0.19` (FTS5 GossipBus — added to mandatory deps)
- **Optional:** `pip install perpetua-tools[rag]` installs `lancedb>=0.6` +
  `pyarrow>=14.0`. System degrades to FTS5-only keyword recall if not installed.

---

## How to use GossipBus

```python
from orchestrator.gossip_bus import GossipBus

bus = GossipBus("perpetua.db")
await bus.init_db()          # idempotent — safe on every startup

# Emit events
await bus.emit("dispatch", {"prompt": "summarize Q3 report"})

# FTS5 keyword search (always works)
hits = await bus.search("Q3 report")

# Most recent events
recent = await bus.tail(limit=20)
```

For hybrid FTS5 + LanceDB + RRF search:

```python
from orchestrator.gossip_bus import GossipBus
from orchestrator.memory_store import get_lance_store
from orchestrator.memory_embed import get_embedding
from orchestrator.memory_rrf import rrf_merge

fts_hits = await bus.search(prompt)
embedding = await get_embedding(prompt)
vec_hits = await get_lance_store().search(embedding)
context = rrf_merge(fts_hits, vec_hits, top_n=5)
```

---

## Source references

- Design spec: `orama-system/docs/superpowers/specs/2026-05-21-rag-memory-gstack-design.md`
- Implementation plan: `orama-system/docs/superpowers/plans/2026-05-21-rag-memory-v1-plan.md`
- External reviews: `orama-system/docs/2026-05-21-001--Critique-RAG-ChatGPT-codex-GPT-5.5.md`
                    `orama-system/docs/2026-05-21-002--RAG-Gstack-Review--Antigravity-Gemini-3.5-Flash-Preview.md`
