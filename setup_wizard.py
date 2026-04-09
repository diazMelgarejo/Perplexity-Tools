#!/usr/bin/env python3
"""
setup_wizard.py
---------------
Idempotent installation wizard for Perplexity-Tools multi-agent orchestration.

Step sequence:
  [0/5] Perplexity API credentials   (NEW — key gate, validate + save)
  [1/5] Scan for existing AI software
  [2/5] Hardware profile
  [2.5] AlphaClaw gateway            (NEW — detect / install / start / wait)
  [3/5] Recommended install path
  [4/5] Python dependencies
  [5/5] .env config

Usage:
    python setup_wizard.py              # guided installation
    python setup_wizard.py --skip-scan  # skip existing software detection
    python setup_wizard.py --advanced   # show advanced options first
"""
from __future__ import annotations

import os
import sys
import shutil
import platform
import subprocess
import argparse
import asyncio
from pathlib import Path


# ---------------------------------------------------------------------------
# Shared key validation (delegate to orchestrator/key_helper.py)
# ---------------------------------------------------------------------------

def _test_perplexity_key(key: str) -> bool:
    """Validate a Perplexity API key via a cheap sonar ping."""
    try:
        from orchestrator.key_helper import test_perplexity_key
        return test_perplexity_key(key)
    except ImportError:
        # openai may not yet be installed at wizard time — do a raw HTTP check
        try:
            import urllib.request
            import json as _json
            body = _json.dumps({
                "model": "sonar",
                "messages": [{"role": "user", "content": "ping"}],
                "max_tokens": 1,
            }).encode()
            req = urllib.request.Request(
                "https://api.perplexity.ai/chat/completions",
                data=body,
                headers={
                    "Authorization": f"Bearer {key.strip()}",
                    "Content-Type": "application/json",
                },
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=8) as resp:
                return resp.status < 400
        except Exception:
            return False


def _resolve_perplexity_key() -> str | None:
    """Run shared Perplexity onboarding. Returns key or None."""
    from orchestrator.perplexity_client import ensure_credentials

    status = ensure_credentials(
        validate=True,
        interactive=True,
        allow_web_fallback=True,
    )
    if status["ready_for_api"]:
        print("  \u2713 Perplexity API key validated and ready for runtime calls.")
        return os.getenv("PERPLEXITY_API_KEY", "").strip() or None
    if status["auth_mode"] == "web-login":
        print("  \u2713 Web-login fallback recorded.")
        print("    Programmatic Perplexity calls will stay disabled until an API key is added.")
        return None
    print(f"  \u26a0 {status['message']}")
    return None


# ---------------------------------------------------------------------------
# AlphaClaw lifecycle helpers (step 2.5)
# ---------------------------------------------------------------------------

def detect_alphaclaw() -> tuple[bool, bool]:
    """Return (installed, gateway_running)."""
    import socket

    installed = bool(shutil.which("alphaclaw"))
    if not installed:
        nm = Path(os.getenv("ALPHACLAW_INSTALL_DIR",
                             str(Path.home() / ".alphaclaw"))) / \
             "node_modules" / "@chrysb" / "alphaclaw"
        installed = nm.exists()

    gateway_running = False
    port = int(os.getenv("OPENCLAW_GATEWAY_PORT", "18789"))
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=1):
            gateway_running = True
    except Exception:
        pass

    return installed, gateway_running


