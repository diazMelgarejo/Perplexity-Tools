from __future__ import annotations

import asyncio

import pytest

import orchestrator.perplexity_client as pc


def test_ensure_credentials_accepts_web_login_fallback(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("PERPLEXITY_API_KEY", raising=False)
    monkeypatch.delenv("PERPLEXITY_AUTH_MODE", raising=False)
    monkeypatch.setattr(pc.sys.stdin, "isatty", lambda: True)

    answers = iter(["", "y"])
    monkeypatch.setattr("builtins.input", lambda _prompt="": next(answers))

    status = pc.ensure_credentials(
        validate=True,
        interactive=True,
        allow_web_fallback=True,
    )

    assert status["configured"] is True
    assert status["ready_for_api"] is False
    assert status["auth_mode"] == "web-login"
    assert "PERPLEXITY_AUTH_MODE=web-login" in (tmp_path / ".env").read_text(encoding="utf-8")


def test_client_refuses_programmatic_calls_in_web_login_mode(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("PERPLEXITY_AUTH_MODE", "web-login")
    monkeypatch.delenv("PERPLEXITY_API_KEY", raising=False)
    pc.PerplexityClient.reset()

    client = pc.PerplexityClient(interactive=False)

    with pytest.raises(RuntimeError, match="web-login fallback"):
        asyncio.run(
            client.chat_async([{"role": "user", "content": "hello"}])
        )
