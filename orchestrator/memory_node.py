"""orchestrator/memory_node.py

Item 6 — MemoryNode v1 wrapper (RAG v1 backport, 2026-05-27).

Async callable that retrieves relevant context for a query by combining:
  1. FTS5 BM25 keyword search via GossipBus (always available)
  2. LanceDB ANN vector search via EmbeddingStore (degrades gracefully)
  3. Optional gbrain semantic search via gbrain_search() (degrades gracefully)
  4. RRF fusion of all hit lists

This is the v1 equivalent of the v2 ``MemoryNode`` graph node design (see
docs/v2/20-rag-and-memory-design.md).  In v1 there is no MiniGraph, so
MemoryNode is a plain async callable, not a graph node.

Usage::

    from orchestrator.memory_node import retrieve_context

    hits = await retrieve_context("Q3 forecasts", top_n=5)
    # hits: [{"text": "...", "row_id": 42}, ...]

Design constraints:
  - Never raises — all backends degrade to [] on any failure.
  - gbrain is opt-in: skipped unless GBRAIN_MEMORY_ENABLED=1 env var is set
    OR caller passes ``use_gbrain=True``.
  - Injection point: supervisor._inject_memory_context() calls this.

Backported from oramasys/* design spec to diazMelgarejo/Perpetua-Tools v1.
Reference: docs/superpowers/plans/2026-05-21-rag-memory-v1-plan.md (Item 6 note)
"""
from __future__ import annotations

import json
import logging
import os
from typing import Any, Optional

_log = logging.getLogger(__name__)

# Top-N returned from the merged RRF list.
_DEFAULT_TOP_N = int(os.environ.get("MEMORY_NODE_TOP_N", "5"))

# opt-in env var: set GBRAIN_MEMORY_ENABLED=1 to include gbrain in every recall
_GBRAIN_ENV_ENABLED = os.environ.get("GBRAIN_MEMORY_ENABLED", "0") == "1"

# Prefer these payload keys when building injectable FTS text (governance-redacted).
_PAYLOAD_TEXT_KEYS = ("prompt", "intent", "text", "message", "detail", "summary")


def _text_from_gossip_payload(payload: Any) -> str:
    """Extract human-readable text from a GossipBus payload for LLM injection."""
    if isinstance(payload, str):
        return payload.strip()
    if not isinstance(payload, dict):
        return ""
    for key in _PAYLOAD_TEXT_KEYS:
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    try:
        return json.dumps(payload, ensure_ascii=False)
    except (TypeError, ValueError):
        return str(payload)


def _normalise_fts_hits(hits: list[dict]) -> list[dict]:
    """
    Normalize GossipBus FTS search rows into recall hit dictionaries that include a usable `text` field.
    
    Scans each element in `hits`, derives a human-readable text value (preferring an existing `text` string, falling back to a representation extracted from `payload`), omits entries without resolvable text, and preserves other fields.
    
    Returns:
        normalized_hits (list[dict]): List of hit dictionaries with a guaranteed `text` string; entries without resolvable text are omitted.
    """
    out: list[dict] = []
    for hit in hits:
        if not isinstance(hit, dict):
            continue
        text = hit.get("text")
        if not (isinstance(text, str) and text.strip()):
            text = _text_from_gossip_payload(hit.get("payload"))
        if not text:
            continue
        normalised = {**hit, "text": text}
        out.append(normalised)
    return out


async def ensure_gossip_db_ready(bus) -> None:
    """
    Ensure a GossipBus instance is initialized for FTS searches.
    
    Performs idempotent schema initialization by calling the bus's init_db() if it has not already been prepared, and marks the bus as ready to avoid repeated initializations. If the bus is already marked ready, this function returns immediately.
    
    Parameters:
        bus: GossipBus-like object with an `init_db()` coroutine and an internal readiness flag attribute.
    """
    if getattr(bus, "_memory_node_db_ready", False):
        return
    await bus.init_db()
    bus._memory_node_db_ready = True  # noqa: SLF001


