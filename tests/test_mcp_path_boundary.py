"""Python wrapper tests — MCP path boundary implemented in local-agents (fix 4)."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]
_NODE_TEST = _REPO / "packages" / "local-agents" / "tests" / "path-boundary.test.cjs"
_MCP_PROFILES_TEST = _REPO / "packages" / "alphaclaw-mcp" / "tests" / "mcp-profiles.test.cjs"


def test_node_path_boundary_suite_passes() -> None:
    """Run the canonical JS path-boundary tests (node --test)."""
    assert _NODE_TEST.is_file(), f"missing {_NODE_TEST}"
    proc = subprocess.run(
        ["node", "--test", str(_NODE_TEST)],
        cwd=_REPO,
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr


def test_mcp_profiles_module_built() -> None:
    """MCP server imports build/mcp-profiles.js — must exist after tsc."""
    profiles_js = _REPO / "packages" / "alphaclaw-mcp" / "build" / "mcp-profiles.js"
    assert profiles_js.is_file(), f"missing {profiles_js} (run npm run build in alphaclaw-mcp)"


def test_node_mcp_profiles_suite_passes() -> None:
    assert _MCP_PROFILES_TEST.is_file(), f"missing {_MCP_PROFILES_TEST}"
    proc = subprocess.run(
        ["node", "--test", str(_MCP_PROFILES_TEST)],
        cwd=_REPO / "packages" / "alphaclaw-mcp",
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
