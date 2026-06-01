#!/usr/bin/env python3
"""User-input queue behaviour (portal / researcher polling)."""
from __future__ import annotations

import collections
import importlib.util
import threading
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
# get_user_input_next — harmonized empty-queue + concurrent-poll guards
#
# Production code keeps BOTH:
#   • ``if not _USER_INPUT_QUEUE`` (fast empty path, legacy response shape)
#   • ``try/except IndexError`` on pop (concurrent pollers after the check)
# Tests below document each layer; they do not require removing either guard.
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


# ---------------------------------------------------------------------------
# Concurrent polls — IndexError guard (additive to the if-not-queue guard above)
# ---------------------------------------------------------------------------


def test_user_input_next_concurrent_pop_never_raises(monkeypatch):
    """Four simultaneous pollers on one message: one wins, three get null — no 500."""
    monkeypatch.setenv("ORAMA_INSECURE_DEV", "1")
    queue = collections.deque(maxlen=50)
    queue.appendleft({"message": "only-one", "source": "portal", "ts": 1.0})
    monkeypatch.setattr(_fapp, "_USER_INPUT_QUEUE", queue)

    results: list[dict | BaseException] = [None] * 4  # type: ignore[misc]

    def _poll(slot: int) -> None:
        try:
            results[slot] = _fapp.get_user_input_next()
        except BaseException as exc:  # noqa: BLE001 — test must record crashes
            results[slot] = exc

    threads = [threading.Thread(target=_poll, args=(i,)) for i in range(4)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=5)

    assert all(not isinstance(r, BaseException) for r in results)
    messages = [r["message"] for r in results]  # type: ignore[index]
    assert messages.count("only-one") == 1
    assert messages.count(None) == 3


# ---------------------------------------------------------------------------
# IndexError fallback — deterministic path (additive to concurrent test above)
#
# The concurrent test exercises the race non-deterministically.  These tests
# use a subclass whose pop() always raises IndexError so the except branch is
# exercised on every run — independent of thread scheduling.
# ---------------------------------------------------------------------------


class _AlwaysRaisesOnPop(collections.deque):
    """Deque that is truthy (has items) but always raises on pop()."""

    def pop(self):
        raise IndexError("simulated concurrent drain")


def test_get_user_input_next_indexerror_on_pop_returns_null_message(monkeypatch):
    """When pop() raises IndexError (race: queue drained between check and pop), return {message: None}."""
    faulty = _AlwaysRaisesOnPop(maxlen=50)
    faulty.appendleft({"message": "ghost", "source": "portal", "ts": 1.0})
    monkeypatch.setattr(_fapp, "_USER_INPUT_QUEUE", faulty)

    result = _fapp.get_user_input_next()

    assert result == {"message": None}


def test_get_user_input_next_indexerror_on_pop_response_has_only_message_key(monkeypatch):
    """IndexError fallback response has exactly one key ('message') — no source/ts leakage."""
    faulty = _AlwaysRaisesOnPop(maxlen=50)
    faulty.appendleft({"message": "ghost"})
    monkeypatch.setattr(_fapp, "_USER_INPUT_QUEUE", faulty)

    result = _fapp.get_user_input_next()

    assert set(result.keys()) == {"message"}
    assert result["message"] is None


# ---------------------------------------------------------------------------
# Response shape — positive path key verification
# ---------------------------------------------------------------------------


def test_get_user_input_next_response_keys_when_message_present(monkeypatch):
    """Successful pop returns dict with exactly {message, source, ts} keys."""
    queue = collections.deque(maxlen=50)
    queue.appendleft({"message": "task-abc", "source": "cli", "ts": 42.0})
    monkeypatch.setattr(_fapp, "_USER_INPUT_QUEUE", queue)

    result = _fapp.get_user_input_next()

    assert set(result.keys()) == {"message", "source", "ts"}
    assert result["message"] == "task-abc"
    assert result["source"] == "cli"
    assert result["ts"] == 42.0


# ---------------------------------------------------------------------------
# Fast path — if not _USER_INPUT_QUEUE: skips pop entirely
# ---------------------------------------------------------------------------


def test_get_user_input_next_fast_path_skips_pop_on_empty_queue(monkeypatch):
    """With an empty queue the fast-path guard fires before pop() is ever called."""
    pop_call_count = []

    class _InstrumentedDeque(collections.deque):
        def pop(self):
            pop_call_count.append(1)
            return super().pop()

    empty_queue = _InstrumentedDeque(maxlen=50)
    monkeypatch.setattr(_fapp, "_USER_INPUT_QUEUE", empty_queue)

    result = _fapp.get_user_input_next()

    assert result == {"message": None}
    assert pop_call_count == [], "pop() must not be called when the fast-path guard fires"


# ---------------------------------------------------------------------------
# Repeated empty-queue calls — regression guard for consistent shape
# ---------------------------------------------------------------------------


def test_get_user_input_next_repeated_empty_calls_all_return_consistent_shape(monkeypatch):
    """Ten successive calls on an empty queue all return the exact same {message: None} shape."""
    monkeypatch.setattr(_fapp, "_USER_INPUT_QUEUE", collections.deque(maxlen=50))

    for _ in range(10):
        result = _fapp.get_user_input_next()
        assert result == {"message": None}
        assert set(result.keys()) == {"message"}


# ---------------------------------------------------------------------------
# Concurrent — multiple messages consumed exactly once each
# ---------------------------------------------------------------------------


def test_get_user_input_next_concurrent_two_messages_each_consumed_once(monkeypatch):
    """With two messages and four concurrent pollers each message is returned exactly once."""
    queue = collections.deque(maxlen=50)
    queue.appendleft({"message": "msg-alpha", "source": "portal", "ts": 1.0})
    queue.appendleft({"message": "msg-beta", "source": "cli", "ts": 2.0})
    monkeypatch.setattr(_fapp, "_USER_INPUT_QUEUE", queue)

    results: list[dict | BaseException] = [None] * 4  # type: ignore[misc]

    def _poll(slot: int) -> None:
        try:
            results[slot] = _fapp.get_user_input_next()
        except BaseException as exc:  # noqa: BLE001
            results[slot] = exc

    threads = [threading.Thread(target=_poll, args=(i,)) for i in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=5)

    assert all(not isinstance(r, BaseException) for r in results), (
        f"unexpected exception: {[r for r in results if isinstance(r, BaseException)]}"
    )
    messages = [r["message"] for r in results]  # type: ignore[index]
    assert messages.count("msg-alpha") == 1
    assert messages.count("msg-beta") == 1
    assert messages.count(None) == 2