async def retrieve_context(
    query: str,
    *,
    top_n: int = _DEFAULT_TOP_N,
    use_gbrain: Optional[bool] = None,
    gossip_bus=None,
    lance_store=None,
) -> list[dict]:
    """
    Retrieve ranked memory hit dictionaries relevant to the provided query.
    
    Performs best-effort keyword, vector, and optional semantic searches and fuses results; failures are treated as empty results and do not raise.
    
    Parameters:
        query (str): The user prompt or search query.
        top_n (int): Maximum number of results to return after fusion.
        use_gbrain (Optional[bool]): If None, uses the module's GBRAIN env default; otherwise overrides gbrain usage.
        gossip_bus: Optional pre-constructed GossipBus instance to use instead of the module default.
        lance_store: Optional pre-constructed EmbeddingStore instance to use instead of the module default.
    
    Returns:
        list[dict]: Ranked list of hit dictionaries, each with at least a `text` key; returns an empty list when no matches are found or on internal failures.
    """
    if not query or not query.strip():
        return []

    _use_gbrain = _GBRAIN_ENV_ENABLED if use_gbrain is None else use_gbrain

    fts_hits: list[dict] = []
    vec_hits: list[dict] = []
    gbrain_hits: list[dict] = []

    # ── 1. FTS5 keyword search ────────────────────────────────────────────────
    try:
        bus = gossip_bus or _get_default_bus()
        if bus is not None:
            await ensure_gossip_db_ready(bus)
            fts_hits = _normalise_fts_hits(
                await bus.search(query, limit=top_n * 2)
            )
    except Exception as exc:
        _log.debug("memory_node: FTS5 search error — %s", exc)

    # ── 2. LanceDB ANN vector search ──────────────────────────────────────────
    try:
        from orchestrator.memory_store import lancedb_available  # noqa: PLC0415

        store = lance_store or _get_default_store()
        if store is not None and lancedb_available():
            from orchestrator.memory_embed import get_embedding  # noqa: PLC0415

            embedding = await get_embedding(query)
            if embedding:
                vec_hits = await store.search(embedding, limit=top_n * 2)
    except Exception as exc:
        _log.debug("memory_node: vector search error — %s", exc)

    # ── 3. Optional gbrain semantic search ────────────────────────────────────
    if _use_gbrain:
        try:
            from orchestrator.gbrain_search import gbrain_search  # noqa: PLC0415
            gbrain_hits = await gbrain_search(query, limit=top_n)
        except Exception as exc:
            _log.debug("memory_node: gbrain search error — %s", exc)

    # ── 4. RRF fusion ─────────────────────────────────────────────────────────
    if not fts_hits and not vec_hits and not gbrain_hits:
        return []

    try:
        from orchestrator.memory_rrf import rrf_merge  # noqa: PLC0415
        # Merge FTS + vector first, then blend in gbrain
        fused = rrf_merge(fts_hits, vec_hits, top_n=top_n * 2)
        if gbrain_hits:
            fused = rrf_merge(fused, gbrain_hits, top_n=top_n)
        else:
            fused = fused[:top_n]
        return fused
    except Exception as exc:
        _log.debug("memory_node: RRF merge error — %s", exc)
        # Fallback: return FTS hits unranked
        return (fts_hits or vec_hits or gbrain_hits)[:top_n]


# ── Singleton helpers ─────────────────────────────────────────────────────────

_default_bus = None
_default_store = None


def _get_default_bus():
    """
    Get the module-level GossipBus singleton whose database path is resolved from the supervisor.
    
    Returns:
        GossipBus or None: Cached GossipBus instance if instantiation succeeded, otherwise None.
    """
    global _default_bus  # noqa: PLW0603
    if _default_bus is None:
        try:
            from orchestrator.gossip_bus import GossipBus, resolve_gossip_db_path  # noqa: PLC0415
            _default_bus = GossipBus(resolve_gossip_db_path())
        except Exception as exc:
            _log.debug("memory_node: could not instantiate GossipBus — %s", exc)
    return _default_bus


def _get_default_store():
    """Return module-level EmbeddingStore singleton."""
    global _default_store  # noqa: PLW0603
    if _default_store is None:
        try:
            from orchestrator.memory_store import get_lance_store  # noqa: PLC0415
            _default_store = get_lance_store()
        except Exception as exc:
            _log.debug("memory_node: could not instantiate EmbeddingStore — %s", exc)
    return _default_store


def reset_singletons() -> None:
    """Reset module-level singletons (test helper only)."""
    global _default_bus, _default_store  # noqa: PLW0603
    _default_bus = None
    _default_store = None
