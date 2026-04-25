#!/usr/bin/env python3
"""
setup_wizard.py
---------------
Idempotent installation wizard for Perpetua-Tools multi-agent orchestration.

Detects existing AI software (Ollama, LM Studio, MLX, Python env) and reuses
it without redundant installations. Guides users through hardware-aware setup
with tiered recommendations:
  Priority 1 (Entry): Easiest path for beginners (Ollama on Mac, LM Studio)
  Priority 2 (Advanced): Distributed multi-node setup with explicit caveats

Step ordering (per approved plan):
  [0/5] Perplexity API credentials (key gate — required before anything else)
  [1/5] Scan for existing AI software + AlphaClaw gateway
  [2/5] Hardware profile detection
  [3/5] Recommended installation path
  [4/5] Python dependencies (via uv when available)
  [5/5] Environment configuration (.env)

Usage:
    python setup_wizard.py              # guided installation
    python setup_wizard.py --skip-scan  # skip existing software detection
    python setup_wizard.py --advanced   # show advanced options first

References:
    hardware/SKILL.md        - hardware profiles and role matrix
    agent_launcher.py        - hardware detection and routing
    .env.example             - environment variable template
    orchestrator/key_helper.py - shared Perplexity key validation
"""

import asyncio
import os
import platform
import shutil
import subprocess
import sys
import urllib.request
import argparse
from pathlib import Path

# ── env / key paths ───────────────────────────────────────────────────────────

_REPO_ROOT = Path(__file__).resolve().parent
ENV_PATH   = _REPO_ROOT / ".env"

try:
    from dotenv import load_dotenv, set_key as _set_key
    load_dotenv(ENV_PATH)
except ImportError:
    def load_dotenv(*a, **k): pass  # type: ignore[misc]
    def _set_key(*a, **k): pass     # type: ignore[misc]


# ---------------------------------------------------------------------------
# Helpers: detect existing installations
# ---------------------------------------------------------------------------

def check_command(cmd: str) -> bool:
    """Return True if the command is in PATH."""
    return shutil.which(cmd) is not None


def detect_ollama() -> tuple[bool, str | None]:
    """Detect Ollama installation. Return (exists, version)."""
    if check_command("ollama"):
        try:
            result = subprocess.run(
                ["ollama", "--version"],
                capture_output=True, text=True, timeout=5
            )
            if result.returncode == 0:
                return True, result.stdout.strip()
        except Exception:
            pass
    return False, None


def detect_lm_studio() -> bool:
    """Detect LM Studio installation on macOS."""
    if platform.system() == "Darwin":
        return Path("/Applications/LM Studio.app").exists()
    return False


def detect_mlx() -> bool:
    """Detect MLX Python package (Apple Silicon only)."""
    if platform.system() != "Darwin":
        return False
    try:
        import mlx  # noqa: F401
        return True
    except ImportError:
        return False


def detect_python_env() -> dict:
    """Detect Python version and virtual env status."""
    py_version = f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"
    in_venv = hasattr(sys, "real_prefix") or (
        hasattr(sys, "base_prefix") and sys.base_prefix != sys.prefix
    )
    return {"version": py_version, "in_venv": in_venv, "executable": sys.executable}


def detect_hardware_profile() -> str:
    """Auto-detect hardware profile."""
    system  = platform.system()
    machine = platform.machine()
    if system == "Darwin" and machine == "arm64":
        return "mac-studio"
    if system == "Windows":
        try:
            result = subprocess.run(
                ["nvidia-smi", "--query-gpu=name", "--format=csv,noheader"],
                capture_output=True, text=True, timeout=5
            )
            if "RTX 3080" in result.stdout:
                return "win-rtx3080"
        except Exception:
            pass
        return "win-generic"
    return "unknown"


# ---------------------------------------------------------------------------
# Step 0: Perplexity API credentials
# ---------------------------------------------------------------------------

def _test_perplexity_key(key: str) -> bool:
    """Validate key with a real sonar ping. Imports from key_helper if available."""
    try:
        from orchestrator.key_helper import test_perplexity_key
        return test_perplexity_key(key)
    except ImportError:
        pass
    # Inline fallback (no orchestrator package yet during first-time setup)
    if not key or not key.startswith("pplx-"):
        return False
    try:
        from openai import OpenAI
        client = OpenAI(api_key=key, base_url="https://api.perplexity.ai", timeout=8)
        r = client.chat.completions.create(
            model="sonar", messages=[{"role": "user", "content": "ping"}], max_tokens=1)
        return bool(r.choices)
    except Exception:
        return False


