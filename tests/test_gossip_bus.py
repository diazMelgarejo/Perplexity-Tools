"""tests/test_gossip_bus.py

Tests for orchestrator/gossip_bus.py — FTS5 search, _pending_embeds GC guard,
embed_status column.  No Ollama or LanceDB required — embed pipeline is
mock-isolated.

Covers acceptance gates G1, G2, G3, G5 from:
  docs/superpowers/plans/2026-05-21-rag-memory-v1-plan.md (backport section)
"""
from __future__ import annotations

import asyncio
import pytest

from orchestrator.gossip_bus import GossipBus, _pending_embeds, _sanitize_fts_query


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
async def bus(tmp_path):
    db = str(tmp_path / "test.db")
    b = GossipBus(db)
    await b.init_db()
    return b


# ---------------------------------------------------------------------------
# _sanitize_fts_query unit tests (Gap 2 / D_FTS-1)
# ---------------------------------------------------------------------------

def test_sanitize_strips_quotes():
    assert '"hello"' not in _sanitize_fts_query('"hello world"')


def test_sanitize_strips_colon():
    result = _sanitize_fts_query("event_type:dispatch")
    assert ":" not in result


def test_sanitize_lowercases_fts_keywords():
    result = _sanitize_fts_query("hello AND world")
    assert "and" in result
    assert "AND" not in result


def test_sanitize_empty_returns_empty():
    assert _sanitize_fts_query("") == ""


def test_sanitize_preserves_plain_terms():
    result = _sanitize_fts_query("blue widget quarterly report")
    assert "blue" in result
    assert "widget" in result


# ---------------------------------------------------------------------------
# GossipBus FTS5 search tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_search_empty_query_returns_empty(bus):
    await bus.emit("dispatch", {"prompt": "hello world"})
    result = await bus.search("")
    assert result == []


@pytest.mark.asyncio
async def test_search_finds_exact_payload_keyword(bus):
    # Use non-sensitive keys — prompts are redacted before durable FTS store.
    await bus.emit("dispatch", {"intent": "find the blue widget"})
    await bus.emit("route", {"intent": "unrelated thing"})
    hits = await bus.search("blue widget")
    assert len(hits) == 1
    assert hits[0]["event_type"] == "dispatch"
    assert "blue widget" in hits[0]["payload"]["intent"]


@pytest.mark.asyncio
async def test_search_filters_by_event_type(bus):
    await bus.emit("dispatch", {"intent": "run the calculation"})
    await bus.emit("error", {"detail": "run the calculation", "error": "timeout"})
    hits = await bus.search("run the calculation", event_type="error")
    assert len(hits) == 1
    assert hits[0]["event_type"] == "error"
    assert "run the calculation" in hits[0]["payload"]["detail"]


@pytest.mark.asyncio
async def test_search_returns_empty_for_no_match(bus):
    await bus.emit("dispatch", {"prompt": "completely different content"})
    hits = await bus.search("xyzzy_no_match_ever")
    assert hits == []


@pytest.mark.asyncio
async def test_search_handles_special_chars_without_raising(bus):
    """Query with FTS5 operators must not raise — sanitizer should handle them."""
    await bus.emit("dispatch", {"prompt": "test event"})
    try:
        hits = await bus.search('event_type:"dispatch" AND *')
        assert isinstance(hits, list)
    except Exception as e:
        pytest.fail(f"search() raised on special chars: {e}")


# ---------------------------------------------------------------------------
# embed_status column tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_emit_creates_pending_row(bus):
    """After emit, the row's embed_status starts as 'pending'."""
    import aiosqlite
    await bus.emit("dispatch", {"prompt": "status test"})
    # Cancel any in-flight embed task to avoid side effects
    for task in list(_pending_embeds):
        task.cancel()
    await asyncio.sleep(0)

    async with aiosqlite.connect(bus._db_path) as db:
        cursor = await db.execute("SELECT embed_status FROM gossip LIMIT 1")
        row = await cursor.fetchone()
    assert row is not None
    assert row[0] in ("pending", "embedded", "failed")


@pytest.mark.asyncio
async def test_embed_failure_marks_row_failed(tmp_path):
    """When Ollama is unreachable, embed_status is set to 'failed'."""
    from unittest.mock import patch
    import aiosqlite

    db_path = str(tmp_path / "fail.db")
    bus = GossipBus(db_path)
    await bus.init_db()

    async def _fail_embed(text: str):
        raise ConnectionError("Ollama unreachable")

    with patch("orchestrator.memory_embed.get_embedding", side_effect=_fail_embed):
        await bus.emit("dispatch", {"prompt": "failing embed row"})
        # Allow the fire-and-forget task to complete
        await asyncio.sleep(0.2)

    async with aiosqlite.connect(db_path) as db:
        cursor = await db.execute("SELECT embed_status FROM gossip LIMIT 1")
        row = await cursor.fetchone()
    assert row[0] == "failed"


