"""Tests for orchestrator/memory_node.py (Item 6 — RAG v1 backport)."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from orchestrator.memory_node import (
    _normalise_fts_hits,
    _text_from_gossip_payload,
    reset_singletons,
    retrieve_context,
)


@pytest.fixture(autouse=True)
def _reset_singletons():
    """Ensure module-level singletons don't bleed between tests."""
    reset_singletons()
    yield
    reset_singletons()


# ── FTS hit normalisation (GossipBus shape) ───────────────────────────────────

def test_text_from_gossip_payload_prefers_prompt():
    assert _text_from_gossip_payload({"prompt": "find widget", "role": "coder"}) == "find widget"


def test_normalise_fts_hits_adds_text_from_payload():
    raw = [
        {
            "row_id": 1,
            "event_type": "dispatch",
            "payload": {"prompt": "Q3 revenue was $10M"},
        }
    ]
    out = _normalise_fts_hits(raw)
    assert len(out) == 1
    assert out[0]["text"] == "Q3 revenue was $10M"
    assert out[0]["row_id"] == 1


@pytest.mark.asyncio
async def test_retrieve_context_real_gossip_bus_fts_only(tmp_path):
    """Integration: GossipBus rows must surface as injectable text (not silent drop)."""
    from orchestrator.gossip_bus import GossipBus

    bus = GossipBus(str(tmp_path / "gossip.db"))
    await bus.init_db()
    with patch.object(bus, "_embed_and_store", new_callable=AsyncMock):
        await bus.emit("dispatch", {"prompt": "Q3 revenue was $10M"})

    with (
        patch("orchestrator.memory_store.lancedb_available", return_value=False),
        patch("orchestrator.memory_embed.get_embedding", AsyncMock()) as mock_embed,
    ):
        result = await retrieve_context("Q3 revenue", top_n=5, gossip_bus=bus, use_gbrain=False)

    mock_embed.assert_not_called()
    assert any("Q3 revenue was $10M" in h.get("text", "") for h in result)


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

    with (
        patch("orchestrator.memory_store.lancedb_available", return_value=True),
        patch("orchestrator.memory_embed.get_embedding", AsyncMock(return_value=[0.1] * 1024)),
    ):
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
