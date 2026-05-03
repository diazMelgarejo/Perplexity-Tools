#!/usr/bin/env python3
"""
test_perplexity.py — Quick smoke-test for Perplexity integration
Run: python scripts/test_perplexity.py

Tests all three client modes:
  - Perplexity sonar (cloud search)
  - sync  via PerplexityClient.search()
  - async via PerplexityClient.search_async()
"""
import asyncio
import sys
from pathlib import Path

# Ensure repo root is on path when run directly
_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

try:
    from dotenv import load_dotenv
    load_dotenv(_REPO_ROOT / ".env")
except ImportError:
    pass

from orchestrator.perplexity_client import PerplexityClient


async def _run_tests() -> None:
    print("\n" + "═" * 54)
    print("   Perpetua-Tools  ·  Connection Smoke Test")
    print("═" * 54)

    # Singleton construction — key prompt fires here if PERPLEXITY_API_KEY missing
    client = PerplexityClient.get()

    all_ok = True

    # ── Test 1: synchronous search ────────────────────────────────────────────
    print("\n[1/2] Synchronous search (sonar-pro)…")
    try:
        result = client.search(
            "Reply with only the single word: pong",
            model="sonar",
        )
        ok = "pong" in result.lower()
        print(f"  {'✅ PASS' if ok else '⚠  WARN'}  sync search")
        if not ok:
            print(f"       Got: {result[:80]}")
        all_ok = all_ok and ok
    except Exception as exc:
        print(f"  ❌ FAIL  sync search → {exc}")
        all_ok = False

    # ── Test 2: async search ──────────────────────────────────────────────────
    print("\n[2/2] Async search (sonar-pro)…")
    try:
        result = await client.search_async(
            "What are the latest benchmarks for Qwen3-Coder-480B on HumanEval?"
        )
        ok = len(result) > 20
        print(f"  {'✅ PASS' if ok else '⚠  WARN'}  async search")
        if ok:
            print(f"       Preview: {result[:120]}…")
        else:
            print(f"       Got: {result!r}")
        all_ok = all_ok and ok
    except Exception as exc:
        print(f"  ❌ FAIL  async search → {exc}")
        all_ok = False

    print("\n" + "─" * 54)
    print("  ✅ All tests passed!" if all_ok else "  ❌ One or more tests failed.")
    print("═" * 54 + "\n")

    sys.exit(0 if all_ok else 1)


if __name__ == "__main__":
    asyncio.run(_run_tests())
