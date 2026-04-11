"""orchestrator/key_helper.py
Shared Perplexity API key validation helper.

Imported by setup_wizard.py and orchestrator/perplexity_client.py to avoid
duplicating the validation logic.  Deliberately minimal — no side-effects,
no imports beyond the stdlib and openai.
"""
from __future__ import annotations

import os

PERPLEXITY_BASE = "https://api.perplexity.ai"
_VALIDATION_MODEL = "sonar"          # cheapest model for key probing
_VALIDATION_TIMEOUT = 8              # seconds


def test_perplexity_key(key: str) -> bool:
    """Validate a Perplexity API key with a real (cheap) sonar call.

    Returns True if the key is accepted, False for any auth / network error.
    Uses max_tokens=1 to minimise cost.
    """
    if not key or not key.startswith("pplx-"):
        return False
    try:
        from openai import OpenAI
        client = OpenAI(api_key=key, base_url=PERPLEXITY_BASE,
                        timeout=_VALIDATION_TIMEOUT)
        r = client.chat.completions.create(
            model=_VALIDATION_MODEL,
            messages=[{"role": "user", "content": "ping"}],
            max_tokens=1,
        )
        return bool(r.choices)
    except Exception:
        return False


def prompt_for_perplexity_key(env_path: str | os.PathLike | None = None) -> str | None:
    """Interactively prompt for a Perplexity API key, validate it, and save it.

    If *env_path* is given the validated key is written there via
    ``dotenv.set_key()``.  Returns the validated key, or None if the user
    skips (empty input).
    """
    from pathlib import Path

    print("\n  No PERPLEXITY_API_KEY found (or key is invalid).")
    print("  Get yours at: https://www.perplexity.ai/settings/api")
    print("  (Press Enter to skip — some features will be disabled)\n")

    while True:
        raw = input("  Paste API key (starts with pplx-): ").strip()
        if not raw:
            print("  ⚠  Skipping Perplexity key — cloud search disabled.\n")
            return None
        if not raw.startswith("pplx-"):
            print("  ✗  Key should start with 'pplx-'. Try again.\n")
            continue
        print("  Validating…", end="", flush=True)
        if test_perplexity_key(raw):
            print(" ✓")
            if env_path:
                try:
                    from dotenv import set_key
                    Path(env_path).parent.mkdir(parents=True, exist_ok=True)
                    set_key(str(env_path), "PERPLEXITY_API_KEY", raw)
                    print(f"  ✓ Key saved to {env_path}\n")
                except Exception as exc:
                    print(f"\n  ⚠  Could not save key: {exc}\n")
            return raw
        print(" ✗  Key not accepted — check it and try again.\n")
