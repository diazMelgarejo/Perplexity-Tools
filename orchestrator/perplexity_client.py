"""orchestrator/perplexity_client.py

Validated singleton PerplexityClient backed by the openai SDK.
Perplexity officially endorses the openai-compatible endpoint, and the
openai package is already in the stack via crewai / other deps.

Public API (backward-compatible with old httpx-based client):
    PerplexityClient.get(
        validate=False,
        interactive=True,
        base_url=None,
        timeout=120.0,
    )  # singleton accessor
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

try:
    from openai import OpenAI, AsyncOpenAI
except ImportError:  # pragma: no cover - exercised indirectly in setup flows
    OpenAI = None  # type: ignore[assignment]
    AsyncOpenAI = None  # type: ignore[assignment]


_ENV_FILE = Path(".") / ".env"
_AUTH_MODE_ENV = "PERPLEXITY_AUTH_MODE"
_AUTH_MODE_API = "api-key"
_AUTH_MODE_WEB = "web-login"


def _update_env_file(key: str, value: str) -> None:
    """Persist a key/value pair to .env, falling back to a manual rewrite."""
    _ENV_FILE.touch(exist_ok=True)
    if _dotenv_set_key is not None:
        _dotenv_set_key(str(_ENV_FILE), key, value, quote_mode="never")
        return

    existing: list[str] = []
    if _ENV_FILE.exists():
        existing = _ENV_FILE.read_text(encoding="utf-8").splitlines()

    prefix = f"{key}="
    rewritten = [line for line in existing if not line.startswith(prefix)]
    rewritten.append(f"{key}={value}")
    _ENV_FILE.write_text("\n".join(rewritten).strip() + "\n", encoding="utf-8")


def _save_key(key: str) -> None:
    """Persist key to .env. Silently skips if dotenv unavailable."""
    try:
        _update_env_file("PERPLEXITY_API_KEY", key)
        _update_env_file(_AUTH_MODE_ENV, _AUTH_MODE_API)
        print(f"[PerplexityClient] \u2713 Key saved to {_ENV_FILE}")
    except Exception:
        print(
            "[PerplexityClient] \u26a0 Could not persist PERPLEXITY_API_KEY "
            f"to {_ENV_FILE}. Add it manually."
        )


def _save_auth_mode(mode: str) -> None:
    """Persist the chosen authentication mode to .env."""
    try:
        _update_env_file(_AUTH_MODE_ENV, mode)
    except Exception:
        print(
            "[PerplexityClient] \u26a0 Could not persist PERPLEXITY_AUTH_MODE "
            f"to {_ENV_FILE}. Add it manually."
        )


def _validate_key(key: str) -> bool:
    """Delegate to shared key_helper. Returns True if key is live."""
    try:
        from orchestrator.key_helper import test_perplexity_key
        return test_perplexity_key(key)
    except ImportError:
        return bool(key and key.strip())


def credential_status(validate: bool = False) -> Dict[str, Any]:
    """Return the current Perplexity credential/onboarding state."""
    key = os.getenv("PERPLEXITY_API_KEY", "").strip()
    auth_mode = os.getenv(_AUTH_MODE_ENV, "").strip() or (_AUTH_MODE_API if key else "unset")
    validated = bool(key)
    if key and validate:
        validated = _validate_key(key)
    ready_for_api = bool(key) and validated
    configured = ready_for_api or auth_mode == _AUTH_MODE_WEB
    message = "Perplexity API key ready." if ready_for_api else ""
    if auth_mode == _AUTH_MODE_WEB and not ready_for_api:
        message = (
            "Web-login fallback selected. Programmatic Perplexity API calls "
            "remain unavailable until PERPLEXITY_API_KEY is configured."
        )
    elif not configured:
        message = "Perplexity credentials are not configured."
    elif key and validate and not validated:
        message = "Stored PERPLEXITY_API_KEY failed validation."

    return {
        "configured": configured,
        "ready_for_api": ready_for_api,
        "validated": validated,
        "auth_mode": auth_mode,
        "has_api_key": bool(key),
        "message": message,
    }


def ensure_credentials(
    *,
    validate: bool = False,
    interactive: bool = True,
    allow_web_fallback: bool = True,
) -> Dict[str, Any]:
    """Ensure Perplexity onboarding is complete.

    Returns a structured status dict that can be reused by setup flows and the
    runtime control plane.
    """
    status = credential_status(validate=validate)
    if status["ready_for_api"]:
        return status
    if status["auth_mode"] == _AUTH_MODE_WEB:
        return status
    if not interactive or not sys.stdin.isatty():
        return status

    print("\n[PerplexityClient] Perplexity onboarding")
    print("  API key is preferred for programmatic search and orchestration.")
    print("  Get one at: https://www.perplexity.ai/settings/api")
    print("  If you only plan to use the website UI for now, you can choose web-login fallback.")

    for attempt in range(3):
        raw = input("  Paste API key (pplx-..., or Enter to choose fallback): ").strip()
        if raw:
            print("  Validating\u2026 ", end="", flush=True)
            if _validate_key(raw):
                print("\u2713")
                os.environ["PERPLEXITY_API_KEY"] = raw
                os.environ[_AUTH_MODE_ENV] = _AUTH_MODE_API
                _save_key(raw)
                return credential_status(validate=False)
            print("\u2717 invalid")
            if attempt < 2:
                print("  Try again.")
            continue

        if not allow_web_fallback:
            print("  \u26a0 API key required for this flow.")
            continue

        fallback = input("  Use web-login fallback instead? [Y/n]: ").strip().lower()
        if fallback in ("", "y", "yes"):
            os.environ[_AUTH_MODE_ENV] = _AUTH_MODE_WEB
            _save_auth_mode(_AUTH_MODE_WEB)
            return credential_status(validate=False)
        if attempt < 2:
            print("  Okay, let's try the API key again.")

    return credential_status(validate=validate)


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
            os.environ[_AUTH_MODE_ENV] = _AUTH_MODE_API
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
        client = PerplexityClient.get(base_url="https://api.perplexity.ai", timeout=30.0)
        result = client.chat([{"role": "user", "content": "hello"}])
        # or async:
        result = await client.chat_async([{"role": "user", "content": "hello"}])

    Notes:
        - `stream()` is the preferred streaming API.
        - `chat(..., stream=True)` is kept compatibility-tolerant in this pass.
    """

    BASE_URL      = "https://api.perplexity.ai"
    DEFAULT_MODEL = "sonar-pro"
    _instance: "PerplexityClient | None" = None

    def __init__(
        self,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        timeout: float = 120.0,
        validate: bool = False,
        interactive: bool = True,
    ) -> None:
        self.base_url = (base_url or self.BASE_URL).rstrip("/")
        self.timeout = timeout
        if api_key:
            key = api_key.strip()
            os.environ[_AUTH_MODE_ENV] = _AUTH_MODE_API
            self._status = {
                "configured": True,
                "ready_for_api": bool(key),
                "validated": bool(key),
                "auth_mode": _AUTH_MODE_API,
                "has_api_key": bool(key),
                "message": "Perplexity API key provided directly.",
            }
        else:
            self._status = ensure_credentials(
                validate=validate,
                interactive=interactive,
                allow_web_fallback=True,
            )
            key = os.getenv("PERPLEXITY_API_KEY", "").strip()

        self.api_key = key
        self.auth_mode = self._status["auth_mode"]
        if OpenAI is None or AsyncOpenAI is None:
            self._sync = None
            self._async = None
        else:
            self._sync = OpenAI(
                api_key=key or "no-key",
                base_url=self.base_url,
                timeout=self.timeout,
            )
            self._async = AsyncOpenAI(
                api_key=key or "no-key",
                base_url=self.base_url,
                timeout=self.timeout,
            )

    def status(self) -> Dict[str, Any]:
        return dict(self._status)

    def api_ready(self) -> bool:
        return bool(self._status.get("ready_for_api"))

    def _require_api_ready(self) -> None:
        if self.api_ready():
            if self._sync is None or self._async is None:
                raise RuntimeError(
                    "The openai package is not installed. Run `pip install openai`."
                )
            return
        if self.auth_mode == _AUTH_MODE_WEB:
            raise RuntimeError(
                "Perplexity is configured for web-login fallback only. "
                "Programmatic calls require PERPLEXITY_API_KEY."
            )
        raise RuntimeError(
            "PERPLEXITY_API_KEY is not configured. Run setup_wizard.py or "
            "PerplexityClient.get(validate=True, interactive=True)."
        )

    # ── singleton accessor ────────────────────────────────────────────────────

    @classmethod
    def get(
        cls,
        validate: bool = False,
        interactive: bool = True,
        base_url: Optional[str] = None,
        timeout: float = 120.0,
    ) -> "PerplexityClient":
        """Return the singleton instance, creating it on first call."""
        if cls._instance is None:
            cls._instance = cls(
                validate=validate,
                interactive=interactive,
                base_url=base_url,
                timeout=timeout,
            )
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
        """Synchronous chat completion.

        Returns OpenAI response dict shape. For streaming, prefer `stream()`.
        The `stream=True` argument is accepted here only for backward
        compatibility and is coerced to the non-streaming path.
        """
        self._require_api_ready()
        if stream:
            print("[PerplexityClient] \u26a0 chat(..., stream=True) is compatibility mode; prefer stream().")
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
        self._require_api_ready()
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
        self._require_api_ready()
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
