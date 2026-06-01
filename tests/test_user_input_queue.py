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


def test_user_input_next_concurrent_pop_never_raises(monkeypatch):
    """Two pollers on one queued message: one wins, one gets null — no IndexError."""
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
