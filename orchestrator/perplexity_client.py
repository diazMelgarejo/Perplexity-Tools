from __future__ import annotations

import json as _json
import os
from typing import Any, Dict, Iterator, List, Optional

import httpx


class PerplexityClient:
    """
    Thin wrapper for Perplexity API (sonar-reasoning-pro / sonar-pro).
    Used by the top-level orchestrator on Mac or Windows when online.
    Subagents call this only when routed here by ModelRegistry.route_task().
    """

    DEFAULT_MODEL = "sonar-reasoning-pro"
    BASE_URL = "https://api.perplexity.ai"

    def __init__(
        self,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        timeout: float = 120.0,
    ) -> None:
        self.api_key = api_key or os.getenv("PERPLEXITY_API_KEY", "")
        self.base_url = (base_url or self.BASE_URL).rstrip("/")
        self.timeout = timeout

    def _headers(self) -> Dict[str, str]:
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

    def chat(
        self,
        messages: List[Dict[str, str]],
        model: Optional[str] = None,
        temperature: float = 0.2,
        stream: bool = False,
    ) -> Dict[str, Any]:
        payload: Dict[str, Any] = {
            "model": model or self.DEFAULT_MODEL,
            "messages": messages,
            "temperature": temperature,
            "stream": stream,
        }
        response = httpx.post(
            f"{self.base_url}/chat/completions",
            headers=self._headers(),
            json=payload,
            timeout=self.timeout,
        )
        response.raise_for_status()
        return response.json()

    def stream(
        self,
        messages: List[Dict[str, str]],
        model: Optional[str] = None,
        temperature: float = 0.2,
    ) -> Iterator[str]:
        """Yield text deltas from a streaming chat completion."""
        payload: Dict[str, Any] = {
            "model": model or self.DEFAULT_MODEL,
            "messages": messages,
            "temperature": temperature,
            "stream": True,
        }
        with httpx.stream(
            "POST",
            f"{self.base_url}/chat/completions",
            headers=self._headers(),
            json=payload,
            timeout=self.timeout,
        ) as resp:
            resp.raise_for_status()
            for line in resp.iter_lines():
                if line.startswith("data: ") and line != "data: [DONE]":
                    chunk = _json.loads(line[6:])
                    delta = chunk["choices"][0].get("delta", {})
                    text = delta.get("content", "")
                    if text:
                        yield text