def _resolve_perplexity_key() -> str | None:
    """
    Step 0: ensure a valid PERPLEXITY_API_KEY is saved to .env before setup continues.

    Flow:
      1. Check env / .env — validate if present.
      2. If missing or invalid, prompt interactively.
      3. Save via dotenv set_key() so future runs skip the prompt.
      4. Allow skipping (empty Enter) — cloud search will be disabled.
    """
    key = os.getenv("PERPLEXITY_API_KEY", "").strip()

    if key:
        print("  Validating saved PERPLEXITY_API_KEY…", end="", flush=True)
        if _test_perplexity_key(key):
            print(" ✓")
            return key
        print(" ✗  (key rejected — will prompt for a new one)")

    print("\n  No valid PERPLEXITY_API_KEY found.")
    print("  Get yours at: https://www.perplexity.ai/settings/api")
    print("  (Press Enter to skip — Perplexity cloud search will be disabled)\n")

    while True:
        raw = input("  Paste API key (starts with pplx-): ").strip()
        if not raw:
            print("  ⚠  Skipping Perplexity key. Cloud search disabled.\n")
            return None
        if not raw.startswith("pplx-"):
            print("  ✗  Key should start with 'pplx-'. Try again.\n")
            continue
        print("  Validating…", end="", flush=True)
        if _test_perplexity_key(raw):
            print(" ✓")
            try:
                ENV_PATH.touch(exist_ok=True)
                _set_key(str(ENV_PATH), "PERPLEXITY_API_KEY", raw)
                print(f"  ✓ Key saved to {ENV_PATH}\n")
            except Exception as exc:
                print(f"\n  ⚠  Could not save key to .env: {exc}\n")
            return raw
        print(" ✗  Key not accepted. Check it and try again.\n")


# ---------------------------------------------------------------------------
# Step 1.5: AlphaClaw gateway detection + lifecycle
# ---------------------------------------------------------------------------

def _probe_gateway_sync(port: int = 18789) -> bool:
    """Synchronous probe: return True if any AlphaClaw-compatible endpoint responds."""
    candidate_ports = [
        int(os.getenv("OPENCLAW_GATEWAY_PORT", str(port))),
        11435, 8080, 3000, 4000, 9000,
    ]
    for p in dict.fromkeys(candidate_ports):
        for path in ("/health", "/v1/models"):
            try:
                urllib.request.urlopen(
                    f"http://127.0.0.1:{p}{path}", timeout=1
                )
                return True
            except Exception:
                pass
    return False


def detect_alphaclaw() -> tuple[bool, bool]:
    """Return (installed, gateway_running)."""
    install_dir = Path(os.getenv("ALPHACLAW_INSTALL_DIR",
                                 str(Path.home() / ".alphaclaw")))
    installed = (
        check_command("alphaclaw")
        or (install_dir / "node_modules" / "@chrysb" / "alphaclaw").exists()
    )
    running = _probe_gateway_sync()
    return installed, running


def _install_alphaclaw_interactive() -> bool:
    """Install @chrysb/alphaclaw and start the gateway. Returns True on success."""
    install_dir = Path(os.getenv("ALPHACLAW_INSTALL_DIR",
                                 str(Path.home() / ".alphaclaw")))
    install_dir.mkdir(parents=True, exist_ok=True)

    bootstrap = _REPO_ROOT / "alphaclaw_bootstrap.py"
    if bootstrap.exists():
        print("  Running alphaclaw_bootstrap.py --bootstrap…\n")
        result = subprocess.run(
            [sys.executable, str(bootstrap), "--bootstrap"],
        )
        return result.returncode == 0

    # Fallback: bare npm install + npx start (no progress bar)
    if not check_command("npm"):
        print("  ✗ npm not found — install Node.js from https://nodejs.org/")
        return False
    print("  Installing @chrysb/alphaclaw…")
    try:
        subprocess.run(["npm", "install", "@chrysb/alphaclaw"],
                       check=True, cwd=str(install_dir))
    except subprocess.CalledProcessError:
        print("  ✗ npm install failed.")
        return False
    print("  Starting AlphaClaw gateway (npx alphaclaw start)…")
    subprocess.Popen(["npx", "alphaclaw", "start"], cwd=str(install_dir))
    return True


