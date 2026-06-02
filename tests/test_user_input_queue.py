#!/usr/bin/env python3
"""User-input queue behaviour (portal / researcher polling)."""
from __future__ import annotations

import collections
import importlib.util
import threading
from collections.abc import Callable
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import orchestrator.fastapi_app as _fapp
from orchestrator.fastapi_app import app

_POLL_JOIN_TIMEOUT_S = 5.0


def _run_barrier_pollers(
    count: int,
    poll: Callable[[int], None],
    *,
    join_timeout_s: float = _POLL_JOIN_TIMEOUT_S,
) -> None:
    """Run ``count`` pollers concurrently after a threading.Barrier start gate."""
    start_gate = threading.Barrier(count)
    completed = [False] * count

    def _worker(slot: int) -> None:
        try:
            start_gate.wait()
            poll(slot)
        finally:
            completed[slot] = True

    threads = [threading.Thread(target=_worker, args=(i,)) for i in range(count)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=join_timeout_s)
        assert not thread.is_alive(), (
            f"poller thread did not finish within {join_timeout_s}s"
        )
    assert all(completed), "one or more pollers did not run to completion"


_LAUNCH_RESEARCHERS = Path(__file__).resolve().parents[1] / "scripts" / "launch_researchers.py"
_spec = importlib.util.spec_from_file_location("launch_researchers", _LAUNCH_RESEARCHERS)
_launch = importlib.util.module_from_spec(_spec)
assert _spec.loader is not None
_spec.loader.exec_module(_launch)
_extract = _launch._extract_user_input_message


def test_parse_crash_recovery_secs_boolean_true(monkeypatch):
    monkeypatch.setenv("RESEARCHER_CRASH_RECOVERY", "true")
    assert _launch._parse_crash_recovery_secs() == 30


def test_parse_crash_recovery_secs_numeric(monkeypatch):
    monkeypatch.setenv("RESEARCHER_CRASH_RECOVERY", "45")
    assert _launch._parse_crash_recovery_secs() == 45


# ---------------------------------------------------------------------------
# _parse_crash_recovery_secs — edge cases for the new env-var parser
# ---------------------------------------------------------------------------


def test_parse_crash_recovery_secs_false_disables(monkeypatch):
    """'false' disables crash recovery (returns 0)."""
    monkeypatch.setenv("RESEARCHER_CRASH_RECOVERY", "false")
    assert _launch._parse_crash_recovery_secs() == 0


def test_parse_crash_recovery_secs_zero_disables(monkeypatch):
    """'0' disables crash recovery (returns 0)."""
    monkeypatch.setenv("RESEARCHER_CRASH_RECOVERY", "0")
    assert _launch._parse_crash_recovery_secs() == 0


def test_parse_crash_recovery_secs_off_disables(monkeypatch):
    """'off' disables crash recovery (returns 0)."""
    monkeypatch.setenv("RESEARCHER_CRASH_RECOVERY", "off")
    assert _launch._parse_crash_recovery_secs() == 0


def test_parse_crash_recovery_secs_disable_keyword(monkeypatch):
    """'disable' disables crash recovery (returns 0)."""
    monkeypatch.setenv("RESEARCHER_CRASH_RECOVERY", "disable")
    assert _launch._parse_crash_recovery_secs() == 0


def test_parse_crash_recovery_secs_disabled_keyword(monkeypatch):
    """'disabled' disables crash recovery (returns 0)."""
    monkeypatch.setenv("RESEARCHER_CRASH_RECOVERY", "disabled")
    assert _launch._parse_crash_recovery_secs() == 0


def test_parse_crash_recovery_secs_no_disables(monkeypatch):
    """'no' disables crash recovery (returns 0)."""
    monkeypatch.setenv("RESEARCHER_CRASH_RECOVERY", "no")
    assert _launch._parse_crash_recovery_secs() == 0


def test_parse_crash_recovery_secs_enable_keyword(monkeypatch):
    """'enable' returns default 30."""
    monkeypatch.setenv("RESEARCHER_CRASH_RECOVERY", "enable")
    assert _launch._parse_crash_recovery_secs() == 30


def test_parse_crash_recovery_secs_enabled_keyword(monkeypatch):
    """'enabled' returns default 30."""
    monkeypatch.setenv("RESEARCHER_CRASH_RECOVERY", "enabled")
    assert _launch._parse_crash_recovery_secs() == 30


def test_parse_crash_recovery_secs_yes_returns_default(monkeypatch):
    """'yes' returns default 30."""
    monkeypatch.setenv("RESEARCHER_CRASH_RECOVERY", "yes")
    assert _launch._parse_crash_recovery_secs() == 30


def test_parse_crash_recovery_secs_on_returns_default(monkeypatch):
    """'on' returns default 30."""
    monkeypatch.setenv("RESEARCHER_CRASH_RECOVERY", "on")
    assert _launch._parse_crash_recovery_secs() == 30