def _run_alphaclaw_lifecycle() -> None:
    """Resolve PT routing, then run the shared AlphaClaw/OpenClaw reconciler."""
    print("\n[2.5/5] AlphaClaw gateway\u2026\n")
    installed, running = detect_alphaclaw()

    if running:
        port = os.getenv("OPENCLAW_GATEWAY_PORT", "18789")
        print(f"  \u2713 alphaclaw found + gateway responding on :{port}")
        return

    try:
        from orchestrator.control_plane import resolve_routing_state, reconcile_gateway

        routing = asyncio.run(resolve_routing_state())
        print(
            "  \u2192 Routing resolved "
            f"(manager={routing['manager_backend']}, coder={routing['coder_backend']})"
        )
        result = asyncio.run(reconcile_gateway(force=False))
        if result.get("ok"):
            print(
                "  \u2713 Gateway reconciled "
                f"({result.get('gateway_url') or 'not yet reachable'})"
            )
            role_routing = result.get("role_routing") or {}
            if role_routing:
                print(
                    "    Topology: "
                    f"{role_routing.get('topology', 'unknown')} "
                    f"| manager={role_routing.get('manager', {}).get('model', 'n/a')} "
                    f"| researcher={role_routing.get('researcher', {}).get('model', 'n/a')}"
                )
            return
        print(
            "  \u26a0 Shared gateway reconciler reported failure "
            f"\u2014 {result.get('error', 'unknown error')}"
        )
    except Exception as e:
        print(f"  \u26a0 Shared gateway reconciler failed: {e}")

    if not installed:
        ans = input("  \u2192 alphaclaw not found. Install now? [Y/n]: ").strip().lower()
        if ans == "n":
            print("  \u26a0 Skipping AlphaClaw install.")
            return
        install_dir = Path(os.getenv("ALPHACLAW_INSTALL_DIR",
                                      str(Path.home() / ".alphaclaw")))
        install_dir.mkdir(parents=True, exist_ok=True)
        print(f"  \u2192 npm install @chrysb/alphaclaw into {install_dir}\u2026")
        try:
            subprocess.run(
                ["npm", "install", "@chrysb/alphaclaw"],
                cwd=str(install_dir),
                check=True,
            )
            print("  \u2713 @chrysb/alphaclaw installed")
        except subprocess.CalledProcessError as e:
            print(f"  \u2717 install failed: {e}")
            return

    # Start gateway
    print("  \u2192 Starting AlphaClaw gateway\u2026")
    install_dir = Path(os.getenv("ALPHACLAW_INSTALL_DIR",
                                  str(Path.home() / ".alphaclaw")))
    npx_bin = shutil.which("npx") or "npx"
    subprocess.Popen(
        [npx_bin, "alphaclaw", "start"],
        cwd=str(install_dir),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    # Poll /health with ASCII progress bar using the shared bootstrap helper.
    try:
        from alphaclaw_bootstrap import _wait_for_gateway
        port = int(os.getenv("OPENCLAW_GATEWAY_PORT", "18789"))
        ok = asyncio.run(_wait_for_gateway(f"http://127.0.0.1:{port}", timeout=30))
        if not ok:
            print("  \u26a0 Gateway did not respond in 30 s \u2014 continuing.")
    except Exception as e:
        print(f"  \u26a0 Health-check skipped: {e}")


# ---------------------------------------------------------------------------
# Existing detection helpers
# ---------------------------------------------------------------------------

def check_command(cmd: str) -> bool:
    return shutil.which(cmd) is not None


def detect_ollama() -> tuple[bool, str | None]:
    if check_command("ollama"):
        try:
            result = subprocess.run(
                ["ollama", "--version"], capture_output=True, text=True, timeout=5
            )
            if result.returncode == 0:
                return True, result.stdout.strip()
        except Exception:
            pass
    return False, None


def detect_lm_studio() -> bool:
    if platform.system() == "Darwin":
        return Path("/Applications/LM Studio.app").exists()
    return False


def detect_mlx() -> bool:
    if platform.system() != "Darwin":
        return False
    try:
        import mlx  # noqa: F401
        return True
    except ImportError:
        return False


def detect_python_env() -> dict:
    py_version = (
        f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"
    )
    in_venv = hasattr(sys, "real_prefix") or (
        hasattr(sys, "base_prefix") and sys.base_prefix != sys.prefix
    )
    return {"version": py_version, "in_venv": in_venv, "executable": sys.executable}


def detect_hardware_profile() -> str:
    system = platform.system()
    machine = platform.machine()
    if system == "Darwin" and machine == "arm64":
        return "mac-studio"
    if system == "Windows":
        try:
            result = subprocess.run(
                ["nvidia-smi", "--query-gpu=name", "--format=csv,noheader"],
                capture_output=True, text=True, timeout=5,
            )
            if "RTX 3080" in result.stdout:
                return "win-rtx3080"
        except Exception:
            pass
        return "win-generic"
    return "unknown"


# ---------------------------------------------------------------------------
# Main wizard flow
# ---------------------------------------------------------------------------

def run_wizard(args: argparse.Namespace) -> None:
    print("\n" + "=" * 60)
    print("    Perplexity-Tools Setup Wizard")
    print("    Idempotent Hardware-Aware Installation")
    print("=" * 60 + "\n")

    # [0/5] Perplexity API credentials (NEW)
    print("[0/5] Perplexity API credentials\u2026\n")
    _resolve_perplexity_key()
    print()

    # [1/5] Detect existing software
    if not args.skip_scan:
        print("[1/5] Scanning for existing AI software...\n")
        ollama_exists, ollama_ver = detect_ollama()
        lm_studio_exists = detect_lm_studio()
        mlx_exists = detect_mlx()
        py_env = detect_python_env()
        ollama_status = "\u2713 " + ollama_ver if ollama_exists else "\u2717 not found"
        lm_studio_status = "\u2713 detected" if lm_studio_exists else "\u2717 not found"
        mlx_status = "\u2713 installed" if mlx_exists else "\u2717 not installed"
        print(f"  Python:     {py_env['version']} {'(venv)' if py_env['in_venv'] else '(system)'}")
        print(f"  Ollama:     {ollama_status}")
        print(f"  LM Studio:  {lm_studio_status}")
        print(f"  MLX:        {mlx_status}")
        print()
    else:
        lm_studio_exists = False
        ollama_exists = False

    # [2/5] Hardware profile
    print("[2/5] Detecting hardware profile...\n")
    profile = detect_hardware_profile()
    print(f"  Detected profile: {profile}")
    print(f"  See hardware/SKILL.md for profile details.\n")

    # [2.5] AlphaClaw lifecycle (NEW)
    _run_alphaclaw_lifecycle()
    print()

    # [3/5] Recommend installation path
    print("[3/5] Recommended installation path:\n")
    if args.advanced:
        print("  \u2192 Advanced mode: showing distributed setup first.")
        print()
    else:
        if profile == "mac-studio":
            if lm_studio_exists:
                print("  \u2713 LM Studio detected \u2014 this is the easiest path for 95% of Mac users.")
                print("    No additional installation needed!")
            elif ollama_exists:
                print("  \u2713 Ollama detected \u2014 excellent choice for Mac.")
                print("    No additional installation needed!")
            else:
                print("  \u2192 Priority 1 (Easiest): Install LM Studio")
                print("      Download: https://lmstudio.ai/")
                print()
                print("  Alternative: Install Ollama (terminal-based)")
                print("      curl -fsSL https://ollama.ai/install.sh | sh")
        elif profile == "win-rtx3080":
            if ollama_exists:
                print("  \u2713 Ollama detected on Windows.")
            else:
                print("  \u2192 Priority 1 (Easiest): Install Ollama for Windows")
                print("      Download: https://ollama.ai/download/windows")
        else:
            print("  \u2192 Install Ollama (cross-platform): https://ollama.ai/download")
        print()

    # Advanced distributed setup
    if args.advanced or input("Configure distributed multi-node setup? [y/N]: ").strip().lower() == "y":
        print("\n  \u26a0\ufe0f  Advanced: Distributed Mac + Windows Setup")
        print("     Caveats:")
        print("       - Requires both machines on same LAN")
        print("       - Windows must have Ollama + Qwen3.5-35B-A3B installed")
        print()
        print("     Next steps:")
        print("       1. On Windows: install Ollama, run:")
        print("          ollama pull frob/qwen3.5:35b-a3b-instruct-ud-q4_K_M")
        print("       2. On Mac: python agent_launcher.py --configure")
        print()

    # [4/5] Python dependencies
    print("[4/5] Python dependencies...\n")
    if Path("requirements.txt").exists():
        ans = input("  Install Python dependencies from requirements.txt? [Y/n]: ").strip().lower()
        if ans != "n":
            print("  Running: pip install -r requirements.txt")
            subprocess.run([sys.executable, "-m", "pip", "install", "-r", "requirements.txt"])
    else:
        print("  No requirements.txt found. Skipping.")
    print()

    # [5/5] .env config
    print("[5/5] Environment configuration...\n")
    env_example = Path(".env.example")
    env_file    = Path(".env")
    if env_example.exists() and not env_file.exists():
        ans = input("  Create .env from .env.example? [Y/n]: ").strip().lower()
        if ans != "n":
            shutil.copy(env_example, env_file)
            print(f"  \u2713 Created {env_file}")
            print("    Edit .env to customise settings (IPs, models, etc.)")
    elif env_file.exists():
        print("  \u2713 .env already exists.")
    print()

    print("=" * 60)
    print("  Setup complete!")
    print()
    print("  Next steps:")
    print("    1. Review hardware/SKILL.md for your hardware profile")
    print("    2. Run: python agent_launcher.py")
    print("    3. Test Perplexity: python scripts/test_perplexity.py")
    print("    4. Test orchestration: python -m orchestrator.cli")
    print("=" * 60 + "\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Idempotent installation wizard for Perplexity-Tools"
    )
    parser.add_argument("--skip-scan", action="store_true",
                        help="Skip scanning for existing software")
    parser.add_argument("--advanced", action="store_true",
                        help="Show advanced distributed setup options first")
    args = parser.parse_args()
    run_wizard(args)
