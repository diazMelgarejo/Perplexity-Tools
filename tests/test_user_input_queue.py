#!/usr/bin/env python3
"""User-input queue behaviour (portal / researcher polling)."""
from __future__ import annotations

import collections
import importlib.util
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import orchestrator.fastapi_app as _fapp
from orchestrator.fastapi_app import app

_LAUNCH_RESEARCHERS = Path(__file__).resolve().parents[1] / "scripts" / "launch_researchers.py"
_spec = importlib.util.spec_from_file_location("launch_researchers", _LAUNCH_RESEARCHERS)
_launch = importlib.util.module_from_spec(_spec)
assert _spec.loader is not None
_spec.loader.exec_module(_launch)
_extract = _launch._extract_user_input_message


def test_extract_user_input_message_flat_string():
    assert _extract("  run tests  ") == "run tests"


def test_extract_user_input_message_legacy_nested_entry():
    legacy = {"message": "steal-me", "source": "portal", "ts": 1.0}
    assert _extract(legacy) == "steal-me"


def test_user_input_next_returns_task_string_not_nested_entry(monkeypatch):
    monkeypatch.setenv("ORAMA_INSECURE_DEV", "1")
    # Isolate from state leaked by prior tests: _USER_INPUT_QUEUE is module-level.
    # test_user_input_requires_token_when_enforced queues "hello" (auth test) and
    # never drains it. appendleft/pop FIFO means "hello" gets popped before
    # "portal-task". monkeypatch auto-restores after the test.
    monkeypatch.setattr(_fapp, "_USER_INPUT_QUEUE", collections.deque(maxlen=50))

    with TestClient(app, raise_server_exceptions=False) as client:
        client.post("/user-input", json={"message": "portal-task", "source": "portal"})
        popped = client.get("/user-input/next")
        empty = client.get("/user-input/next")

    assert popped.status_code == 200
    body = popped.json()
    assert body["message"] == "portal-task"
    assert body["source"] == "portal"
    assert isinstance(body["ts"], (int, float))
    assert empty.json()["message"] is None


# ---------------------------------------------------------------------------
# get_user_input_next — if/else guard (PR: replace try/except IndexError)
# ---------------------------------------------------------------------------


def test_get_user_input_next_empty_queue_returns_null_message(monkeypatch):
    """Empty queue returns {"message": None} without raising any exception."""
    monkeypatch.setattr(_fapp, "_USER_INPUT_QUEUE", collections.deque(maxlen=50))
    result = _fapp.get_user_input_next()
    assert result == {"message": None}


def test_get_user_input_next_empty_queue_response_has_only_message_key(monkeypatch):
    """Empty-queue response contains exactly the 'message' key — no source/ts leakage."""
    monkeypatch.setattr(_fapp, "_USER_INPUT_QUEUE", collections.deque(maxlen=50))
    result = _fapp.get_user_input_next()
    assert set(result.keys()) == {"message"}


def test_get_user_input_next_entry_without_source_returns_none_source(monkeypatch):
    """Entry missing 'source' key returns source=None via dict.get() fallback."""
    queue = collections.deque(maxlen=50)
    queue.appendleft({"message": "task-no-source", "ts": 99.0})
    monkeypatch.setattr(_fapp, "_USER_INPUT_QUEUE", queue)
    result = _fapp.get_user_input_next()
    assert result["message"] == "task-no-source"
    assert result["source"] is None
    assert result["ts"] == 99.0


def test_get_user_input_next_entry_without_ts_returns_none_ts(monkeypatch):
    """Entry missing 'ts' key returns ts=None via dict.get() fallback."""
    queue = collections.deque(maxlen=50)
    queue.appendleft({"message": "task-no-ts", "source": "cli"})
    monkeypatch.setattr(_fapp, "_USER_INPUT_QUEUE", queue)
    result = _fapp.get_user_input_next()
    assert result["message"] == "task-no-ts"
    assert result["source"] == "cli"
    assert result["ts"] is None


def test_get_user_input_next_multiple_items_pops_fifo_order(monkeypatch):
    """With two items queued, the first enqueued message is returned first (FIFO)."""
    queue = collections.deque(maxlen=50)
    # appendleft mimics post_user_input; deque.pop() removes from right,
    # so first appendleft ends up on the right and is popped first.
    queue.appendleft({"message": "first", "source": "portal", "ts": 1.0})
    queue.appendleft({"message": "second", "source": "portal", "ts": 2.0})
    monkeypatch.setattr(_fapp, "_USER_INPUT_QUEUE", queue)

    first_result = _fapp.get_user_input_next()
    second_result = _fapp.get_user_input_next()
    empty_result = _fapp.get_user_input_next()

    assert first_result["message"] == "first"
    assert second_result["message"] == "second"
    assert empty_result == {"message": None}


def test_get_user_input_next_drains_to_empty(monkeypatch):
    """After popping the last item, the queue is empty and subsequent calls return null."""
    queue = collections.deque(maxlen=50)
    queue.appendleft({"message": "only-one", "source": "cli", "ts": 5.0})
    monkeypatch.setattr(_fapp, "_USER_INPUT_QUEUE", queue)

    _fapp.get_user_input_next()  # consume the item

    # Queue must be falsy now; all further pops return null
    for _ in range(3):
        assert _fapp.get_user_input_next() == {"message": None}


def test_get_user_input_next_via_http_empty_queue_shape(monkeypatch):
    """HTTP /user-input/next on an empty queue returns JSON {message: null} with status 200."""
    monkeypatch.setenv("ORAMA_INSECURE_DEV", "1")
    monkeypatch.setattr(_fapp, "_USER_INPUT_QUEUE", collections.deque(maxlen=50))

    with TestClient(app, raise_server_exceptions=False) as client:
        resp = client.get("/user-input/next")

    assert resp.status_code == 200
    body = resp.json()
    assert body["message"] is None
    # source and ts are not present in the empty-queue response
    assert "source" not in body
    assert "ts" not in body


def test_get_user_input_next_entry_all_optional_fields_missing(monkeypatch):
    """Entry with only 'message' key returns source=None and ts=None — no KeyError."""
    queue = collections.deque(maxlen=50)
    queue.appendleft({"message": "bare"})
    monkeypatch.setattr(_fapp, "_USER_INPUT_QUEUE", queue)
    result = _fapp.get_user_input_next()
    assert result["message"] == "bare"
    assert result["source"] is None
    assert result["ts"] is None