# ---------------------------------------------------------------------------
# _pending_embeds GC guard test (Gap 3 / D_GCG-1)
# Real behavioral test — not just isinstance check.
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_pending_embeds_set_prevents_gc(tmp_path):
    """In-flight embed tasks are registered in _pending_embeds during execution
    and auto-discarded when the task completes.

    Gap 3 fix (Antigravity Gemini 3.5 critique, 2026-05-21):
    Previously the test only asserted isinstance(_pending_embeds, set) — a tautology.
    This test patches _embed_and_store to sleep, verifying the set holds the task
    during the active window and drains to 0 after the callback fires.
    """
    from unittest.mock import patch
    import orchestrator.gossip_bus as gossip_mod

    db_path = str(tmp_path / "gc.db")
    bus = GossipBus(db_path)
    await bus.init_db()
    _pending_embeds.clear()

    async def slow_embed(self, row_id, payload):
        await asyncio.sleep(0.1)

    with patch.object(gossip_mod.GossipBus, "_embed_and_store", slow_embed):
        await bus.emit("dispatch", {"prompt": "gc test"})
        assert len(_pending_embeds) == 1, "Task must be registered while in-flight"
        await asyncio.sleep(0.2)
        assert len(_pending_embeds) == 0, "Task must be discarded after done-callback"


# ---------------------------------------------------------------------------
# tail() test
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_tail_returns_recent_events_newest_first(bus):
    await bus.emit("dispatch", {"prompt": "first"})
    await bus.emit("route", {"intent": "second"})
    rows = await bus.tail(limit=5)
    assert len(rows) == 2
    assert rows[0]["event_type"] == "route"   # newest first
    assert rows[1]["event_type"] == "dispatch"


# ---------------------------------------------------------------------------
# resolve_gossip_db_path tests (PR change: new function)
# ---------------------------------------------------------------------------

def test_resolve_gossip_db_path_explicit_env_overrides_all(tmp_path, monkeypatch):
    """GOSSIP_DB_PATH env var takes highest precedence over state_dir and PT_STATE_DIR."""
    from orchestrator.gossip_bus import resolve_gossip_db_path

    explicit = str(tmp_path / "explicit.db")
    monkeypatch.setenv("GOSSIP_DB_PATH", explicit)
    monkeypatch.setenv("PT_STATE_DIR", str(tmp_path / "other"))

    result = resolve_gossip_db_path(state_dir=tmp_path / "also_other")
    assert result == explicit


def test_resolve_gossip_db_path_with_state_dir_arg(tmp_path, monkeypatch):
    """When state_dir is provided and GOSSIP_DB_PATH is unset, path is under state_dir."""
    from orchestrator.gossip_bus import resolve_gossip_db_path

    monkeypatch.delenv("GOSSIP_DB_PATH", raising=False)
    monkeypatch.delenv("PT_STATE_DIR", raising=False)

    result = resolve_gossip_db_path(state_dir=tmp_path)
    assert result == str((tmp_path / "perpetua_core.db").resolve())


def test_resolve_gossip_db_path_uses_pt_state_dir_env(tmp_path, monkeypatch):
    """When state_dir is None, PT_STATE_DIR env var determines the database path."""
    from orchestrator.gossip_bus import resolve_gossip_db_path

    monkeypatch.delenv("GOSSIP_DB_PATH", raising=False)
    monkeypatch.setenv("PT_STATE_DIR", str(tmp_path))

    result = resolve_gossip_db_path()
    assert result == str((tmp_path / "perpetua_core.db").resolve())


def test_resolve_gossip_db_path_defaults_to_dot_state(monkeypatch):
    """When no env vars and no state_dir are set, defaults to .state/perpetua_core.db."""
    from pathlib import Path
    from orchestrator.gossip_bus import resolve_gossip_db_path

    monkeypatch.delenv("GOSSIP_DB_PATH", raising=False)
    monkeypatch.delenv("PT_STATE_DIR", raising=False)

    result = resolve_gossip_db_path()
    expected = str((Path(".state") / "perpetua_core.db").resolve())
    assert result == expected


def test_resolve_gossip_db_path_state_dir_takes_precedence_over_pt_state_dir(tmp_path, monkeypatch):
    """Explicit state_dir arg overrides PT_STATE_DIR env var (but GOSSIP_DB_PATH wins both)."""
    from orchestrator.gossip_bus import resolve_gossip_db_path

    monkeypatch.delenv("GOSSIP_DB_PATH", raising=False)
    env_dir = tmp_path / "from_env"
    arg_dir = tmp_path / "from_arg"
    monkeypatch.setenv("PT_STATE_DIR", str(env_dir))

    result = resolve_gossip_db_path(state_dir=arg_dir)
    assert result == str((arg_dir / "perpetua_core.db").resolve())
    # Verify it does NOT use the env dir
    assert str(env_dir) not in result


def test_resolve_gossip_db_path_db_filename_is_perpetua_core(tmp_path, monkeypatch):
    """The database file is always named perpetua_core.db regardless of input."""
    from orchestrator.gossip_bus import resolve_gossip_db_path

    monkeypatch.delenv("GOSSIP_DB_PATH", raising=False)

    result = resolve_gossip_db_path(state_dir=tmp_path)
    assert result.endswith("perpetua_core.db")


def test_resolve_gossip_db_path_explicit_env_whitespace_stripped(tmp_path, monkeypatch):
    """GOSSIP_DB_PATH with surrounding whitespace is treated as non-empty/empty correctly."""
    from orchestrator.gossip_bus import resolve_gossip_db_path

    monkeypatch.setenv("GOSSIP_DB_PATH", "   ")  # whitespace-only → ignored
    monkeypatch.delenv("PT_STATE_DIR", raising=False)

    result = resolve_gossip_db_path(state_dir=tmp_path)
    # Whitespace-only GOSSIP_DB_PATH is stripped to "" → falls through to state_dir
    assert result == str((tmp_path / "perpetua_core.db").resolve())
