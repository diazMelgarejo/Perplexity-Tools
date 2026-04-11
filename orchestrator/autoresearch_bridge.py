"""orchestrator/autoresearch_bridge.py

Layer 4 integration: autoresearch as a managed foot-soldier.

Architecture (post-migration)
------------------------------
Primary mode:  uditgoenka/autoresearch Claude Code plugin
               → installed via `claude plugin marketplace add uditgoenka/autoresearch`
               → activated via `/autoresearch` and `/autoresearch:debug` slash commands
               → can execute anywhere (Mac, Windows, CI) without SSH

Secondary mode: When task_type is `ml-experiment`, the GPU runner at $GPU_BOX
                is used as an optional `Verify` substrate via SSH, reading
                swarm_state.md for GPU locks.  This path is NOT removed — it
                becomes the dedicated hardware verifier for ML experiments.

Responsibilities
----------------
- Idempotent git sync of the canonical autoresearch clone on the Windows GPU runner.
- Spawning the three cognitive swarm agents (Coder, Evaluator, Orchestrator) via
  the top-level Perplexity-Tools AgentTracker so lifecycle and idempotency are
  consistent with the rest of the stack.
- Reading swarm_state.md for GPU lock status before dispatching any training run.
- Installing the uditgoenka/autoresearch Claude Code plugin (idempotent).

Design rules (from approved interoperability contract)
------------------------------------------------------
1. ONLY Perplexity-Tools/orchestrator.py (or the FastAPI /autoresearch/* endpoints)
   may call sync_autoresearch_idempotent().  Layers 2-4 treat autoresearch as
   read-only from a lifecycle perspective.
2. The autoresearch clone lives in ONE canonical path on the Windows GPU runner:
       C:/Users/<WINUSER>/autoresearch/
   Never duplicate it.
3. File transfer uses scp only (rsync not guaranteed on Windows SSH sessions).
4. API keys are NEVER written to files; they are injected as session env vars.
5. GPU lock is the IDLE/BUSY flag in swarm_state.md — no external queue daemon.
6. Windows model loading is STRICTLY SEQUENTIAL — never dispatch a new GPU run
   while swarm_state.md shows GPU: BUSY.
"""

from __future__ import annotations

import os
import subprocess
import textwrap
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

# ── configuration (resolved from environment, never hard-coded secrets) ────────

GPU_BOX: str = os.environ.get("GPU_BOX", "WINUSER@192.168.1.100")
GPU_REPO_PATH: str = os.environ.get("GPU_REPO_PATH", "autoresearch")

# Primary: uditgoenka/autoresearch Claude Code plugin (env-var configurable)
AUTORESEARCH_REMOTE: str = os.environ.get(
    "AUTORESEARCH_REMOTE", "https://github.com/uditgoenka/autoresearch.git"
)
AUTORESEARCH_DEFAULT_BRANCH: str = os.environ.get("AUTORESEARCH_BRANCH", "main")

SSH_TIMEOUT: int = int(os.environ.get("SSH_TIMEOUT", "90"))

# SSH identity key — set DELL_SSH_KEY in .env.local (session-only, gitignored).
_SSH_KEY: str = os.environ.get("DELL_SSH_KEY", "")
_SSH_OPTS: list[str] = (
    ["-i", _SSH_KEY, "-o", "BatchMode=yes", "-o", "StrictHostKeyChecking=accept-new"]
    if _SSH_KEY else
    ["-o", "BatchMode=yes", "-o", "StrictHostKeyChecking=accept-new"]
)

# Local Mac path — used only for git history, SKILL.md edits, swarm_state.md.
LOCAL_REPO_PATH: Path = Path(
    os.environ.get("LOCAL_AUTORESEARCH_PATH", str(Path.home() / "autoresearch"))
)
SWARM_STATE_FILE: Path = LOCAL_REPO_PATH / "swarm_state.md"


# ── data types ────────────────────────────────────────────────────────────────

@dataclass
class SyncResult:
    ok: bool
    sha: str = ""
    error: str = ""


@dataclass
class SwarmState:
    gpu_status: str = "IDLE"       # IDLE | BUSY
    baseline_val_bpb: float = 0.0
    baseline_sha: str = ""
    orchestrator_directive: str = ""
    evaluator_findings: list[str] = field(default_factory=list)


# ── progress helper ───────────────────────────────────────────────────────────

def _progress(label: str, msg: str) -> None:
    """Print a single-line status update (no bar — SSH ops have no duration signal)."""
    print(f"  [{label}] {msg}", flush=True)


# ── Claude Code plugin install ────────────────────────────────────────────────

