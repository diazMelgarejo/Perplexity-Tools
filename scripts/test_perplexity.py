#!/usr/bin/env python3
"""
scripts/test_perplexity.py
--------------------------
Smoke-test for the PerplexityClient singleton.

Creates an Orchestrator (via PerplexityClient.get()) and calls search_async
with a simple query. Prints the result and exits 0 on success, 1 on failure.

Usage:
    python scripts/test_perplexity.py
    python scripts/test_perplexity.py --query "What is the AlphaClaw gateway?"
"""
from __future__ import annotations

import argparse
import asyncio
import sys
import os

# Allow running from repo root without installing the package
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


async def main(query: str) -> int:
    print("[test_perplexity] Initialising PerplexityClient singleton\u2026")
    try:
        from orchestrator.perplexity_client import PerplexityClient
    except ImportError as e:
        print(f"[test_perplexity] \u2717 Import failed: {e}")
        print("  Run: pip install openai python-dotenv")
        return 1

    try:
        client = PerplexityClient.get(validate=True, interactive=True)
        print(f"[test_perplexity] \u2713 Singleton ready  (model={client.DEFAULT_MODEL})")
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
    args = parser.parse_args()
    sys.exit(asyncio.run(main(args.query)))