# ---------------------------------------------------------------------------
# Main wizard flow
# ---------------------------------------------------------------------------

def run_wizard(args: argparse.Namespace) -> None:
    print("\n" + "=" * 60)
    print("    Perpetua-Tools Setup Wizard")
    print("    Idempotent Hardware-Aware Installation")
    print("=" * 60 + "\n")

    # ── Step 0: Perplexity API credentials ───────────────────────────────────
    print("[0/5] Perplexity API credentials…\n")
    pplx_key = _resolve_perplexity_key()
    if pplx_key:
        print(f"  ✓ PERPLEXITY_API_KEY active (sonar validated)\n")
    else:
        print("  ⚠  Continuing without Perplexity — cloud search features disabled.\n")

    # ── Step 1: Scan for existing AI software + AlphaClaw ────────────────────
    ollama_exists = ollama_ver = None
    lm_studio_exists = mlx_exists = False

    if not args.skip_scan:
        print("[1/5] Scanning for existing AI software…\n")

        ollama_exists, ollama_ver = detect_ollama()
        lm_studio_exists = detect_lm_studio()
        mlx_exists = detect_mlx()
        py_env = detect_python_env()
        alphaclaw_installed, alphaclaw_running = detect_alphaclaw()

        print(f"  Python:     {py_env['version']} "
              f"{'(venv)' if py_env['in_venv'] else '(system)'}")
        print(f"  Ollama:     {'✓ ' + ollama_ver if ollama_exists else '✗ not found'}")
        print(f"  LM Studio:  {'✓ detected' if lm_studio_exists else '✗ not found'}")
        print(f"  MLX:        {'✓ installed' if mlx_exists else '✗ not installed'}")
        print(f"  AlphaClaw:  "
              f"{'✓ installed' if alphaclaw_installed else '✗ not installed'}"
              f"{' + gateway ✓' if alphaclaw_running else ''}")
        print()

        # AlphaClaw lifecycle
        if not alphaclaw_installed:
            ans = input("  AlphaClaw not found. Install @chrysb/alphaclaw now? [Y/n]: ").strip()
            if ans.lower() != "n":
                ok = _install_alphaclaw_interactive()
                print(f"  {'✓ AlphaClaw ready' if ok else '✗ AlphaClaw setup failed (non-fatal)'}\n")
        elif not alphaclaw_running:
            ans = input("  AlphaClaw installed but gateway not running. Start now? [Y/n]: ").strip()
            if ans.lower() != "n":
                bootstrap = _REPO_ROOT / "alphaclaw_bootstrap.py"
                if bootstrap.exists():
                    subprocess.run([sys.executable, str(bootstrap), "--bootstrap"])
                else:
                    install_dir = Path(os.getenv("ALPHACLAW_INSTALL_DIR",
                                                  str(Path.home() / ".alphaclaw")))
                    subprocess.Popen(["npx", "alphaclaw", "start"],
                                     cwd=str(install_dir))
                print()
        else:
            print("  ✓ AlphaClaw gateway is running — no action needed.\n")
    else:
        py_env = detect_python_env()

    # ── Step 2: Hardware profile ──────────────────────────────────────────────
    print("[2/5] Detecting hardware profile…\n")
    profile = detect_hardware_profile()
    print(f"  Detected profile: {profile}")
    print(f"  See hardware/SKILL.md for profile details.\n")

    # ── Step 3: Recommend installation path ───────────────────────────────────
    print("[3/5] Recommended installation path:\n")

    if args.advanced:
        print("  → Advanced mode: showing distributed setup first.\n")
    else:
        if profile == "mac-studio":
            if lm_studio_exists:
                print("  ✓ LM Studio detected — easiest path for Mac users.")
                print("    No additional installation needed!")
            elif ollama_exists:
                print("  ✓ Ollama detected — excellent choice for Mac.")
                print("    No additional installation needed!")
            else:
                print("  → Priority 1 (Easiest): Install LM Studio")
                print("      Download: https://lmstudio.ai/")
                print("      — GUI-based, no terminal required")
                print("      — Optimised for Apple Silicon (MLX backend)")
                print()
                print("  Alternative: Install Ollama (terminal-based)")
                print("      curl -fsSL https://ollama.ai/install.sh | sh")
        elif profile == "win-rtx3080":
            if ollama_exists:
                print("  ✓ Ollama detected on Windows.")
            else:
                print("  → Priority 1 (Easiest): Install Ollama for Windows")
                print("      Download: https://ollama.ai/download/windows")
                print("      — RTX 3080 will be auto-detected for GPU acceleration")
        else:
            print("  → Install Ollama (cross-platform)")
            print("      https://ollama.ai/download")
        print()

    # Advanced distributed setup
    if args.advanced or input(
        "Configure distributed multi-node setup? [y/N]: "
    ).strip().lower() == "y":
        print("\n  ⚠  Advanced: Distributed Mac + Windows Setup")
        print("     Caveats:")
        print("       - Requires both machines on same LAN")
        print("       - Windows must have Ollama + Qwen3.5-35B-A3B installed")
        print("       - Valid Windows model: "
              "Qwen3.5-27B-Claude-4.6-Opus-Reasoning-Distilled-v2")
        print("       - Never load more than one model at a time on Windows")
        print()
        print("     Next steps:")
        print("       1. On Windows: install Ollama, run:")
        print("          ollama pull frob/qwen3.5:35b-a3b-instruct-ud-q4_K_M")
        print("          ollama create qwen3.5-35b-a3b-win -f hardware/Modelfile.win-rtx3080")
        print("       2. On Mac: run agent_launcher.py to configure IPs")
        print("          python agent_launcher.py --configure")
        print()

    # ── Step 4: Python dependencies ───────────────────────────────────────────
    print("[4/5] Python dependencies…\n")
    requirements_exist = (_REPO_ROOT / "requirements.txt").exists()
    pyproject_exists   = (_REPO_ROOT / "pyproject.toml").exists()

    if pyproject_exists and check_command("uv"):
        install_deps = input(
            "  Install via uv sync --dev? [Y/n]: "
        ).strip().lower()
        if install_deps != "n":
            print("  Running: uv sync --dev")
            subprocess.run(["uv", "sync", "--dev"], cwd=str(_REPO_ROOT))
    elif requirements_exist:
        install_deps = input(
            "  Install Python dependencies from requirements.txt? [Y/n]: "
        ).strip().lower()
        if install_deps != "n":
            print("  Running: pip install -r requirements.txt")
            subprocess.run([sys.executable, "-m", "pip", "install",
                            "-r", "requirements.txt"])
    else:
        print("  No requirements.txt found. Skipping.")
    print()

    # ── Step 5: Environment configuration ─────────────────────────────────────
    print("[5/5] Environment configuration…\n")
    env_example = _REPO_ROOT / ".env.example"
    if env_example.exists() and not ENV_PATH.exists():
        create_env = input(
            "  Create .env from .env.example? [Y/n]: "
        ).strip().lower()
        if create_env != "n":
            shutil.copy(env_example, ENV_PATH)
            print(f"  ✓ Created {ENV_PATH}")
            print("    Edit .env to customise settings (IPs, models, etc.)")
            if pplx_key:
                _set_key(str(ENV_PATH), "PERPLEXITY_API_KEY", pplx_key)
                print("  ✓ PERPLEXITY_API_KEY written to .env")
    elif ENV_PATH.exists():
        print("  ✓ .env already exists.")
    print()

    # Done
    print("=" * 60)
    print("  Setup complete!")
    print()
    print("  Next steps:")
    print("    1. Review hardware/SKILL.md for your hardware profile")
    print("    2. Run: python agent_launcher.py")
    print("    3. Test orchestration: python -m orchestrator.cli")
    print("    4. Smoke-test Perplexity: python scripts/test_perplexity.py")
    print("=" * 60 + "\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Idempotent installation wizard for Perpetua-Tools"
    )
    parser.add_argument(
        "--skip-scan", action="store_true",
        help="Skip scanning for existing software"
    )
    parser.add_argument(
        "--advanced", action="store_true",
        help="Show advanced distributed setup options first"
    )
    args = parser.parse_args()
    run_wizard(args)