def install_autoresearch_plugin() -> SyncResult:
    """Install the uditgoenka/autoresearch Claude Code plugin idempotently.

    Checks `claude plugin list` first; skips install if already present.
    Runs two commands:
      1. claude plugin marketplace add uditgoenka/autoresearch
      2. claude plugin install autoresearch@autoresearch
    """
    _progress("autoresearch-plugin", "Checking if plugin is already installed…")

    # Check current plugin list
    list_result = subprocess.run(
        ["claude", "plugin", "list"],
        capture_output=True, text=True, timeout=30,
    )
    if list_result.returncode == 0 and "uditgoenka/autoresearch" in list_result.stdout:
        _progress("autoresearch-plugin", "✓ plugin already installed — skipping")
        return SyncResult(ok=True, sha="already-installed")

    # Step 1: marketplace add
    _progress("autoresearch-plugin",
              "→ claude plugin marketplace add uditgoenka/autoresearch")
    add_result = subprocess.run(
        ["claude", "plugin", "marketplace", "add", "uditgoenka/autoresearch"],
        capture_output=True, text=True, timeout=60,
    )
    if add_result.returncode != 0:
        return SyncResult(
            ok=False,
            error=f"marketplace add failed: {add_result.stderr.strip()}"
        )

    # Step 2: install
    _progress("autoresearch-plugin", "→ claude plugin install autoresearch@autoresearch")
    install_result = subprocess.run(
        ["claude", "plugin", "install", "autoresearch@autoresearch"],
        capture_output=True, text=True, timeout=60,
    )
    if install_result.returncode != 0:
        return SyncResult(
            ok=False,
            error=f"plugin install failed: {install_result.stderr.strip()}"
        )

    _progress("autoresearch-plugin", "✓ uditgoenka/autoresearch plugin installed")
    return SyncResult(ok=True)


# ── idempotent sync (called by orchestrator before EVERY autoresearch run) ─────

def sync_autoresearch_idempotent() -> SyncResult:
    """Pull latest autoresearch on the Windows GPU runner.

    Idempotent: safe to call on every orchestration cycle.
    Uses `git fetch + reset --hard origin/<AUTORESEARCH_DEFAULT_BRANCH>` so the
    runner always runs the latest upstream code without merge conflicts.

    Returns SyncResult with HEAD sha for logging.
    """
    _progress("autoresearch", f"→ Syncing on GPU runner ({GPU_BOX})…")
    cmd = (
        f"cd {GPU_REPO_PATH} && "
        "git fetch origin && "
        f"git reset --hard origin/{AUTORESEARCH_DEFAULT_BRANCH} && "
        "git rev-parse HEAD"
    )
    try:
        result = subprocess.run(
            ["ssh", *_SSH_OPTS, GPU_BOX, cmd],
            capture_output=True,
            text=True,
            timeout=SSH_TIMEOUT,
        )
        if result.returncode != 0:
            _progress("autoresearch", f"✗ sync failed: {result.stderr.strip()}")
            return SyncResult(ok=False, error=result.stderr.strip())
        sha = result.stdout.strip().splitlines()[-1]
        _progress("autoresearch", f"✓ synced  sha={sha[:8]}")
        return SyncResult(ok=True, sha=sha)
    except subprocess.TimeoutExpired:
        msg = f"SSH timeout after {SSH_TIMEOUT}s"
        _progress("autoresearch", f"✗ {msg}")
        return SyncResult(ok=False, error=msg)
    except Exception as exc:  # noqa: BLE001
        _progress("autoresearch", f"✗ {exc}")
        return SyncResult(ok=False, error=str(exc))


# ── bootstrap: ensure the repo exists on the GPU runner (first-run only) ──────

def bootstrap_autoresearch_on_runner() -> SyncResult:
    """Clone autoresearch on the Windows GPU runner if it does not exist yet.

    Idempotent: if the directory already exists, falls through to a normal sync.
    Uses uv sync --dev to install dev dependencies (uditgoenka/autoresearch uses
    pyproject.toml with dev extras).
    """
    _progress("autoresearch", f"→ Checking / bootstrapping on GPU runner ({GPU_BOX})…")

    check_cmd = (
        f"if not exist {GPU_REPO_PATH} ("
        f"  git clone {AUTORESEARCH_REMOTE} {GPU_REPO_PATH}"
        f")"
    )
    try:
        subprocess.run(
            ["ssh", *_SSH_OPTS, GPU_BOX, check_cmd],
            capture_output=True,
            text=True,
            timeout=SSH_TIMEOUT,
        )
    except Exception as exc:  # noqa: BLE001
        return SyncResult(ok=False, error=f"Bootstrap failed: {exc}")

    # After clone, install dev deps via uv sync --dev on the runner
    _progress("autoresearch", "→ Running uv sync --dev on GPU runner…")
    uv_cmd = f"cd {GPU_REPO_PATH} && uv sync --dev"
    try:
        subprocess.run(
            ["ssh", *_SSH_OPTS, GPU_BOX, uv_cmd],
            capture_output=True,
            text=True,
            timeout=SSH_TIMEOUT,
        )
        _progress("autoresearch", "✓ uv sync --dev complete")
    except Exception:
        _progress("autoresearch", "⚠ uv sync --dev failed (non-fatal — runner may lack uv)")

    return sync_autoresearch_idempotent()