def test_parse_crash_recovery_secs_one_returns_default(monkeypatch):
    """'1' returns default 30 (boolean-enable alias)."""
    monkeypatch.setenv("RESEARCHER_CRASH_RECOVERY", "1")
    assert _launch._parse_crash_recovery_secs() == 30


def test_parse_crash_recovery_secs_numeric_zero_disables(monkeypatch):
    """Numeric zero string disables crash recovery."""
    monkeypatch.setenv("RESEARCHER_CRASH_RECOVERY", "0")
    assert _launch._parse_crash_recovery_secs() == 0


def test_parse_crash_recovery_secs_large_number(monkeypatch):
    """Large numeric value is accepted and returned directly."""
    monkeypatch.setenv("RESEARCHER_CRASH_RECOVERY", "3600")
    assert _launch._parse_crash_recovery_secs() == 3600


def test_parse_crash_recovery_secs_invalid_string_defaults_to_30(monkeypatch):
    """An invalid string (not numeric, not a known keyword) defaults to 30."""
    monkeypatch.setenv("RESEARCHER_CRASH_RECOVERY", "totally-invalid")
    assert _launch._parse_crash_recovery_secs() == 30


def test_parse_crash_recovery_secs_empty_string_defaults_to_30(monkeypatch):
    """Empty string defaults to 30."""
    monkeypatch.setenv("RESEARCHER_CRASH_RECOVERY", "")
    assert _launch._parse_crash_recovery_secs() == 30


def test_parse_crash_recovery_secs_negative_number_clamps_to_zero(monkeypatch):
    """Negative numeric value is clamped to 0 via max(0, int(raw))."""
    monkeypatch.setenv("RESEARCHER_CRASH_RECOVERY", "-10")
    assert _launch._parse_crash_recovery_secs() == 0


def test_parse_crash_recovery_secs_whitespace_around_value(monkeypatch):
    """Leading/trailing whitespace is stripped before parsing."""
    monkeypatch.setenv("RESEARCHER_CRASH_RECOVERY", "  60  ")
    assert _launch._parse_crash_recovery_secs() == 60


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
#
# Tests in this module are additive layers (do not replace one another):
#   • CodeRabbit #85 — empty-queue shape, optional fields, FIFO, HTTP contract
#   • harmonize — concurrent poll regression
#   • CodeRabbit docstrings PR — fast-path vs IndexError path, response-shape contract
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

    _run_barrier_pollers(4, _poll)

    assert all(not isinstance(r, BaseException) for r in results)
    messages = [r["message"] for r in results]  # type: ignore[index]
    assert messages.count("only-one") == 1
    assert messages.count(None) == 3


# ---------------------------------------------------------------------------
# Response shape contract — full entry must expose exactly {message, source, ts}
# ---------------------------------------------------------------------------


def test_get_user_input_next_full_entry_has_exactly_three_keys(monkeypatch):
    """Successful pop returns exactly the keys: message, source, ts — no extras."""
    queue = collections.deque(maxlen=50)
    queue.appendleft({"message": "shaped", "source": "cli", "ts": 42.0})
    monkeypatch.setattr(_fapp, "_USER_INPUT_QUEUE", queue)
    result = _fapp.get_user_input_next()
    assert set(result.keys()) == {"message", "source", "ts"}


def test_get_user_input_next_preserves_exact_values(monkeypatch):
    """source and ts values pass through without mutation."""
    queue = collections.deque(maxlen=50)
    queue.appendleft({"message": "exact", "source": "portal", "ts": 1_700_000_000.5})
    monkeypatch.setattr(_fapp, "_USER_INPUT_QUEUE", queue)
    result = _fapp.get_user_input_next()
    assert result["message"] == "exact"
    assert result["source"] == "portal"
    assert result["ts"] == pytest.approx(1_700_000_000.5)


# ---------------------------------------------------------------------------
# Fast-path guard: ``if not _USER_INPUT_QUEUE`` fires before pop is attempted
# ---------------------------------------------------------------------------


def test_get_user_input_next_empty_deque_is_falsy():
    """Sanity: an empty collections.deque() is falsy — the fast-path guard relies on this."""
    assert not collections.deque()
    assert not collections.deque(maxlen=50)


def test_get_user_input_next_non_empty_deque_is_truthy():
    """Non-empty deque is truthy — fast-path guard must NOT short-circuit when items exist."""
    q = collections.deque(maxlen=50)
    q.appendleft({"message": "x"})
    assert q  # truthy → guard does not fire → pop proceeds


