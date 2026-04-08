#!/usr/bin/env python3
"""
alphaclaw_bootstrap.py — Perplexity-Tools
------------------------------------------
Canonical AlphaClaw (@chrysb/alphaclaw) gateway install / commandeer / start
logic. ultrathink-system delegates to this script via PT_HOME env var.

Steps (all idempotent):
  0. Probe all candidate ports for any running OpenClaw-compatible gateway
     (commandeer if found — skip install and start).
  1. Verify npm is available.
  2. Install @chrysb/alphaclaw locally (npm install, no -g) if missing.
  3. Write ~/.openclaw/openclaw.json from PT routing.json + env defaults.
  4. Create agent workspaces from bin/agents/*/SOUL.md.
  5. Start gateway via: npx alphaclaw start
  6. Poll /health with ASCII progress bar (30 s timeout).
  7. Ensure ~/autoresearch is cloned and uv-synced.

Usage:
    python alphaclaw_bootstrap.py --bootstrap [--force]

Environment variables:
    PT_HOME               path to this repo (default: $HOME/Perplexity-Tools)
    UTS_HOME              path to ultrathink-system (fallback for bin/agents/)
    ALPHACLAW_INSTALL_DIR npm install target directory (default: $HOME/.alphaclaw)
    OPENCLAW_GATEWAY_PORT gateway port (default: 18789)
    OPENCLAW_EXTRA_PORTS  comma-separated additional ports to probe
    PT_AGENTS_STATE       path to .state/routing.json produced by agent_launcher
    MAC_IP / WIN_IP       LAN IPs (exported by start.sh)
    LM_STUDIO_*           LM Studio endpoints and token
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
OPENCLAW_GATEWAY_PORT = int(os.getenv("OPENCLAW_GATEWAY_PORT", "18789"))

_extra = [int(p) for p in os.getenv("OPENCLAW_EXTRA_PORTS", "").split(",") if p.strip()]
OPENCLAW_CANDIDATE_PORTS: list[int] = list(dict.fromkeys(
    [OPENCLAW_GATEWAY_PORT, 11435, 8080, 3000, 4000, 9000] + _extra
))

# SOUL source: prefer PT's own bin/agents/, fall back to UTS_HOME/bin/agents/
_UTS_HOME = os.getenv("UTS_HOME", str(Path.home() / "ultrathink-system"))
SOUL_SRC: Path = (
    SCRIPT_DIR / "bin" / "agents"
    if (SCRIPT_DIR / "bin" / "agents").is_dir()
    else Path(_UTS_HOME) / "bin" / "agents"
)

ALPHACLAW_INSTALL_DIR = Path(
    os.getenv("ALPHACLAW_INSTALL_DIR", str(Path.home() / ".alphaclaw"))
)

# env-var defaults (exported by start.sh)
MAC_IP     = os.getenv("MAC_IP",  "192.168.254.105")
WIN_IP     = os.getenv("WIN_IP",  "192.168.254.101")
OLLAMA_MAC = os.getenv("OLLAMA_MAC_ENDPOINT",    f"http://{MAC_IP}:11434")
OLLAMA_WIN = os.getenv("OLLAMA_WINDOWS_ENDPOINT", f"http://{WIN_IP}:11434")
LMS_MAC    = os.getenv("LM_STUDIO_MAC_ENDPOINT",  f"http://{MAC_IP}:1234")
LMS_WIN    = os.getenv("LM_STUDIO_WIN_ENDPOINTS",  f"http://{WIN_IP}:1234")
LMS_TOKEN  = os.getenv("LM_STUDIO_API_TOKEN", "lm-studio")
MAC_MODEL  = os.getenv("MAC_LMS_MODEL", "qwen3:8b-instruct")
WIN_MODEL  = os.getenv("WINDOWS_LMS_MODEL",
                        "Qwen3.5-27B-Claude-4.6-Opus-Reasoning-Distilled-v2")


# ── ASCII progress bar: poll /health after gateway start ─────────────────────

async def _wait_for_gateway(url: str, timeout: int = 30) -> bool:
    """Poll gateway /health with ASCII progress bar. Returns True when ready."""
    try:
        import httpx
    except ImportError:
        print("[alphaclaw] ⚠ httpx not installed — skipping health-check")
        return False

    bar_width = 38
    print(f"\n  [alphaclaw] Waiting for gateway at {url}\u2026")
    for elapsed in range(timeout + 1):
        filled = int(bar_width * elapsed / timeout)
        bar = "\u2588" * filled + "\u2591" * (bar_width - filled)
        pct = int(100 * elapsed / timeout)
        left = timeout - elapsed
        print(f"\r  [alphaclaw] [{bar}] {pct:3d}%  ({left:2d}s)  ",
              end="", flush=True)
        try:
            async with httpx.AsyncClient(timeout=1.0) as c:
                r = await c.get(f"{url}/health")
                if r.status_code < 400:
                    print(
                        f"\r  [alphaclaw] [{'\u2588' * bar_width}] 100%  "
                        "\u2713 ready          "
                    )
                    return True
        except Exception:
            pass
        if elapsed < timeout:
            await asyncio.sleep(1)
    print(
        f"\r  [alphaclaw] [{'\u2591' * bar_width}] timed out after {timeout}s           "
    )
    return False


# ── gateway discovery ─────────────────────────────────────────────────────────

async def _probe_url(url: str, client) -> bool:
    for path in ("/health", "/v1/models"):
        try:
            r = await client.get(f"{url.rstrip('/')}{path}")
            if r.status_code < 400:
                return True
        except Exception:
            pass
    return False


async def _find_any_gateway() -> str | None:
    """Probe all candidate ports. Returns base URL of first responsive gateway."""
    try:
        import httpx
    except ImportError:
        return None
    async with httpx.AsyncClient(timeout=1.5) as client:
        for port in OPENCLAW_CANDIDATE_PORTS:
            url = f"http://127.0.0.1:{port}"
            if await _probe_url(url, client):
                return url
    return None


def _is_alphaclaw_installed() -> bool:
    """Return True if alphaclaw binary or local node_modules package is present."""
    if shutil.which("alphaclaw"):
        return True
    nm = ALPHACLAW_INSTALL_DIR / "node_modules" / "@chrysb" / "alphaclaw"
    return nm.exists()


# ── config + workspaces ───────────────────────────────────────────────────────

def _load_pt_state() -> dict | None:
    state_path = os.getenv("PT_AGENTS_STATE")
    if state_path and Path(state_path).exists():
        with open(state_path) as f:
            return json.load(f)
    return None


def _lms_base_url(raw: str) -> str:
    raw = raw.rstrip("/")
    return raw if raw.endswith("/v1") else f"{raw}/v1"


def _write_openclaw_config(config_dir: Path, config_file: Path) -> None:
    pt = _load_pt_state()
    if pt:
        mac_lms_url   = pt.get("mac_lmstudio_endpoint") or LMS_MAC
        win_lms_url   = pt.get("lmstudio_endpoint")     or LMS_WIN
        coder_model   = pt.get("coder_model",   WIN_MODEL)
        manager_model = pt.get("manager_model", MAC_MODEL)
        coder_backend = pt.get("coder_backend", "mac-degraded")
        mac_lms_ok    = bool(pt.get("mac_lmstudio_ok"))
    else:
        mac_lms_url, win_lms_url = LMS_MAC, LMS_WIN
        coder_model, manager_model = WIN_MODEL, MAC_MODEL
        coder_backend, mac_lms_ok = "unknown", False

    if coder_backend == "windows-lmstudio":
        coder_primary = f"lmstudio-win/{coder_model}"
    elif coder_backend == "windows-ollama":
        coder_primary = f"ollama-win/{coder_model}"
    else:
        coder_primary = f"lmstudio-mac/{manager_model}"

    manager_primary = (
        f"lmstudio-mac/{manager_model}" if mac_lms_ok
        else f"ollama-mac/{manager_model}"
    )

    agents_root = str(Path.home() / ".openclaw" / "agents")
    config = {
        "gateway": {
            "mode": "local",
            "port": OPENCLAW_GATEWAY_PORT,
            "bind": "loopback",
            "commandeered": False,
        },
        "agents": {
            "defaults": {
                "model": {"primary": manager_primary},
                "workspace": f"{agents_root}/default",
            },
            "list": [
                {"id": "mac-researcher",
                 "model": {"primary": manager_primary},
                 "workspace": f"{agents_root}/mac-researcher"},
                {"id": "win-researcher",
                 "model": {"primary": coder_primary},
                 "workspace": f"{agents_root}/win-researcher"},
                {"id": "orchestrator",
                 "model": {"primary": manager_primary},
                 "workspace": f"{agents_root}/orchestrator"},
                {"id": "coder",
                 "model": {"primary": coder_primary},
                 "workspace": f"{agents_root}/coder"},
                {"id": "autoresearcher",
                 "model": {"primary": coder_primary},
                 "workspace": str(Path.home() / "autoresearch")},
            ],
        },
        "models": {
            "providers": {
                "lmstudio-mac": {
                    "baseUrl": _lms_base_url(mac_lms_url),
                    "apiKey": LMS_TOKEN,
                    "api": "openai-completions",
                    "models": [{"id": MAC_MODEL,
                                "name": f"Mac LMS \u2014 {MAC_MODEL}",
                                "contextWindow": 32768, "maxTokens": 8192,
                                "cost": {"input": 0, "output": 0}}],
                },
                "lmstudio-win": {
                    "baseUrl": _lms_base_url(win_lms_url),
                    "apiKey": LMS_TOKEN,
                    "api": "openai-completions",
                    "models": [{"id": WIN_MODEL,
                                "name": f"Win LMS \u2014 {WIN_MODEL}",
                                "contextWindow": 32768, "maxTokens": 8192,
                                "cost": {"input": 0, "output": 0}}],
                },
                "ollama-mac": {
                    "apiKey": "ollama-local",
                    "baseUrl": OLLAMA_MAC,
                    "api": "ollama",
                },
                "ollama-win": {
                    "apiKey": "ollama-remote",
                    "baseUrl": OLLAMA_WIN,
                    "api": "ollama",
                },
            },
        },
    }
    config_dir.mkdir(parents=True, exist_ok=True)
    config_file.write_text(json.dumps(config, indent=2), encoding="utf-8")
    print(
        f"[alphaclaw] \u2713 openclaw.json written \u2192 {config_file}"
        f"  (coder-backend={coder_backend})"
    )


def _ensure_agent_workspaces(config_dir: Path) -> None:
    agents_dir = config_dir / "agents"
    roles = ["mac-researcher", "win-researcher", "orchestrator", "coder", "autoresearcher"]
    for role in roles:
        role_dir = agents_dir / role
        role_dir.mkdir(parents=True, exist_ok=True)
        soul_file = role_dir / "SOUL.md"
        if soul_file.exists():
            continue
        src = SOUL_SRC / role / "SOUL.md"
        if src.exists():
            shutil.copy(src, soul_file)
            print(f"[alphaclaw] \u2713 agent workspace: {role}")
        else:
            print(f"[alphaclaw] \u26a0 missing source: bin/agents/{role}/SOUL.md")


def _ensure_autoresearch() -> None:
    """Idempotent clone + uv sync of ~/autoresearch."""
    repo = Path.home() / "autoresearch"
    if repo.exists():
        print("[alphaclaw] \u2713 ~/autoresearch already exists")
        return
    print("[alphaclaw] \u2192 Cloning karpathy/autoresearch\u2026")
    try:
        subprocess.run(
            ["git", "clone", "https://github.com/karpathy/autoresearch", str(repo)],
            check=True, capture_output=True,
        )
        subprocess.run(["pip", "install", "uv"], check=True, capture_output=True)
        subprocess.run(["uv", "sync"], cwd=repo, check=True, capture_output=True)
        print("[alphaclaw] \u2713 autoresearch ready")
    except subprocess.CalledProcessError as e:
        print(f"[alphaclaw] \u2717 autoresearch setup failed (non-fatal): {e}")


# ── main bootstrap ────────────────────────────────────────────────────────────

async def bootstrap_alphaclaw(force: bool = False) -> bool:
    """
    Idempotent AlphaClaw gateway bootstrap. Safe to call on every start.sh run.

    Steps 30 s apart maximum (or immediately when the previous one finishes).
    """
    try:
        import httpx  # noqa: F401
    except ImportError:
        print("[alphaclaw] \u2717 httpx not installed \u2014 run: pip install httpx")
        return False

    config_dir  = Path.home() / ".openclaw"
    config_file = config_dir  / "openclaw.json"

    # Step 0: commandeer any already-running compatible gateway
    print(
        f"[alphaclaw] \u2192 Probing {len(OPENCLAW_CANDIDATE_PORTS)} candidate ports:"
        f" {OPENCLAW_CANDIDATE_PORTS}"
    )
    existing_url = await _find_any_gateway()

    if existing_url:
        existing_port = int(existing_url.rsplit(":", 1)[-1])
        if existing_port != OPENCLAW_GATEWAY_PORT:
            print(
                f"[alphaclaw] \u2713 Found gateway at {existing_url}"
                f" (port :{existing_port}) \u2014 commandeering"
            )
        else:
            print(f"[alphaclaw] \u2713 Gateway already running at {existing_url} \u2014 commandeering")
        os.environ["OPENCLAW_GATEWAY_URL"] = existing_url
        if not config_file.exists() or force:
            _write_openclaw_config(config_dir, config_file)
        _ensure_agent_workspaces(config_dir)
        _ensure_autoresearch()
        return True

    print("[alphaclaw] No running gateway found \u2014 proceeding with full bootstrap")

    # Step 1: npm check
    if not shutil.which("npm"):
        print("[alphaclaw] \u2717 npm not found \u2014 install Node 20+ from https://nodejs.org/")
        return False

    # Step 2: install @chrysb/alphaclaw locally if missing
    if not _is_alphaclaw_installed():
        ALPHACLAW_INSTALL_DIR.mkdir(parents=True, exist_ok=True)
        print(
            f"[alphaclaw] \u2192 Installing @chrysb/alphaclaw into"
            f" {ALPHACLAW_INSTALL_DIR}\u2026"
        )
        try:
            # Stream output so user sees live npm progress
            subprocess.run(
                ["npm", "install", "@chrysb/alphaclaw"],
                cwd=str(ALPHACLAW_INSTALL_DIR),
                check=True,
            )
            print("[alphaclaw] \u2713 @chrysb/alphaclaw installed")
        except subprocess.CalledProcessError as e:
            print(f"[alphaclaw] \u2717 install failed: {e}")
            return False
    else:
        print("[alphaclaw] \u2713 @chrysb/alphaclaw already installed \u2014 skipping")

    # Step 3: write config
    if not config_file.exists() or force:
        _write_openclaw_config(config_dir, config_file)

    # Step 4: agent workspaces
    _ensure_agent_workspaces(config_dir)

    # Step 5: start gateway
    gateway_url = f"http://127.0.0.1:{OPENCLAW_GATEWAY_PORT}"
    print("[alphaclaw] \u2192 Starting AlphaClaw gateway\u2026")
    try:
        npx_bin = shutil.which("npx") or "npx"
        subprocess.Popen(
            [npx_bin, "alphaclaw", "start"],
            cwd=str(ALPHACLAW_INSTALL_DIR),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except Exception as e:
        print(f"[alphaclaw] \u2717 gateway start failed: {e}")
        return False

    # Step 6: poll /health with progress bar
    ready = await _wait_for_gateway(gateway_url, timeout=30)
    if not ready:
        print(
            "[alphaclaw] \u26a0 Gateway did not respond within 30 s "
            "\u2014 continuing anyway (non-fatal)"
        )
    else:
        os.environ["OPENCLAW_GATEWAY_URL"] = gateway_url

    # Step 7: autoresearch
    _ensure_autoresearch()
    return True


# ── CLI ───────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Perplexity-Tools AlphaClaw gateway bootstrap",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  python alphaclaw_bootstrap.py --bootstrap          # idempotent bootstrap\n"
            "  python alphaclaw_bootstrap.py --bootstrap --force  # force-rewrite config\n"
        ),
    )
    parser.add_argument("--bootstrap", action="store_true",
                        help="Idempotent AlphaClaw install + configure + start")
    parser.add_argument("--force", action="store_true",
                        help="Force-rewrite openclaw.json even if it already exists")
    _args = parser.parse_args()
    if _args.bootstrap:
        ok = asyncio.run(bootstrap_alphaclaw(force=_args.force))
        sys.exit(0 if ok else 1)
    else:
        parser.print_help()
        sys.exit(1)
