#!/usr/bin/env python3
"""
setup_wizard.py
---------------
Idempotent installation wizard for Perplexity-Tools multi-agent orchestration.

Detects existing AI software (Ollama, LM Studio, MLX, Python env) and reuses
it without redundant installations. Guides users through hardware-aware setup
with tiered recommendations:
  Priority 1 (Entry): Easiest path for beginners (Ollama on Mac, LM Studio)
  Priority 2 (Advanced): Distributed multi-node setup with explicit caveats

Usage:
    python setup_wizard.py              # guided installation
    python setup_wizard.py --skip-scan  # skip existing software detection
    python setup_wizard.py --advanced   # show advanced options first

References:
    hardware/SKILL.md        - hardware profiles and role matrix
    agent_launcher.py        - hardware detection and routing
    .env.example             - environment variable template
"""

import os
import sys
import shutil
import platform
import subprocess
import argparse
from pathlib import Path


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
                version = result.stdout.strip()
                return True, version
        except Exception:
            pass
    return False, None


def detect_lm_studio() -> bool:
    """Detect LM Studio installation on macOS."""
    if platform.system() == "Darwin":
        app_path = Path("/Applications/LM Studio.app")
        return app_path.exists()
    # Windows / Linux detection can be added as needed
    return False


def detect_mlx() -> bool:
    """Detect MLX Python package (Apple Silicon only)."""
    if platform.system() != "Darwin":
        return False
    try:
        import mlx
        return True
    except ImportError:
        return False


def detect_python_env() -> dict:
    """Detect Python version and virtual env status."""
    py_version = f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"
    in_venv = hasattr(sys, 'real_prefix') or (
        hasattr(sys, 'base_prefix') and sys.base_prefix != sys.prefix
    )
    return {
        "version": py_version,
        "in_venv": in_venv,
        "executable": sys.executable,
    }


def detect_hardware_profile() -> str:
    """Auto-detect hardware profile from hardware/SKILL.md."""
    system = platform.system()
    machine = platform.machine()

    # Apple Silicon detection
    if system == "Darwin" and machine == "arm64":
        return "mac-studio"  # covers Mac Mini / Studio / MBP M-series

    # Windows with NVIDIA GPU (check later via nvidia-smi)
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
# Main wizard flow
# ---------------------------------------------------------------------------

def run_wizard(args: argparse.Namespace) -> None:
    print("\n" + "="*60)
    print("    Perplexity-Tools Setup Wizard")
    print("    Idempotent Hardware-Aware Installation")
    print("="*60 + "\n")

    # 1. Detect existing software
    if not args.skip_scan:
        print("[1/5] Scanning for existing AI software...\n")

        ollama_exists, ollama_ver = detect_ollama()
        lm_studio_exists = detect_lm_studio()
        mlx_exists = detect_mlx()
        py_env = detect_python_env()

        print(f"  Python:     {py_env['version']} {'(venv)' if py_env['in_venv'] else '(system)'}")
        print(f"  Ollama:     {'✓ ' + ollama_ver if ollama_exists else '✗ not found'}")
        print(f"  LM Studio:  {'✓ detected' if lm_studio_exists else '✗ not found'}")
        print(f"  MLX:        {'✓ installed' if mlx_exists else '✗ not installed'}")
        print()

    # 2. Detect hardware profile
    print("[2/5] Detecting hardware profile...\n")
    profile = detect_hardware_profile()
    print(f"  Detected profile: {profile}")
    print(f"  See hardware/SKILL.md for profile details.\n")

    # 3. Recommend installation path
    print("[3/5] Recommended installation path:\n")

    if args.advanced:
        print("  → Advanced mode: showing distributed setup first.")
        print()
    else:
        # Priority 1: Easiest path
        if profile == "mac-studio":
            if lm_studio_exists:
                print("  ✓ LM Studio detected — this is the easiest path for 95% of Mac users.")
                print("    No additional installation needed!")
            elif ollama_exists:
                print("  ✓ Ollama detected — excellent choice for Mac.")
                print("    No additional installation needed!")
            else:
                print("  → Priority 1 (Easiest): Install LM Studio")
                print("      Download: https://lmstudio.ai/")
                print("      — GUI-based, no terminal required")
                print("      — Optimized for Apple Silicon (MLX backend)")
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

    # 4. Advanced: distributed setup
    if args.advanced or input("Configure distributed multi-node setup? [y/N]: ").strip().lower() == "y":
        print("\n  ⚠️  Advanced: Distributed Mac + Windows Setup")
        print("     Caveats:")
        print("       - Requires both machines on same LAN")
        print("       - Windows must have Ollama + Qwen3.5-35B-A3B installed")
        print("       - Network latency may add overhead")
        print()
        print("     Next steps:")
        print("       1. On Windows: install Ollama, run:")
        print("          ollama pull frob/qwen3.5:35b-a3b-instruct-ud-q4_K_M")
        print("          ollama create qwen3.5-35b-a3b-win -f hardware/Modelfile.win-rtx3080")
        print("       2. On Mac: run agent_launcher.py to configure IPs")
        print("          python agent_launcher.py --configure")
        print()

    # 5. Install Python dependencies
    print("[4/5] Python dependencies...\n")
    requirements_exist = Path("requirements.txt").exists()
    if requirements_exist:
        install_deps = input("  Install Python dependencies from requirements.txt? [Y/n]: ").strip().lower()
        if install_deps != "n":
            print("  Running: pip install -r requirements.txt")
            subprocess.run([sys.executable, "-m", "pip", "install", "-r", "requirements.txt"])
    else:
        print("  No requirements.txt found. Skipping.")
    print()

    # 6. Finalize: create .env from .env.example
    print("[5/5] Environment configuration...\n")
    env_example = Path(".env.example")
    env_file = Path(".env")
    if env_example.exists() and not env_file.exists():
        create_env = input("  Create .env from .env.example? [Y/n]: ").strip().lower()
        if create_env != "n":
            shutil.copy(env_example, env_file)
            print(f"  ✓ Created {env_file}")
            print("    Edit .env to customize settings (IPs, models, etc.)")
    elif env_file.exists():
        print("  ✓ .env already exists.")
    print()

    # Done
    print("="*60)
    print("  Setup complete!")
    print()
    print("  Next steps:")
    print("    1. Review hardware/SKILL.md for your hardware profile")
    print("    2. Run: python agent_launcher.py")
    print("    3. Test orchestration: python -m orchestrator.cli")
    print("="*60 + "\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Idempotent installation wizard for Perplexity-Tools"
    )
    parser.add_argument(
        "--skip-scan",
        action="store_true",
        help="Skip scanning for existing software"
    )
    parser.add_argument(
        "--advanced",
        action="store_true",
        help="Show advanced distributed setup options first"
    )
    args = parser.parse_args()
    run_wizard(args)
