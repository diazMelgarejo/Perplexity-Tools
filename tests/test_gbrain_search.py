"""Tests for orchestrator/gbrain_search.py (Item 5 — RAG v1 backport)."""
from __future__ import annotations

import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from orchestrator.gbrain_search import _normalise_hits, gbrain_search


# ── _normalise_hits ────────────────────────────────────────────────────────────

def test_normalise_hits_content_key():
    raw = [{"content": "hello world", "score": 0.9}]
    out = _normalise_hits(raw, limit=5)
    assert len(out) == 1
    assert out[0]["text"] == "hello world"


def test_normalise_hits_text_key():
    raw = [{"text": "foo bar"}]
    out = _normalise_hits(raw, limit=5)
    assert out[0]["text"] == "foo bar"


def test_normalise_hits_title_fallback():
    raw = [{"title": "my title"}]
    out = _normalise_hits(raw, limit=5)
    assert out[0]["text"] == "my title"


def test_normalise_hits_skips_empty_text():
    raw = [{"content": ""}, {"content": "good"}]
    out = _normalise_hits(raw, limit=5)
    assert len(out) == 1
    assert out[0]["text"] == "good"


def test_normalise_hits_skips_non_dict():
    raw = ["string item", {"text": "ok"}]
    out = _normalise_hits(raw, limit=5)
    assert len(out) == 1
    assert out[0]["text"] == "ok"


def test_normalise_hits_respects_limit():
    raw = [{"text": f"item {i}"} for i in range(10)]
    out = _normalise_hits(raw, limit=3)
    assert len(out) == 3


# ── gbrain_search ──────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_gbrain_search_returns_empty_when_binary_missing():
    with patch("orchestrator.gbrain_search._gbrain_binary", return_value=None):
        result = await gbrain_search("any query")
    assert result == []


@pytest.mark.asyncio
async def test_gbrain_search_returns_empty_for_blank_query():
    result = await gbrain_search("   ")
    assert result == []


@pytest.mark.asyncio
async def test_gbrain_search_returns_empty_for_empty_query():
    result = await gbrain_search("")
    assert result == []


@pytest.mark.asyncio
async def test_gbrain_search_parses_list_response():
    payload = json.dumps([{"text": "result A"}, {"text": "result B"}]).encode()

    mock_proc = MagicMock()
    mock_proc.returncode = 0
    mock_proc.communicate = AsyncMock(return_value=(payload, b""))

    with (
        patch("orchestrator.gbrain_search._gbrain_binary", return_value="/usr/local/bin/gbrain"),
        patch("asyncio.create_subprocess_exec", return_value=mock_proc),
    ):
        result = await gbrain_search("test query")

    assert len(result) == 2
    assert result[0]["text"] == "result A"


@pytest.mark.asyncio
async def test_gbrain_search_parses_results_dict_response():
    payload = json.dumps({"results": [{"content": "context snippet"}]}).encode()

    mock_proc = MagicMock()
    mock_proc.returncode = 0
    mock_proc.communicate = AsyncMock(return_value=(payload, b""))

    with (
        patch("orchestrator.gbrain_search._gbrain_binary", return_value="/usr/local/bin/gbrain"),
        patch("asyncio.create_subprocess_exec", return_value=mock_proc),
    ):
        result = await gbrain_search("context query")

    assert len(result) == 1
    assert result[0]["text"] == "context snippet"


@pytest.mark.asyncio
async def test_gbrain_search_returns_empty_on_nonzero_exit():
    mock_proc = MagicMock()
    mock_proc.returncode = 1
    mock_proc.communicate = AsyncMock(return_value=(b"", b"error"))

    with (
        patch("orchestrator.gbrain_search._gbrain_binary", return_value="/usr/bin/gbrain"),
        patch("asyncio.create_subprocess_exec", return_value=mock_proc),
    ):
        result = await gbrain_search("query")

    assert result == []


@pytest.mark.asyncio
async def test_gbrain_search_returns_empty_on_bad_json():
    mock_proc = MagicMock()
    mock_proc.returncode = 0
    mock_proc.communicate = AsyncMock(return_value=(b"not valid json", b""))

    with (
        patch("orchestrator.gbrain_search._gbrain_binary", return_value="/usr/bin/gbrain"),
        patch("asyncio.create_subprocess_exec", return_value=mock_proc),
    ):
        result = await gbrain_search("query")

    assert result == []


@pytest.mark.asyncio
async def test_gbrain_search_returns_empty_on_timeout():
    mock_proc = MagicMock()
    mock_proc.kill = MagicMock()
    mock_proc.communicate = AsyncMock(return_value=(b"", b""))

    async def _timeout_communicate():
        raise asyncio.TimeoutError

    mock_proc.communicate = _timeout_communicate

    with (
        patch("orchestrator.gbrain_search._gbrain_binary", return_value="/usr/bin/gbrain"),
        patch("asyncio.create_subprocess_exec", return_value=mock_proc),
        patch("asyncio.wait_for", side_effect=asyncio.TimeoutError),
    ):
        result = await gbrain_search("query", timeout=0.001)

    assert result == []