# ── GPU lock helpers (read/write swarm_state.md on Mac) ───────────────────────

def read_swarm_state() -> SwarmState:
    """Parse swarm_state.md into a SwarmState dataclass.

    Returns a default IDLE state if the file does not exist yet.
    """
    if not SWARM_STATE_FILE.exists():
        return SwarmState()

    content = SWARM_STATE_FILE.read_text(encoding="utf-8")
    state = SwarmState()
    for line in content.splitlines():
        line = line.strip()
        if line.startswith("- GPU:"):
            state.gpu_status = line.split(":", 1)[1].strip()
        elif line.startswith("val_bpb:"):
            try:
                state.baseline_val_bpb = float(line.split(":", 1)[1].strip())
            except ValueError:
                pass
        elif line.startswith("git_sha:"):
            state.baseline_sha = line.split(":", 1)[1].strip()
    return state


def is_gpu_idle() -> bool:
    """Return True if swarm_state.md reports GPU: IDLE."""
    return read_swarm_state().gpu_status.upper() == "IDLE"


# ── deploy train.py to runner ─────────────────────────────────────────────────

def deploy_train_py() -> bool:
    """Copy the locally edited train.py to the Windows GPU runner via scp."""
    local_train = LOCAL_REPO_PATH / "train.py"
    if not local_train.exists():
        return False
    result = subprocess.run(
        ["scp", *_SSH_OPTS, str(local_train),
         f"{GPU_BOX}:{GPU_REPO_PATH}/train.py"],
        capture_output=True, text=True, timeout=SSH_TIMEOUT,
    )
    return result.returncode == 0


# ── dispatch training run on GPU runner ───────────────────────────────────────

def run_experiment_on_gpu() -> bool:
    """SSH into Windows runner and execute train.py via uv run.

    HARDWARE GUARD: caller MUST check is_gpu_idle() before calling this.
    Windows model loading is strictly sequential — never dispatch while BUSY.
    """
    cmd = (
        f"cd {GPU_REPO_PATH} && "
        "uv run train.py > run.log 2>&1"
    )
    result = subprocess.run(
        ["ssh", *_SSH_OPTS, GPU_BOX, cmd],
        capture_output=True, text=True,
        timeout=400,
    )
    return result.returncode == 0


# ── fetch run.log back to Mac ─────────────────────────────────────────────────

def fetch_run_log() -> bool:
    """Copy run.log from the Windows runner to the local Mac repo dir via scp."""
    result = subprocess.run(
        ["scp", *_SSH_OPTS,
         f"{GPU_BOX}:{GPU_REPO_PATH}/run.log",
         str(LOCAL_REPO_PATH / "log.txt")],
        capture_output=True, text=True, timeout=SSH_TIMEOUT,
    )
    return result.returncode == 0


# ── swarm_state.md initialiser ────────────────────────────────────────────────

def init_swarm_state(run_tag: str) -> None:
    """Write a fresh swarm_state.md into the local autoresearch repo."""
    content = textwrap.dedent(f"""\
        # Swarm State — {run_tag}
        <!-- Managed by Perplexity-Tools autoresearch_bridge.py -->
        <!-- DO NOT commit this file; it is ephemeral session state. -->

        ## Current Baseline
        val_bpb: TBD
        git_sha: TBD

        ## Orchestrator Directives
        - Establish baseline: run train.py as-is for the first experiment.

        ## Evaluator Findings
        - (none yet)

        ## Status
        - GPU: IDLE
        <!-- IDLE = safe to dispatch. BUSY = Coder has an active run. -->
        <!-- Only the Coder agent may flip IDLE → BUSY and back. -->
        <!-- HARDWARE GUARD: Windows loads ONE model at a time — never dispatch while BUSY. -->
    """)
    SWARM_STATE_FILE.write_text(content, encoding="utf-8")


# ── convenience: full pre-run checklist ───────────────────────────────────────

def preflight(run_tag: Optional[str] = None) -> dict:
    """Run the full pre-flight sequence before starting an autoresearch session.

    Steps (all idempotent):
    1. Install the uditgoenka/autoresearch Claude Code plugin.
    2. Bootstrap / sync autoresearch on GPU runner (secondary/verify substrate).
    3. Initialise swarm_state.md on Mac (only if run_tag supplied and file absent).

    Returns a dict with keys: plugin_ok, sync_ok, sha, swarm_state_initialised.
    """
    plugin = install_autoresearch_plugin()
    sync   = bootstrap_autoresearch_on_runner()
    initialised = False
    if run_tag and not SWARM_STATE_FILE.exists():
        init_swarm_state(run_tag)
        initialised = True
    return {
        "plugin_ok":              plugin.ok,
        "plugin_error":           plugin.error,
        "sync_ok":                sync.ok,
        "sha":                    sync.sha,
        "error":                  sync.error,
        "swarm_state_initialised": initialised,
    }
