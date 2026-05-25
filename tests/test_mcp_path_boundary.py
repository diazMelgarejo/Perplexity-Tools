"""Python wrapper tests — MCP path boundary implemented in local-agents (fix 4)."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]
_NODE_TEST = _REPO / "packages" / "local-agents" / "tests" / "path-boundary.test.cjs"


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
