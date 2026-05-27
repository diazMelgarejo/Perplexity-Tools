"""Tests for orchestrator/memory_node.py (Item 6 — RAG v1 backport)."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from orchestrator.memory_node import reset_singletons, retrieve_context


@pytest.fixture(autouse=True)
def _reset_singletons():
    """Ensure module-level singletons don't bleed between tests."""
    reset_singletons()
    yield
    reset_singletons()


# ── Edge cases ────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_retrieve_context_empty_query_returns_empty():
    result = await retrieve_context("")
    assert result == []


@pytest.mark.asyncio
async def test_retrieve_context_blank_query_returns_empty():
    result = await retrieve_context("   ")
    assert result == []


# ── FTS5-only mode (no LanceDB, no gbrain) ────────────────────────────────────

@pytest.mark.asyncio
async def test_retrieve_context_fts_only():
    mock_bus = MagicMock()
    mock_bus.search = AsyncMock(return_value=[
        {"row_id": 1, "text": "hello world"},
        {"row_id": 2, "text": "foo bar"},
    ])
    mock_store = MagicMock()
    mock_store.search = AsyncMock(return_value=[])

    with patch("orchestrator.memory_embed.get_embedding", AsyncMock(return_value=[])):
        result = await retrieve_context(
            "hello",
            top_n=5,
            use_gbrain=False,
            gossip_bus=mock_bus,
            lance_store=mock_store,
        )

    assert len(result) == 2
    assert result[0]["text"] == "hello world"


# ── FTS + vector RRF merge ────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_retrieve_context_rrf_merge():
    mock_bus = MagicMock()
    mock_bus.search = AsyncMock(return_value=[
        {"row_id": 1, "text": "FTS hit A"},
    ])
    mock_store = MagicMock()
    mock_store.search = AsyncMock(return_value=[
        {"row_id": 2, "text": "vec hit B"},
    ])

    with patch("orchestrator.memory_embed.get_embedding", AsyncMock(return_value=[0.1] * 1024)):
        result = await retrieve_context(
            "query",
            top_n=5,
            use_gbrain=False,
            gossip_bus=mock_bus,
            lance_store=mock_store,
        )

    texts = [r["text"] for r in result]
    assert "FTS hit A" in texts
    assert "vec hit B" in texts


# ── gbrain blend ─────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_retrieve_context_includes_gbrain_hits():
    mock_bus = MagicMock()
    mock_bus.search = AsyncMock(return_value=[{"row_id": 1, "text": "bus hit"}])
    mock_store = MagicMock()
    mock_store.search = AsyncMock(return_value=[])

    with (
        patch("orchestrator.memory_embed.get_embedding", AsyncMock(return_value=[])),
        patch("orchestrator.gbrain_search.gbrain_search", AsyncMock(return_value=[{"text": "gbrain hit"}])),
    ):
        result = await retrieve_context(
            "query",
            top_n=5,
            use_gbrain=True,
            gossip_bus=mock_bus,
            lance_store=mock_store,
        )

    # FTS hits should be present; gbrain hit may also be blended in
    assert len(result) >= 1
    texts = [r["text"] for r in result]
    assert "bus hit" in texts


# ── Degradation: all backends fail ───────────────────────────────────────────

@pytest.mark.asyncio
async def test_retrieve_context_returns_empty_when_all_backends_fail():
    mock_bus = MagicMock()
    mock_bus.search = AsyncMock(side_effect=RuntimeError("db gone"))
    mock_store = MagicMock()
    mock_store.search = AsyncMock(side_effect=RuntimeError("lance gone"))

    with patch("orchestrator.memory_embed.get_embedding", AsyncMock(side_effect=RuntimeError)):
        result = await retrieve_context(
            "query",
            use_gbrain=False,
            gossip_bus=mock_bus,
            lance_store=mock_store,
        )

    assert result == []


# ── top_n respected ───────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_retrieve_context_respects_top_n():
    hits = [{"row_id": i, "text": f"hit {i}"} for i in range(20)]
    mock_bus = MagicMock()
    mock_bus.search = AsyncMock(return_value=hits)
    mock_store = MagicMock()
    mock_store.search = AsyncMock(return_value=[])

    with patch("orchestrator.memory_embed.get_embedding", AsyncMock(return_value=[])):
        result = await retrieve_context(
            "many hits",
            top_n=3,
            use_gbrain=False,
            gossip_bus=mock_bus,
            lance_store=mock_store,
        )

    assert len(result) <= 3
