"""orchestrator/perplexity_client.py

Validated singleton PerplexityClient backed by the openai SDK.
Perplexity officially endorses the openai-compatible endpoint, and the
openai package is already in the stack via crewai / other deps.

Public API (backward-compatible with old httpx-based client):
    PerplexityClient.get(validate=False, interactive=True)  # singleton accessor
    client.chat(messages, model, **kw)       -> dict (OpenAI response shape)
    client.chat_async(messages, model, **kw) -> dict
    client.stream(messages, model)           -> Iterator[str]

Key handling:
    1. Reads PERPLEXITY_API_KEY from env (or already-loaded .env)
    2. If missing / invalid, prompts interactively once
    3. Saves accepted key to .env via python-dotenv set_key()
    4. Singleton: subsequent PerplexityClient.get() calls reuse the instance
"""
from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional

# Load .env on first import so PERPLEXITY_API_KEY is available immediately
try:
    from dotenv import load_dotenv, set_key as _dotenv_set_key
    load_dotenv(dotenv_path=Path(".") / ".env", override=False)
except ImportError:
    _dotenv_set_key = None  # type: ignore[assignment]

from openai import OpenAI, AsyncOpenAI


_ENV_FILE = Path(".") / ".env"


def _save_key(key: str) -> None:
    """Persist key to .env. Silently skips if dotenv unavailable."""
    if _dotenv_set_key is not None:
        _ENV_FILE.touch(exist_ok=True)
        _dotenv_set_key(str(_ENV_FILE), "PERPLEXITY_API_KEY", key)
        print(f"[PerplexityClient] \u2713 Key saved to {_ENV_FILE}")
    else:
        print(
            "[PerplexityClient] \u26a0 python-dotenv not installed \u2014 "
            "add PERPLEXITY_API_KEY to .env manually."
        )


def _validate_key(key: str) -> bool:
    """Delegate to shared key_helper. Returns True if key is live."""
    try:
        from orchestrator.key_helper import test_perplexity_key
        return test_perplexity_key(key)
    except ImportError:
        return bool(key and key.strip())


def _prompt_for_key() -> str:
    """Interactive key prompt with validation loop. Always returns a key string
    (may be empty if stdin is not a TTY \u2014 callers must handle that)."""
    if not sys.stdin.isatty():
        return ""
    print("\n[PerplexityClient] PERPLEXITY_API_KEY not set or invalid.")
    print("  Get one at: https://www.perplexity.ai/settings/api")
    for attempt in range(3):
        raw = input("  Paste key (pplx-\u2026, or Enter to skip): ").strip()
        if not raw:
            print("  \u26a0 Skipping \u2014 Perplexity features will be unavailable.")
            return ""
        print("  Validating\u2026 ", end="", flush=True)
        if _validate_key(raw):
            print("\u2713")
            os.environ["PERPLEXITY_API_KEY"] = raw
            _save_key(raw)
            return raw
        print("\u2717 invalid")
        if attempt < 2:
            print("  Try again.")
    print("  \u26a0 Giving up after 3 attempts.")
    return ""


class PerplexityClient:
    """
    Validated singleton PerplexityClient (openai SDK, Perplexity-compatible endpoint).

    Usage:
        client = PerplexityClient.get()   # singleton
        result = client.chat([{"role": "user", "content": "hello"}])
        # or async:
        result = await client.chat_async([{"role": "user", "content": "hello"}])
    """

    BASE_URL      = "https://api.perplexity.ai"
    DEFAULT_MODEL = "sonar-pro"
    _instance: "PerplexityClient | None" = None

    def __init__(
        self,
        api_key: Optional[str] = None,
        validate: bool = False,
        interactive: bool = True,
    ) -> None:
        key = (api_key or os.getenv("PERPLEXITY_API_KEY", "")).strip()

        if validate and key and not _validate_key(key):
            print("[PerplexityClient] \u26a0 stored key failed validation \u2014 re-prompting")
            key = ""

        if not key and interactive:
            key = _prompt_for_key()

        self.api_key = key
        self._sync  = OpenAI(api_key=key or "no-key",  base_url=self.BASE_URL)
        self._async = AsyncOpenAI(api_key=key or "no-key", base_url=self.BASE_URL)

    # ── singleton accessor ────────────────────────────────────────────────────

    @classmethod
    def get(
        cls,
        validate: bool = False,
        interactive: bool = True,
    ) -> "PerplexityClient":
        """Return the singleton instance, creating it on first call."""
        if cls._instance is None:
            cls._instance = cls(validate=validate, interactive=interactive)
        return cls._instance

    @classmethod
    def reset(cls) -> None:
        """Clear the singleton (for testing / re-auth)."""
        cls._instance = None

    # ── synchronous chat ──────────────────────────────────────────────────────

    def chat(
        self,
        messages: List[Dict[str, str]],
        model: Optional[str] = None,
        temperature: float = 0.2,
        stream: bool = False,
        **kw: Any,
    ) -> Dict[str, Any]:
        """Synchronous chat completion. Returns OpenAI response dict shape."""
        r = self._sync.chat.completions.create(
            model=model or self.DEFAULT_MODEL,
            messages=messages,  # type: ignore[arg-type]
            temperature=temperature,
            stream=False,
            **kw,
        )
        return {
            "choices": [
                {"message": {"content": r.choices[0].message.content}}
            ]
        }

    # ── async chat ────────────────────────────────────────────────────────────

    async def chat_async(
        self,
        messages: List[Dict[str, str]],
        model: Optional[str] = None,
        temperature: float = 0.2,
        **kw: Any,
    ) -> Dict[str, Any]:
        """Async chat completion."""
        r = await self._async.chat.completions.create(
            model=model or self.DEFAULT_MODEL,
            messages=messages,  # type: ignore[arg-type]
            temperature=temperature,
            **kw,
        )
        return {
            "choices": [
                {"message": {"content": r.choices[0].message.content}}
            ]
        }

    # ── streaming (backward-compat) ───────────────────────────────────────────

    def stream(
        self,
        messages: List[Dict[str, str]],
        model: Optional[str] = None,
        temperature: float = 0.2,
        **kw: Any,
    ) -> Iterator[str]:
        """Yield text deltas from a streaming chat completion."""
        for chunk in self._sync.chat.completions.create(
            model=model or self.DEFAULT_MODEL,
            messages=messages,  # type: ignore[arg-type]
            temperature=temperature,
            stream=True,
            **kw,
        ):
            text = (chunk.choices[0].delta.content or "") if chunk.choices else ""
            if text:
                yield text
