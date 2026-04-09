"""orchestrator/key_helper.py

Shared Perplexity API key validation helper.
Imported by both setup_wizard.py and orchestrator/perplexity_client.py
to avoid duplicate validation logic.
"""
from __future__ import annotations

PERPLEXITY_BASE = "https://api.perplexity.ai"


def test_perplexity_key(key: str) -> bool:
    """Return True if key passes a live sonar ping (max_tokens=1).

    Uses a cheap, minimal call so the validation is near-instant and
    costs essentially nothing.
    """
    if not key or not key.strip():
        return False
    try:
        from openai import OpenAI
        client = OpenAI(api_key=key.strip(), base_url=PERPLEXITY_BASE, timeout=8)
        r = client.chat.completions.create(
            model="sonar",
            messages=[{"role": "user", "content": "ping"}],
            max_tokens=1,
        )
        return bool(r.choices)
    except Exception:
        return False