def test_get_user_input_next_fast_path_bypasses_pop_on_empty(monkeypatch):
    """Empty queue returns null via the if-not guard, never reaching pop()."""

    class _PoppingForbidden(collections.deque):
        def pop(self):
            raise AssertionError("pop() must not be called on an empty queue")

    monkeypatch.setattr(_fapp, "_USER_INPUT_QUEUE", _PoppingForbidden(maxlen=50))
    result = _fapp.get_user_input_next()
    assert result == {"message": None}


# ---------------------------------------------------------------------------
# IndexError fallback path — race after the emptiness check
# ---------------------------------------------------------------------------


def test_get_user_input_next_indexerror_on_pop_returns_null_not_500(monkeypatch):
    """If pop() raises IndexError after the emptiness check passes, return null — no crash."""

    class _AlwaysNonEmptyButPopFails(collections.deque):
        def __bool__(self):
            return True  # trick the ``if not`` guard into passing

        def pop(self):
            raise IndexError("simulated concurrent drain")

    monkeypatch.setattr(_fapp, "_USER_INPUT_QUEUE", _AlwaysNonEmptyButPopFails(maxlen=50))
    result = _fapp.get_user_input_next()
    assert result == {"message": None}


def test_get_user_input_next_indexerror_path_response_shape(monkeypatch):
    """IndexError fallback also returns exactly {message: None} — same contract as empty."""

    class _FakeTruthyEmptyDeque(collections.deque):
        def __bool__(self):
            return True

        def pop(self):
            raise IndexError

    monkeypatch.setattr(_fapp, "_USER_INPUT_QUEUE", _FakeTruthyEmptyDeque(maxlen=50))
    result = _fapp.get_user_input_next()
    assert set(result.keys()) == {"message"}
    assert result["message"] is None


# ---------------------------------------------------------------------------
# Concurrent polls — more threads than messages
# ---------------------------------------------------------------------------


def test_user_input_next_concurrent_eight_threads_two_messages(monkeypatch):
    """8 threads compete for 2 messages: exactly 2 win, 6 get null — no exceptions."""
    queue = collections.deque(maxlen=50)
    queue.appendleft({"message": "msg-a", "source": "portal", "ts": 1.0})
    queue.appendleft({"message": "msg-b", "source": "cli", "ts": 2.0})
    monkeypatch.setattr(_fapp, "_USER_INPUT_QUEUE", queue)

    results: list[dict | BaseException] = [None] * 8  # type: ignore[misc]

    def _poll(slot: int) -> None:
        try:
            results[slot] = _fapp.get_user_input_next()
        except BaseException as exc:  # noqa: BLE001
            results[slot] = exc

    _run_barrier_pollers(8, _poll)

    assert all(not isinstance(r, BaseException) for r in results)
    messages = [r["message"] for r in results]  # type: ignore[index]
    assert messages.count(None) == 6
    assert sum(1 for m in messages if m is not None) == 2
    assert set(m for m in messages if m is not None) == {"msg-a", "msg-b"}


def test_user_input_next_concurrent_equal_threads_and_messages(monkeypatch):
    """N threads compete for exactly N messages: all N threads get a non-null message."""
    n = 5
    queue = collections.deque(maxlen=50)
    for i in range(n):
        queue.appendleft({"message": f"item-{i}", "source": "portal", "ts": float(i)})
    monkeypatch.setattr(_fapp, "_USER_INPUT_QUEUE", queue)

    results: list[dict | BaseException] = [None] * n  # type: ignore[misc]

    def _poll(slot: int) -> None:
        try:
            results[slot] = _fapp.get_user_input_next()
        except BaseException as exc:  # noqa: BLE001
            results[slot] = exc

    _run_barrier_pollers(n, _poll)

    assert all(not isinstance(r, BaseException) for r in results)
    messages = [r["message"] for r in results]  # type: ignore[index]
    assert all(m is not None for m in messages)
    assert len(set(messages)) == n  # each thread got a distinct message


# ---------------------------------------------------------------------------
# Regression: queue emptied after pop, not before — single-pass drain
# ---------------------------------------------------------------------------


def test_get_user_input_next_queue_is_empty_after_single_item_consumed(monkeypatch):
    """After popping the sole entry, the underlying deque is empty (len == 0)."""
    queue = collections.deque(maxlen=50)
    queue.appendleft({"message": "last", "source": "cli", "ts": 7.0})
    monkeypatch.setattr(_fapp, "_USER_INPUT_QUEUE", queue)

    _fapp.get_user_input_next()  # consumes the item

    assert len(_fapp._USER_INPUT_QUEUE) == 0
    assert not _fapp._USER_INPUT_QUEUE  # falsy — fast-path guard will fire next time


def test_get_user_input_next_repeated_empty_polls_never_raise(monkeypatch):
    """Repeated polls on an empty queue always return null — no error on any call."""
    monkeypatch.setattr(_fapp, "_USER_INPUT_QUEUE", collections.deque(maxlen=50))
    for _ in range(10):
        result = _fapp.get_user_input_next()
        assert result == {"message": None}
