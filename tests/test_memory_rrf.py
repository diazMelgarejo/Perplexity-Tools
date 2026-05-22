"""tests/test_memory_rrf.py

Unit tests for orchestrator/memory_rrf.py — Reciprocal Rank Fusion.
Zero dependencies (pure function).
"""
from orchestrator.memory_rrf import rrf_merge


def test_rrf_fts_only_when_no_vec():
    """If vec_hits is empty, return fts_hits unchanged (up to top_n)."""
    fts = [{"row_id": 1}, {"row_id": 2}]
    result = rrf_merge(fts, [])
    assert result == fts


def test_rrf_merges_and_deduplicates():
    """Same row_id in both lists appears once in output."""
    fts = [{"row_id": 1, "text": "a"}, {"row_id": 2, "text": "b"}]
    vec = [{"row_id": 2, "text": "b"}, {"row_id": 3, "text": "c"}]
    result = rrf_merge(fts, vec)
    row_ids = [r["row_id"] for r in result]
    assert len(row_ids) == len(set(row_ids)), "Duplicates found in RRF output"
    assert set(row_ids) == {1, 2, 3}


def test_rrf_top_ranked_item_appears_first():
    """Item ranked #1 in both lists gets the highest RRF score."""
    fts = [{"row_id": 10}, {"row_id": 20}]
    vec = [{"row_id": 10}, {"row_id": 30}]
    result = rrf_merge(fts, vec)
    assert result[0]["row_id"] == 10, "Item #1 in both lists must win"


def test_rrf_respects_top_n():
    """Result length is capped at top_n."""
    fts = [{"row_id": i} for i in range(20)]
    vec = [{"row_id": i + 5} for i in range(20)]
    result = rrf_merge(fts, vec, top_n=3)
    assert len(result) <= 3


def test_rrf_both_empty_returns_empty():
    assert rrf_merge([], []) == []


def test_rrf_vec_only_when_fts_empty():
    """If fts_hits empty but vec_hits present, vec_hits are returned."""
    vec = [{"row_id": 7}, {"row_id": 8}]
    result = rrf_merge([], vec)
    row_ids = {r["row_id"] for r in result}
    assert {7, 8}.issubset(row_ids)
