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


# ---------------------------------------------------------------------------
# _AlwaysRaisesOnPop helper class — self-documenting invariants
# ---------------------------------------------------------------------------


def test_always_raises_on_pop_is_truthy_when_nonempty():
    """_AlwaysRaisesOnPop is truthy when it contains items (prerequisite for testing the IndexError guard)."""
    faulty = _AlwaysRaisesOnPop(maxlen=50)
    faulty.appendleft({"message": "item"})
    assert bool(faulty) is True


def test_always_raises_on_pop_raises_index_error_on_pop():
    """_AlwaysRaisesOnPop.pop() always raises IndexError regardless of content."""
    faulty = _AlwaysRaisesOnPop(maxlen=50)
    faulty.appendleft({"message": "item"})
    with pytest.raises(IndexError, match="simulated concurrent drain"):
        faulty.pop()


def test_always_raises_on_pop_appendleft_does_not_raise():
    """_AlwaysRaisesOnPop.appendleft() works normally — only pop() is overridden."""
    faulty = _AlwaysRaisesOnPop(maxlen=50)
    faulty.appendleft({"message": "a"})
    faulty.appendleft({"message": "b"})
    assert len(faulty) == 2


# ---------------------------------------------------------------------------
# IndexError path — HTTP layer returns 200, not 500
# ---------------------------------------------------------------------------


def test_get_user_input_next_indexerror_via_http_returns_200_not_500(monkeypatch):
    """When IndexError fires on pop(), the HTTP endpoint returns 200 — not 500."""
    monkeypatch.setenv("ORAMA_INSECURE_DEV", "1")
    faulty = _AlwaysRaisesOnPop(maxlen=50)
    faulty.appendleft({"message": "ghost", "source": "portal", "ts": 1.0})
    monkeypatch.setattr(_fapp, "_USER_INPUT_QUEUE", faulty)

    with TestClient(app, raise_server_exceptions=False) as client:
        resp = client.get("/user-input/next")

    assert resp.status_code == 200


def test_get_user_input_next_indexerror_via_http_body_has_null_message(monkeypatch):
    """HTTP response body has {message: null} when IndexError fires on pop()."""
    monkeypatch.setenv("ORAMA_INSECURE_DEV", "1")
    faulty = _AlwaysRaisesOnPop(maxlen=50)
    faulty.appendleft({"message": "ghost"})
    monkeypatch.setattr(_fapp, "_USER_INPUT_QUEUE", faulty)

    with TestClient(app, raise_server_exceptions=False) as client:
        body = client.get("/user-input/next").json()

    assert body["message"] is None


# ---------------------------------------------------------------------------
# Mutation safety — returned dict is independent of queue internals
# ---------------------------------------------------------------------------


def test_get_user_input_next_returned_dict_is_a_copy_not_the_queue_entry(monkeypatch):
    """Mutating the returned dict does not affect the remaining queue contents."""
    queue = collections.deque(maxlen=50)
    queue.appendleft({"message": "first", "source": "cli", "ts": 1.0})
    queue.appendleft({"message": "second", "source": "portal", "ts": 2.0})
    monkeypatch.setattr(_fapp, "_USER_INPUT_QUEUE", queue)

    result = _fapp.get_user_input_next()
    # Mutate the returned dict
    result["message"] = "mutated"
    result["source"] = "mutated"

    # The next pop should still return the original second entry untouched
    next_result = _fapp.get_user_input_next()
    assert next_result["message"] == "second"
    assert next_result["source"] == "portal"


# ---------------------------------------------------------------------------
# Concurrent — eight-thread stress test (one message, seven nulls)
# ---------------------------------------------------------------------------


