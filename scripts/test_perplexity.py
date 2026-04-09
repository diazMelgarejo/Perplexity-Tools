#!/usr/bin/env python3
"""
scripts/test_perplexity.py
--------------------------
Smoke-test for the PerplexityClient singleton.

Creates the validated client singleton and calls chat_async with a simple
query. Prints the result and exits 0 on success, 1 on failure.

Usage:
    python scripts/test_perplexity.py
    python scripts/test_perplexity.py --query "What is the AlphaClaw gateway?"
    python scripts/test_perplexity.py --base-url https://api.perplexity.ai --timeout 30
"""
from __future__ import annotations

import argparse
import asyncio
import sys
import os

# Allow running from repo root without installing the package
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


async def main(query: str, base_url: str | None, timeout: float) -> int:
    print("[test_perplexity] Initialising PerplexityClient singleton\u2026")
    try:
        from orchestrator.perplexity_client import PerplexityClient
    except ImportError as e:
        print(f"[test_perplexity] \u2717 Import failed: {e}")
        print("  Run: pip install openai python-dotenv")
        return 1

    try:
        client = PerplexityClient.get(
            validate=True,
            interactive=True,
            base_url=base_url,
            timeout=timeout,
        )
        status = client.status()
        print(
            "[test_perplexity] \u2713 Singleton ready "
            f"(model={client.DEFAULT_MODEL}, auth_mode={status['auth_mode']})"
        )
        if not status["ready_for_api"]:
            print(f"[test_perplexity] \u26a0 {status['message']}")
            return 1
    except Exception as e:
        print(f"[test_perplexity] \u2717 Client init failed: {e}")
        return 1

    print(f"[test_perplexity] \u2192 Query: {query!r}")
    try:
        result = await client.chat_async(
            messages=[{"role": "user", "content": query}]
        )
        content = result["choices"][0]["message"]["content"]
        print("[test_perplexity] \u2713 Response received:")
        print("-" * 60)
        print(content[:800])
        if len(content) > 800:
            print(f"  \u2026 ({len(content) - 800} chars truncated)")
        print("-" * 60)
        return 0
    except Exception as e:
        print(f"[test_perplexity] \u2717 search_async failed: {e}")
        return 1


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Smoke-test for PerplexityClient singleton"
    )
    parser.add_argument(
        "--query",
        default="What is the latest version of the sonar-pro model?",
        help="Query to send to Perplexity sonar-pro",
    )
    parser.add_argument(
        "--base-url",
        default=None,
        help="Optional Perplexity-compatible base URL override",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=120.0,
        help="Optional request timeout in seconds",
    )
    args = parser.parse_args()
    sys.exit(asyncio.run(main(args.query, args.base_url, args.timeout)))
