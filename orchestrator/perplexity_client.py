from __future__ import annotations

import os
import sys
from typing import Any, Dict, Iterator, List, Optional


class PerplexityClient:
    """
    Validated singleton Perplexity API client.

    Uses the OpenAI-compatible SDK (openai package) with Perplexity's base URL —
    the officially endorsed approach that reuses the openai package already
    present in the stack via crewai.

    Key properties:
    - Clients (sync + async) are created ONCE in __init__ and reused.
    - If PERPLEXITY_API_KEY is missing or invalid at first construction,
      an interactive prompt fires (saves the key to .env via dotenv.set_key).
    - PerplexityClient.get() returns the process-wide singleton.
    - stream() is kept for backward compatibility with callers expecting an
      iterator of text deltas.
    """

    BASE_URL      = "https://api.perplexity.ai"
    DEFAULT_MODEL = "sonar-pro"

    _instance: "PerplexityClient | None" = None

    # ── construction ──────────────────────────────────────────────────────────

    def __init__(
        self,
        api_key:  Optional[str] = None,
        validate: bool = False,
        timeout:  float = 120.0,
    ) -> None:
        try:
            from openai import AsyncOpenAI, OpenAI
        except ImportError as exc:
            raise ImportError(
                "openai package is required: pip install openai"
            ) from exc

        key = (api_key or os.getenv("PERPLEXITY_API_KEY", "")).strip()

        if validate and key:
            if not self._test_key(key):
                key = ""   # will trigger interactive prompt below

        if not key:
            key = self._prompt_for_key() or ""

        self.api_key = key
        self._sync  = OpenAI(api_key=key,      base_url=self.BASE_URL, timeout=timeout)
        self._async = AsyncOpenAI(api_key=key,  base_url=self.BASE_URL, timeout=timeout)

    # ── singleton accessor ─────────────────────────────────────────────────────

    @classmethod
    def get(cls, **kwargs: Any) -> "PerplexityClient":
        """Return the process-wide singleton, creating it once on first call."""
        if cls._instance is None:
            cls._instance = cls(**kwargs)
        return cls._instance

    # ── key helpers ───────────────────────────────────────────────────────────

    @staticmethod
    def _test_key(key: str) -> bool:
        """Validate a Perplexity key with a cheap real sonar ping."""
        try:
            from orchestrator.key_helper import test_perplexity_key
            return test_perplexity_key(key)
        except ImportError:
            pass
        try:
            from openai import OpenAI
            client = OpenAI(api_key=key, base_url=PerplexityClient.BASE_URL, timeout=8)
            r = client.chat.completions.create(
                model="sonar",
                messages=[{"role": "user", "content": "ping"}],
                max_tokens=1,
            )
            return bool(r.choices)
        except Exception:
            return False

    @classmethod
    def _prompt_for_key(cls) -> Optional[str]:
        """Interactive key prompt; saves valid key to .env. Returns key or None."""
        try:
            from pathlib import Path
            from dotenv import set_key
            env_path = Path(__file__).resolve().parent.parent / ".env"
        except ImportError:
            env_path = None  # type: ignore[assignment]

        print("\n  PERPLEXITY_API_KEY not found or invalid.")
        print("  Get yours at: https://www.perplexity.ai/settings/api")
        print("  (Press Enter to skip)\n")

        while True:
            raw = input("  Paste API key (starts with pplx-): ").strip()
            if not raw:
                print("  ⚠  Skipping — Perplexity cloud search disabled.\n")
                return None
            if not raw.startswith("pplx-"):
                print("  ✗  Key should start with 'pplx-'. Try again.\n")
                continue
            print("  Validating…", end="", flush=True)
            if cls._test_key(raw):
                print(" ✓")
                if env_path is not None:
                    try:
                        env_path.touch(exist_ok=True)
                        set_key(str(env_path), "PERPLEXITY_API_KEY", raw)
                        print(f"  ✓ Key saved to {env_path}\n")
                    except Exception as exc:
                        print(f"\n  ⚠  Could not save to .env: {exc}\n")
                return raw
            print(" ✗  Key not accepted. Try again.\n")

    # ── synchronous API ───────────────────────────────────────────────────────

    def chat(
        self,
        messages: List[Dict[str, str]],
        model: Optional[str] = None,
        temperature: float = 0.2,
        stream: bool = False,
        **kw: Any,
    ) -> Dict[str, Any]:
        """Synchronous chat completion — returns the full response dict."""
        r = self._sync.chat.completions.create(
            model=model or self.DEFAULT_MODEL,
            messages=messages,
            temperature=temperature,
            stream=stream,
            **kw,
        )
        # Normalise to the dict shape callers expect
        return {
            "choices": [
                {"message": {"content": r.choices[0].message.content}}
            ]
        }

    def search(self, query: str, model: Optional[str] = None) -> str:
        """Convenience: send a single user query, return the text reply."""
        result = self.chat(
            messages=[{"role": "user", "content": query}],
            model=model or "sonar-pro",
        )
        return result["choices"][0]["message"]["content"]

    def stream(
        self,
        messages: List[Dict[str, str]],
        model: Optional[str] = None,
        temperature: float = 0.2,
    ) -> Iterator[str]:
        """Yield text deltas (backward-compatible streaming interface)."""
        response = self._sync.chat.completions.create(
            model=model or self.DEFAULT_MODEL,
            messages=messages,
            temperature=temperature,
            stream=True,
        )
        for chunk in response:
            delta = chunk.choices[0].delta
            if delta and delta.content:
                yield delta.content

    # ── async API ─────────────────────────────────────────────────────────────

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
            messages=messages,
            temperature=temperature,
            **kw,
        )
        return {
            "choices": [
                {"message": {"content": r.choices[0].message.content}}
            ]
        }

    async def search_async(self, query: str, model: Optional[str] = None) -> str:
        """Async convenience search — returns text reply."""
        result = await self.chat_async(
            messages=[{"role": "user", "content": query}],
            model=model or "sonar-pro",
        )
        return result["choices"][0]["message"]["content"]