def test_get_user_input_next_concurrent_eight_threads_single_message_no_crash(monkeypatch):
    """Eight simultaneous pollers on one message: exactly one wins, seven get null, no exception."""
    queue = collections.deque(maxlen=50)
    queue.appendleft({"message": "singleton", "source": "cli", "ts": 9.9})
    monkeypatch.setattr(_fapp, "_USER_INPUT_QUEUE", queue)

    n_threads = 8
    results: list[dict | BaseException] = [None] * n_threads  # type: ignore[misc]

    def _poll(slot: int) -> None:
        try:
            results[slot] = _fapp.get_user_input_next()
        except BaseException as exc:  # noqa: BLE001
            results[slot] = exc

    threads = [threading.Thread(target=_poll, args=(i,)) for i in range(n_threads)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=5)

    assert all(not isinstance(r, BaseException) for r in results), (
        f"unexpected exception: {[r for r in results if isinstance(r, BaseException)]}"
    )
    messages = [r["message"] for r in results]  # type: ignore[index]
    assert messages.count("singleton") == 1
    assert messages.count(None) == n_threads - 1


# ---------------------------------------------------------------------------
# Queue depth — successful pop shrinks queue by exactly one
# ---------------------------------------------------------------------------


def test_get_user_input_next_queue_depth_decreases_by_one_after_pop(monkeypatch):
    """After a successful pop, the queue contains one fewer item."""
    queue = collections.deque(maxlen=50)
    queue.appendleft({"message": "a", "source": "cli", "ts": 1.0})
    queue.appendleft({"message": "b", "source": "portal", "ts": 2.0})
    monkeypatch.setattr(_fapp, "_USER_INPUT_QUEUE", queue)

    assert len(queue) == 2
    _fapp.get_user_input_next()
    assert len(queue) == 1
    _fapp.get_user_input_next()
    assert len(queue) == 0


# ---------------------------------------------------------------------------
# IndexError response shape — consistent regardless of how full the queue was
# ---------------------------------------------------------------------------


def test_get_user_input_next_indexerror_shape_is_stable_for_multiple_queue_sizes(monkeypatch):
    """IndexError path always returns {message: None} whether the queue had 1 or 10 items."""
    for n_items in (1, 5, 10):
        faulty = _AlwaysRaisesOnPop(maxlen=50)
        for i in range(n_items):
            faulty.appendleft({"message": f"item-{i}"})
        monkeypatch.setattr(_fapp, "_USER_INPUT_QUEUE", faulty)

        result = _fapp.get_user_input_next()
        assert result == {"message": None}, f"failed for n_items={n_items}"
        assert set(result.keys()) == {"message"}, f"extra keys for n_items={n_items}"


# ---------------------------------------------------------------------------
# Concurrent — zero messages, all pollers get null, no crash
# ---------------------------------------------------------------------------


def test_get_user_input_next_concurrent_empty_queue_all_get_null(monkeypatch):
    """Four concurrent pollers on an empty queue all receive null — no exception."""
    monkeypatch.setattr(_fapp, "_USER_INPUT_QUEUE", collections.deque(maxlen=50))

    n_threads = 4
    results: list[dict | BaseException] = [None] * n_threads  # type: ignore[misc]

    def _poll(slot: int) -> None:
        try:
            results[slot] = _fapp.get_user_input_next()
        except BaseException as exc:  # noqa: BLE001
            results[slot] = exc

    threads = [threading.Thread(target=_poll, args=(i,)) for i in range(n_threads)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=5)

    assert all(not isinstance(r, BaseException) for r in results)
    assert all(r == {"message": None} for r in results)  # type: ignore[index]


# ---------------------------------------------------------------------------
# Boundary — message at maximum allowed length
# ---------------------------------------------------------------------------


def test_get_user_input_next_preserves_long_message_intact(monkeypatch):
    """A message at the maximum allowed field length (4000 chars) is returned unmodified."""
    long_msg = "x" * 4000
    queue = collections.deque(maxlen=50)
    queue.appendleft({"message": long_msg, "source": "cli", "ts": 0.0})
    monkeypatch.setattr(_fapp, "_USER_INPUT_QUEUE", queue)

    result = _fapp.get_user_input_next()

    assert result["message"] == long_msg
    assert len(result["message"]) == 4000
