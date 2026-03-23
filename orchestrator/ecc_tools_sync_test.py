"""
Quick smoke test for ECC Tools sync module.
Run: python -m orchestrator.ecc_tools_sync_test
"""

from __future__ import annotations

import sys
from pathlib import Path


def main() -> None:
    print("=== ECC Tools Sync Smoke Test ===\n")

    from orchestrator.ecc_tools_sync import (
        STATE_FILE,
        VENDOR_DIR,
        get_sync_status,
        sync_ecc_tools,
    )

    status = get_sync_status()
    print(f"Pre-sync status: {status.get('status')}")
    print(f"Vendor dir exists: {VENDOR_DIR.exists()}")
    print(f"State file exists: {STATE_FILE.exists()}\n")

    print("Running sync (force=False)...")
    result = sync_ecc_tools(force=False)
    print(f"Result status: {result['status']}")
    print(f"Message: {result.get('message', '')}")
    if result["status"] == "synced":
        print(f"  Copied: {len(result.get('copied', []))} files")
        print(f"  Skipped: {result.get('skipped_count', 0)} files")
        print(f"  Missing source: {result.get('missing_source', [])}")
        print(f"  Errors: {result.get('errors', [])}")

    print("\nRunning sync again (should be idempotent 'up_to_date')...")
    result2 = sync_ecc_tools(force=False)
    if result2["status"] not in ("up_to_date", "synced"):
        print(f"Unexpected status: {result2['status']}")
        sys.exit(1)
    print(f"Result status: {result2['status']} ✓")

    key_file = Path(".claude/ecc-tools.json")
    if key_file.exists():
        print(f"\nKey file present: {key_file} ✓")
    else:
        print(f"\nWARNING: Key file missing: {key_file} (expected after successful sync)")
        sys.exit(1)

    print("\n=== Smoke test PASSED ===")


if __name__ == "__main__":
    main()
