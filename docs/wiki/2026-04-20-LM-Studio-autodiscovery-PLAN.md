# LM Studio Auto-Discovery & Three-Repo Claude Code Automation — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` (recommended) or `superpowers:executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Auto-discover live LM Studio endpoints on every Claude Code session start, update all configs idempotently, and wire all three repos with hooks/skills/subagents — with full disaster recovery.

**Architecture:** Layer B (per-repo `discover-lm-studio.sh`) checks a 5-min gossip TTL; if stale, calls Layer A (`~/.openclaw/scripts/discover.py`) which probes live endpoints, hashes state, and only writes when something changed. `openclaw.json` is master; all repo `.env.lmstudio` files derive from it. Four recovery tiers ensure the system always has a valid config.

**Tech Stack:** Python 3.9+ stdlib only (no ruamel.yaml dep — YAML patched with `re`), bash, `gh` CLI for GitHub sync, `fcntl` file locking.

**Live endpoints confirmed:** Mac `192.168.254.107:1234` · Win `192.168.254.101:1234` — both serving 5 identical models via LM Link.

---

## File Map

```
CREATE (local)
~/.openclaw/scripts/discover.py             # Layer A hub — full discovery + patching
~/.openclaw/profiles/lan-full.json          # Tier 4 profile: both nodes
~/.openclaw/profiles/mac-only.json          # Tier 4 profile: Mac only
~/.openclaw/profiles/win-only.json          # Tier 4 profile: Win only

CREATE + PUSH (AlphaClaw feature/MacOS-post-install)
scripts/discover-lm-studio.sh               # Layer B shell gate
.claude/settings.json                       # hooks: SessionStart, PostToolUse(test+lock)
.claude/skills/macos-port-status/SKILL.md
.claude/skills/cherry-pick-down/SKILL.md
.claude/agents/upstream-compat-reviewer.md
AGENT_RESUME.md                             # future-agent handoff doc

CREATE + PUSH (Perpetua-Tools main)
scripts/discover-lm-studio.sh               # Layer B shell gate
.claude/skills/agent-run/SKILL.md
.claude/skills/model-routing-check/SKILL.md
.claude/agents/api-validator.md
AGENT_RESUME.md

CREATE + PUSH (orama-system main)
scripts/discover-lm-studio.sh               # Layer B shell gate
.claude/skills/ecc-sync/SKILL.md            # promoted from .claude/commands/ecc-sync.md
.claude/skills/agent-methodology/SKILL.md   # Claude-only
.claude/agents/crystallizer.md
AGENT_RESUME.md

MODIFY + PUSH (Perpetua-Tools main)
.claude/settings.json                       # add SessionStart(discover), PostToolUse(ruff+pytest)
config/devices.yml                          # lan_ip .103→.107, .100→.101
config/models.yml                           # host defaults updated
.gitignore                                  # add .env.lmstudio

MODIFY + PUSH (orama-system main)
.claude/settings.json                       # add SessionStart(discover), Stop(lessons check)
.gitignore                                  # add .env.lmstudio

MODIFY + PUSH (AlphaClaw feature/MacOS-post-install)
.gitignore                                  # add .env.lmstudio

MODIFY (local only — never committed)
~/.openclaw/openclaw.json                   # fix stale IPs: .147→.107, .108→.101
```

---

## Task 1: Write tests for discover.py (TDD)

**Files:**
- Create: `~/.openclaw/scripts/tests/test_discover.py`

- [ ] **Step 1.1: Create test file**

```python
# ~/.openclaw/scripts/tests/test_discover.py
import json, sys, time
from datetime import datetime, timezone, timedelta
from pathlib import Path
import pytest

sys.path.insert(0, str(Path.home() / ".openclaw/scripts"))
import discover as D


# ── compute_hash ──────────────────────────────────────────────────────────────

def test_hash_deterministic():
    ep = {"mac": {"ip": "127.0.0.1", "models": ["m1", "m2"]},
          "win": {"ip": "192.168.254.101", "models": ["m3"]}}
    assert D.compute_hash(ep) == D.compute_hash(ep)

def test_hash_changes_on_ip_change():
    ep1 = {"mac": {"ip": "127.0.0.1", "models": ["m1"]}, "win": None}
    ep2 = {"mac": {"ip": "192.168.254.107", "models": ["m1"]}, "win": None}
    assert D.compute_hash(ep1) != D.compute_hash(ep2)

def test_hash_model_order_independent():
    ep1 = {"mac": {"ip": "x", "models": ["b", "a"]}, "win": None}
    ep2 = {"mac": {"ip": "x", "models": ["a", "b"]}, "win": None}
    assert D.compute_hash(ep1) == D.compute_hash(ep2)

def test_hash_none_endpoint():
    ep = {"mac": None, "win": None}
    assert isinstance(D.compute_hash(ep), str)
    assert len(D.compute_hash(ep)) == 40


# ── backup limits ─────────────────────────────────────────────────────────────

def test_backup_limit_enforced(tmp_path, monkeypatch):
    monkeypatch.setattr(D, "BACKUPS_DIR", tmp_path / "backups")
    monkeypatch.setattr(D, "ARCHIVE_DIR", tmp_path / "archive")
    (tmp_path / "backups").mkdir()
    (tmp_path / "archive").mkdir()

    # Create 32 fake backup files
    for i in range(32):
        f = tmp_path / "backups" / f"2026-01-{i+1:02d}_00-00-00.json"
        f.write_text("{}")
        # stagger mtime so ordering is deterministic
        import os; os.utime(f, (i * 1000, i * 1000))

    D._enforce_backup_limits()
    remaining = list((tmp_path / "backups").glob("*.json"))
    assert len(remaining) <= D.MAX_BACKUPS

def test_old_files_archived_not_deleted(tmp_path, monkeypatch):
    monkeypatch.setattr(D, "BACKUPS_DIR", tmp_path / "backups")
    monkeypatch.setattr(D, "ARCHIVE_DIR", tmp_path / "archive")
    (tmp_path / "backups").mkdir()
    (tmp_path / "archive").mkdir()

    import os
    old_file = tmp_path / "backups" / "2025-01-01_00-00-00.json"
    old_file.write_text("{}")
    old_mtime = time.time() - (31 * 86400)  # 31 days ago
    os.utime(old_file, (old_mtime, old_mtime))

    D._enforce_backup_limits()
    assert not old_file.exists(), "old file should have been moved"
    assert (tmp_path / "archive" / "2025-01-01_00-00-00.json").exists(), "old file should be in archive"


# ── YAML patching ─────────────────────────────────────────────────────────────

DEVICES_YML = """\
devices:
  - id: "mac-studio"
    os: macos
    lan_ip: "192.168.254.103"
    ports: [1234]
  - id: "win-rtx3080"
    os: windows
    lan_ip: "192.168.254.100"
    ports: [1234]
"""

def test_patch_devices_yml(tmp_path):
    cfg = tmp_path / "config"
    cfg.mkdir()
    (cfg / "devices.yml").write_text(DEVICES_YML)
    D.patch_devices_yml("192.168.254.107", "192.168.254.101", tmp_path)
    result = (cfg / "devices.yml").read_text()
    assert '"192.168.254.107"' in result
    assert '"192.168.254.101"' in result
    assert "192.168.254.103" not in result
    assert "192.168.254.100" not in result

def test_patch_devices_yml_no_write_if_unchanged(tmp_path):
    cfg = tmp_path / "config"
    cfg.mkdir()
    content = DEVICES_YML.replace("192.168.254.103", "192.168.254.107").replace("192.168.254.100", "192.168.254.101")
    (cfg / "devices.yml").write_text(content)
    import os
    mtime_before = os.stat(cfg / "devices.yml").st_mtime
    time.sleep(0.01)
    D.patch_devices_yml("192.168.254.107", "192.168.254.101", tmp_path)
    mtime_after = os.stat(cfg / "devices.yml").st_mtime
    assert mtime_before == mtime_after, "file should not be rewritten when unchanged"


# ── openclaw.json patching ────────────────────────────────────────────────────

def test_patch_openclaw_json(tmp_path, monkeypatch):
    oc = tmp_path / "openclaw.json"
    oc.write_text(json.dumps({
        "models": {"providers": {
            "lmstudio-mac": {"baseUrl": "http://192.168.1.147:1234/v1", "models": []},
            "lmstudio-win": {"baseUrl": "http://192.168.254.108:1234/v1", "models": []},
        }},
        "meta": {"lastTouchedAt": "2026-01-01T00:00:00Z"}
    }))
    monkeypatch.setattr(D, "OPENCLAW_JSON", oc)
    endpoints = {
        "mac": {"ip": "192.168.254.107", "models": ["qwen3.5-9b-mlx", "text-embedding-nomic"]},
        "win": {"ip": "192.168.254.101", "models": ["qwen3.5-27b-distilled"]},
    }
    D.patch_openclaw_json(endpoints)
    cfg = json.loads(oc.read_text())
    assert "192.168.254.107" in cfg["models"]["providers"]["lmstudio-mac"]["baseUrl"]
    assert "192.168.254.101" in cfg["models"]["providers"]["lmstudio-win"]["baseUrl"]
    # Embedding models excluded from provider list
    mac_ids = [m["id"] for m in cfg["models"]["providers"]["lmstudio-mac"]["models"]]
    assert "text-embedding-nomic" not in mac_ids
    assert "qwen3.5-9b-mlx" in mac_ids


# ── idempotency ───────────────────────────────────────────────────────────────

def test_no_write_when_hash_unchanged(tmp_path, monkeypatch):
    """run_discovery returns 0 and writes nothing if hash matches last state."""
    monkeypatch.setattr(D, "STATE_DIR", tmp_path)
    monkeypatch.setattr(D, "BACKUPS_DIR", tmp_path / "backups")
    monkeypatch.setattr(D, "ARCHIVE_DIR", tmp_path / "archive")
    monkeypatch.setattr(D, "DISCOVERY_JSON", tmp_path / "discovery.json")
    monkeypatch.setattr(D, "LAST_DISCOVERY_JSON", tmp_path / "last_discovery.json")
    monkeypatch.setattr(D, "RECOVERY_SOURCE_TXT", tmp_path / "recovery_source.txt")
    monkeypatch.setattr(D, "OPENCLAW_JSON", tmp_path / "openclaw.json")
    (tmp_path / "openclaw.json").write_text("{}")
    (tmp_path / "backups").mkdir()
    (tmp_path / "archive").mkdir()

    endpoints = {"mac": {"ip": "127.0.0.1", "models": ["m1"]}, "win": {"ip": "1.2.3.4", "models": ["m2"]}}
    D.save_discovery_state(endpoints, tier=1)
    files_before = {f: f.stat().st_mtime for f in tmp_path.rglob("*.json")}

    # Patch discover_endpoints to return same data
    monkeypatch.setattr(D, "discover_endpoints", lambda: endpoints)
    time.sleep(0.05)
    result = D.run_discovery(force=True)

    assert result == 0
    for f, mtime in files_before.items():
        if f.name in ("discovery.json",):
            continue  # gossip timestamp is always updated
        assert f.stat().st_mtime == mtime, f"{f} should not have been rewritten"
```

- [ ] **Step 1.2: Run tests to confirm they fail (discover.py doesn't exist yet)**

```bash
mkdir -p ~/.openclaw/scripts/tests
cp "/Users/lawrencecyremelgarejo/Documents/Terminal xCode/claude/OpenClaw/docs/superpowers/plans/" ~/.openclaw/scripts/tests/  # copy test file after creation
cd ~/.openclaw/scripts && python3 -m pytest tests/test_discover.py -v 2>&1 | head -20
```
Expected: `ModuleNotFoundError: No module named 'discover'`

---

## Task 2: Implement discover.py

**Files:**
- Create: `~/.openclaw/scripts/discover.py`

- [ ] **Step 2.1: Create discover.py**

```python
#!/usr/bin/env python3
"""
~/.openclaw/scripts/discover.py
LM Studio Auto-Discovery Hub — Layer A.
Called by per-repo discover-lm-studio.sh when gossip is stale.
Idempotent: writes nothing if state hash is unchanged.
"""

from __future__ import annotations
import argparse, asyncio, fcntl, hashlib, json, os, re, shutil, socket, sys, time
import urllib.error, urllib.request
from datetime import datetime, timezone, timedelta
from pathlib import Path

# ── Paths ─────────────────────────────────────────────────────────────────────
OPENCLAW_DIR   = Path.home() / ".openclaw"
STATE_DIR      = OPENCLAW_DIR / "state"
BACKUPS_DIR    = STATE_DIR / "backups"
ARCHIVE_DIR    = STATE_DIR / "archive"
PROFILES_DIR   = OPENCLAW_DIR / "profiles"
DISCOVERY_JSON     = STATE_DIR / "discovery.json"
LAST_DISCOVERY_JSON = STATE_DIR / "last_discovery.json"
RECOVERY_SOURCE_TXT = STATE_DIR / "recovery_source.txt"
LOCK_FILE      = STATE_DIR / ".discover.lock"
OPENCLAW_JSON  = OPENCLAW_DIR / "openclaw.json"

LM_STUDIO_PORT     = 1234
SUBNET             = "192.168.254"
PROBE_TIMEOUT      = 0.2   # subnet scan per-IP timeout (seconds)
MODEL_API_TIMEOUT  = 4     # /v1/models request timeout
MAX_BACKUPS        = 30
ARCHIVE_DAYS       = 30
GOSSIP_TTL_SECONDS = 300   # 5 minutes

# ── Repo discovery ────────────────────────────────────────────────────────────

def get_repo_paths() -> dict[str, Path | None]:
    base = Path.home() / "Documents" / "Terminal xCode" / "claude" / "OpenClaw"
    candidates = {
        "alphaclaw":      [Path(os.environ.get("ALPHACLAW_INSTALL_DIR", "~/.alphaclaw")).expanduser()],
        "perpetua_tools": [
            base / "perplexity-api" / "Perpetua-Tools",
            Path.home() / "Perpetua-Tools",
        ],
        "orama_system":   [
            base / "orama-system",
            Path.home() / "orama-system",
        ],
    }
    result = {}
    for name, paths in candidates.items():
        env_key = name.upper() + "_PATH"
        if env_val := os.environ.get(env_key):
            result[name] = Path(env_val)
        else:
            result[name] = next((p for p in paths if p.exists()), None)
    return result

# ── Probing ───────────────────────────────────────────────────────────────────

def probe_models(base_url: str, timeout: float = MODEL_API_TIMEOUT) -> list[str] | None:
    try:
        req = urllib.request.Request(
            f"{base_url}/v1/models",
            headers={"Authorization": "Bearer lm-studio"},
        )
        with urllib.request.urlopen(req, timeout=timeout) as r:
            data = json.loads(r.read())
            models = sorted(m["id"] for m in data.get("data", []))
            return models or None
    except Exception:
        return None

async def _check_port(ip: str, port: int) -> str | None:
    try:
        _, w = await asyncio.wait_for(asyncio.open_connection(ip, port), timeout=PROBE_TIMEOUT)
        w.close(); await w.wait_closed()
        return ip
    except Exception:
        return None

async def scan_subnet_async(subnet: str, port: int, exclude: set[str]) -> list[str]:
    tasks = [_check_port(f"{subnet}.{i}", port) for i in range(1, 255)
             if f"{subnet}.{i}" not in exclude]
    return [ip for ip in await asyncio.gather(*tasks) if ip]

def _mac_lan_ip() -> str | None:
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("192.168.254.1", 80))
        ip = s.getsockname()[0]; s.close()
        return ip if ip.startswith("192.168.254.") else None
    except Exception:
        return None

def discover_endpoints() -> dict:
    """Probe live endpoints. Mac = localhost, Win = subnet scan."""
    result: dict[str, dict | None] = {"mac": None, "win": None}

    # Mac: always localhost on this machine
    mac_models = probe_models("http://localhost:1234")
    if mac_models:
        result["mac"] = {"ip": "localhost", "models": mac_models}

    # Win: try last known IP first, fall back to subnet scan
    last = _load_json(LAST_DISCOVERY_JSON)
    win_last_ip = (last or {}).get("endpoints", {}).get("win", {}).get("ip", "")
    mac_lan = _mac_lan_ip()
    exclude = {"localhost", "127.0.0.1", mac_lan} if mac_lan else {"localhost", "127.0.0.1"}

    if win_last_ip and win_last_ip not in exclude:
        win_models = probe_models(f"http://{win_last_ip}:1234")
        if win_models:
            result["win"] = {"ip": win_last_ip, "models": win_models}

    if not result["win"]:
        subnet = mac_lan.rsplit(".", 1)[0] if mac_lan else SUBNET
        for ip in asyncio.run(scan_subnet_async(subnet, LM_STUDIO_PORT, exclude)):
            models = probe_models(f"http://{ip}:1234")
            if models:
                result["win"] = {"ip": ip, "models": models}
                break

    return result

# ── Hash & state ──────────────────────────────────────────────────────────────

def compute_hash(endpoints: dict) -> str:
    mac = endpoints.get("mac") or {}
    win = endpoints.get("win") or {}
    key = json.dumps({
        "mac_ip": mac.get("ip", ""),
        "mac_models": sorted(mac.get("models", [])),
        "win_ip": win.get("ip", ""),
        "win_models": sorted(win.get("models", [])),
    }, sort_keys=True)
    return hashlib.sha1(key.encode()).hexdigest()

def _load_json(path: Path) -> dict | None:
    try: return json.loads(path.read_text())
    except Exception: return None

def save_discovery_state(endpoints: dict, tier: int = 1):
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    mac = endpoints.get("mac") or {}
    win = endpoints.get("win") or {}
    state = {
        "schema": 1,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "hash": compute_hash(endpoints),
        "recovery_tier": tier,
        "endpoints": {
            "mac": {"ip": mac.get("ip", ""), "port": LM_STUDIO_PORT, "reachable": bool(mac)},
            "win": {"ip": win.get("ip", ""), "port": LM_STUDIO_PORT, "reachable": bool(win)},
        },
        "models": {"mac": mac.get("models", []), "win": win.get("models", [])},
    }
    DISCOVERY_JSON.write_text(json.dumps(state, indent=2))
    LAST_DISCOVERY_JSON.write_text(json.dumps(state, indent=2))
    RECOVERY_SOURCE_TXT.write_text(f"tier{tier}\n")

# ── Backup / archive ──────────────────────────────────────────────────────────

def backup_current_state():
    if not LAST_DISCOVERY_JSON.exists(): return
    BACKUPS_DIR.mkdir(parents=True, exist_ok=True)
    ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    shutil.copy2(LAST_DISCOVERY_JSON, BACKUPS_DIR / f"{ts}.json")
    _enforce_backup_limits()

def _enforce_backup_limits():
    BACKUPS_DIR.mkdir(parents=True, exist_ok=True)
    ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)
    cutoff = time.time() - (ARCHIVE_DAYS * 86400)
    backups = sorted(BACKUPS_DIR.glob("*.json"), key=lambda p: p.stat().st_mtime)
    # Archive files older than ARCHIVE_DAYS
    for f in list(backups):
        if f.stat().st_mtime < cutoff:
            shutil.move(str(f), str(ARCHIVE_DIR / f.name))
            backups.remove(f)
    # Delete oldest if over MAX_BACKUPS (after archiving)
    backups = sorted(BACKUPS_DIR.glob("*.json"), key=lambda p: p.stat().st_mtime)
    while len(backups) > MAX_BACKUPS:
        backups[0].unlink()
        backups = backups[1:]

# ── Config patching ───────────────────────────────────────────────────────────

def patch_openclaw_json(endpoints: dict):
    if not OPENCLAW_JSON.exists(): return
    cfg = _load_json(OPENCLAW_JSON)
    if not cfg: return
    providers = cfg.setdefault("models", {}).setdefault("providers", {})
    mac = endpoints.get("mac")
    win = endpoints.get("win")
    if mac:
        url = "http://localhost:1234/v1" if mac["ip"] == "localhost" else f"http://{mac['ip']}:1234/v1"
        providers.setdefault("lmstudio-mac", {})["baseUrl"] = url
        providers["lmstudio-mac"]["models"] = [
            {"id": m, "name": f"Mac LMS — {m}", "contextWindow": 32768,
             "maxTokens": 8192, "cost": {"input": 0, "output": 0}}
            for m in mac["models"] if "embed" not in m.lower()
        ]
    if win:
        providers.setdefault("lmstudio-win", {})["baseUrl"] = f"http://{win['ip']}:1234/v1"
        providers["lmstudio-win"]["models"] = [
            {"id": m, "name": f"Win LMS — {m}", "contextWindow": 32768,
             "maxTokens": 8192, "cost": {"input": 0, "output": 0}}
            for m in win["models"] if "embed" not in m.lower()
        ]
    cfg.setdefault("meta", {})["lastTouchedAt"] = datetime.now(timezone.utc).isoformat()
    OPENCLAW_JSON.write_text(json.dumps(cfg, indent=2))

def patch_devices_yml(mac_ip: str, win_ip: str, pt_repo: Path):
    f = pt_repo / "config" / "devices.yml"
    if not f.exists(): return
    content = original = f.read_text()
    # Section-aware: replace lan_ip only within the correct device block
    content = re.sub(
        r'(- id: "mac-studio".*?lan_ip:\s*")[^"]+(")',
        lambda m: m.group(1) + mac_ip + m.group(2),
        content, flags=re.DOTALL
    )
    content = re.sub(
        r'(- id: "win-rtx3080".*?lan_ip:\s*")[^"]+(")',
        lambda m: m.group(1) + win_ip + m.group(2),
        content, flags=re.DOTALL
    )
    if content != original:
        f.write_text(content)

def patch_models_yml(mac_ip: str, win_ip: str, pt_repo: Path):
    f = pt_repo / "config" / "models.yml"
    if not f.exists(): return
    content = original = f.read_text()
    mac_url = "http://localhost:1234" if mac_ip == "localhost" else f"http://{mac_ip}:1234"
    content = re.sub(r'(\$\{LM_STUDIO_MAC_ENDPOINT:-)[^}]+(\})', rf'\g<1>{mac_url}\2', content)
    content = re.sub(r'(\$\{LM_STUDIO_WIN_ENDPOINTS:-)[^}:]+', rf'\g<1>http://{win_ip}', content)
    if content != original:
        f.write_text(content)

def write_env_lmstudio(endpoints: dict, repo_paths: dict):
    mac = endpoints.get("mac") or {}
    win = endpoints.get("win") or {}
    mac_ip  = mac.get("ip", "")
    win_ip  = win.get("ip", "")
    mac_url = "http://localhost:1234" if mac_ip == "localhost" else f"http://{mac_ip}:1234"
    win_url = f"http://{win_ip}:1234" if win_ip else ""
    mac_models = mac.get("models", [])
    win_models = win.get("models", [])
    mac_primary = next((m for m in mac_models if "embed" not in m.lower()), "")
    win_primary = next((m for m in win_models if "27b" in m.lower() or "embed" not in m.lower()), "")
    win_fallback = next((m for m in win_models if m != win_primary and "embed" not in m.lower()), "")
    tier = (_load_json(LAST_DISCOVERY_JSON) or {}).get("recovery_tier", 1)
    content = (
        f"# Auto-generated by ~/.openclaw/scripts/discover.py — do not edit manually\n"
        f"# Last updated: {datetime.now(timezone.utc).isoformat()} | recovery_tier: {tier}\n"
        f"LM_STUDIO_MAC_ENDPOINT={mac_url}\n"
        f"LM_STUDIO_WIN_ENDPOINTS={win_url}\n"
        f"LMS_MAC_MODEL={mac_primary}\n"
        f"LMS_WIN_MODEL={win_primary}\n"
        f"LMS_WIN_FALLBACK_MODEL={win_fallback}\n"
        f"LM_STUDIO_API_TOKEN=lm-studio\n"
    )
    for repo_path in repo_paths.values():
        if repo_path and Path(repo_path).exists():
            (Path(repo_path) / ".env.lmstudio").write_text(content)

# ── Recovery tiers ────────────────────────────────────────────────────────────

def _state_to_ep(state: dict) -> dict | None:
    if not state or not state.get("endpoints"): return None
    return {
        "mac": {"ip": state["endpoints"]["mac"]["ip"], "models": state["models"]["mac"]}
              if state["endpoints"]["mac"]["reachable"] else None,
        "win": {"ip": state["endpoints"]["win"]["ip"], "models": state["models"]["win"]}
              if state["endpoints"]["win"]["reachable"] else None,
    }

def _load_tier2() -> dict | None: return _state_to_ep(_load_json(LAST_DISCOVERY_JSON))
def _load_tier3() -> dict | None:
    if not BACKUPS_DIR.exists(): return None
    for b in sorted(BACKUPS_DIR.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True):
        ep = _state_to_ep(_load_json(b))
        if ep: return ep
    return None
def _load_tier4(profile: str = "lan-full") -> dict | None:
    return _state_to_ep(_load_json(PROFILES_DIR / f"{profile}.json"))

# ── File lock ─────────────────────────────────────────────────────────────────

class _Lock:
    def __init__(self, timeout=10.0):
        self._timeout = timeout; self._fd = None
    def __enter__(self):
        STATE_DIR.mkdir(parents=True, exist_ok=True)
        self._fd = open(LOCK_FILE, "w")
        deadline = time.time() + self._timeout
        while True:
            try:
                fcntl.flock(self._fd, fcntl.LOCK_EX | fcntl.LOCK_NB); return self
            except BlockingIOError:
                if time.time() > deadline: raise TimeoutError("discovery lock timeout")
                time.sleep(0.2)
    def __exit__(self, *_):
        if self._fd:
            fcntl.flock(self._fd, fcntl.LOCK_UN); self._fd.close()
            try: LOCK_FILE.unlink()
            except FileNotFoundError: pass

# ── Main discovery flow ───────────────────────────────────────────────────────

def run_discovery(force: bool = False) -> int:
    with _Lock():
        # Gossip freshness check (double-check inside lock)
        if not force and DISCOVERY_JSON.exists():
            state = _load_json(DISCOVERY_JSON)
            if state:
                age = (datetime.now(timezone.utc) -
                       datetime.fromisoformat(state["timestamp"])).total_seconds()
                if age < GOSSIP_TTL_SECONDS:
                    return 0

        print("🔍 Probing LM Studio endpoints...", file=sys.stderr)
        endpoints = discover_endpoints()
        tier = 1

        if not endpoints["mac"] and not endpoints["win"]:
            print("⚠️  No live endpoints — trying recovery tiers...", file=sys.stderr)
            for fn, t, name in [(_load_tier2, 2, "last known good"),
                                  (_load_tier3, 3, "newest backup"),
                                  (lambda: _load_tier4("lan-full"), 4, "lan-full profile")]:
                ep = fn()
                if ep: endpoints = ep; tier = t; print(f"  → tier {t}: {name}", file=sys.stderr); break
            if not endpoints["mac"] and not endpoints["win"]:
                print("❌ All tiers failed.", file=sys.stderr)
                RECOVERY_SOURCE_TXT.write_text("tier_failed\n")
                return 1
        else:
            # Partial: preserve last-good for the missing endpoint
            last = _load_json(LAST_DISCOVERY_JSON)
            if last:
                for role in ("mac", "win"):
                    if not endpoints[role] and last["endpoints"][role]["reachable"]:
                        endpoints[role] = {"ip": last["endpoints"][role]["ip"],
                                           "models": last["models"][role]}
                        print(f"⚠️  {role} unreachable — preserving last-good", file=sys.stderr)

        # Idempotency check
        new_hash = compute_hash(endpoints)
        last = _load_json(LAST_DISCOVERY_JSON)
        if last and last.get("hash") == new_hash:
            # Refresh gossip timestamp only
            last["timestamp"] = datetime.now(timezone.utc).isoformat()
            DISCOVERY_JSON.write_text(json.dumps(last, indent=2))
            print("✅ No changes. Config is current.", file=sys.stderr)
            return 0

        print("🔄 Changes detected — updating configs...", file=sys.stderr)
        backup_current_state()
        repo_paths = get_repo_paths()
        pt_repo = repo_paths.get("perpetua_tools")
        mac = endpoints.get("mac") or {}
        win = endpoints.get("win") or {}

        patch_openclaw_json(endpoints)
        print("  ✓ openclaw.json", file=sys.stderr)
        if pt_repo:
            patch_devices_yml(mac.get("ip",""), win.get("ip",""), pt_repo)
            patch_models_yml(mac.get("ip",""), win.get("ip",""), pt_repo)
            print("  ✓ Perpetua-Tools config/", file=sys.stderr)
        write_env_lmstudio(endpoints, repo_paths)
        print("  ✓ .env.lmstudio written", file=sys.stderr)
        save_discovery_state(endpoints, tier)
        print(f"  ✓ state saved (tier {tier})", file=sys.stderr)
        if mac.get("ip"): print(f"  Mac: {mac['ip']} — {len(mac.get('models',[]))} models", file=sys.stderr)
        if win.get("ip"): print(f"  Win: {win['ip']} — {len(win.get('models',[]))} models", file=sys.stderr)
        return 0

# ── CLI ───────────────────────────────────────────────────────────────────────

def _cmd_status():
    state = _load_json(LAST_DISCOVERY_JSON) or _load_json(DISCOVERY_JSON)
    if not state: print("No discovery state. Run: discover.py --force"); return
    print(f"Tier:    {state.get('recovery_tier','?')}")
    print(f"Updated: {state.get('timestamp','?')}")
    for role, ep in state.get("endpoints", {}).items():
        ok = "✅" if ep["reachable"] else "❌"
        print(f"  {role}: {ok} {ep['ip']}:{ep['port']} — {len(state['models'].get(role,[]))} models")
    src = RECOVERY_SOURCE_TXT.read_text().strip() if RECOVERY_SOURCE_TXT.exists() else "unknown"
    print(f"Source:  {src}")

def _cmd_restore(target: str):
    if target == "latest":
        ep = _load_tier3()
    elif target.startswith("profile:"):
        ep = _load_tier4(target.split(":", 1)[1])
    else:
        matches = sorted(BACKUPS_DIR.glob(f"{target}*.json")) if BACKUPS_DIR.exists() else []
        ep = _state_to_ep(_load_json(matches[-1])) if matches else None
    if not ep: print(f"Nothing found for '{target}'."); return
    backup_current_state()
    repo_paths = get_repo_paths()
    pt_repo = repo_paths.get("perpetua_tools")
    mac = ep.get("mac") or {}; win = ep.get("win") or {}
    patch_openclaw_json(ep)
    if pt_repo:
        patch_devices_yml(mac.get("ip",""), win.get("ip",""), pt_repo)
        patch_models_yml(mac.get("ip",""), win.get("ip",""), pt_repo)
    write_env_lmstudio(ep, repo_paths)
    save_discovery_state(ep, tier=99)
    RECOVERY_SOURCE_TXT.write_text("manual_restore\n")
    print(f"✅ Restored: Mac={mac.get('ip','?')} Win={win.get('ip','?')}")

def main():
    p = argparse.ArgumentParser(description="LM Studio Auto-Discovery")
    p.add_argument("--force",   action="store_true", help="Re-probe now, bypass gossip TTL")
    p.add_argument("--status",  action="store_true", help="Show current state")
    p.add_argument("--restore", metavar="TARGET",    help="latest | YYYY-MM-DD | profile:name")
    p.add_argument("--prune",   action="store_true", help="Manually prune backups")
    args = p.parse_args()
    if args.status:  _cmd_status(); sys.exit(0)
    if args.restore: _cmd_restore(args.restore); sys.exit(0)
    if args.prune:   _enforce_backup_limits(); print("✅ Pruned."); sys.exit(0)
    sys.exit(run_discovery(force=args.force))

if __name__ == "__main__":
    main()
```

- [ ] **Step 2.2: Make discover.py executable and create required dirs**

```bash
chmod +x ~/.openclaw/scripts/discover.py
mkdir -p ~/.openclaw/state/backups ~/.openclaw/state/archive ~/.openclaw/profiles
```

- [ ] **Step 2.3: Run tests — expect all to pass**

```bash
cd ~/.openclaw/scripts && python3 -m pytest tests/test_discover.py -v
```

Expected: all 9 tests PASS.

- [ ] **Step 2.4: Run live dry-run**

```bash
python3 ~/.openclaw/scripts/discover.py --force
python3 scripts/discover.py --status
```

Expected output includes `Mac: 192.168.254.107` and `Win: 192.168.254.101` (or both as `localhost`/LAN).

- [ ] **Step 2.5: Commit test file**

```bash
# Tests live locally — no git commit needed for ~/.openclaw
echo "discover.py installed and tests passing" >> ~/.openclaw/state/recovery_source.txt
```

---

## Task 3: Create recovery profiles

**Files:**
- Create: `~/.openclaw/profiles/lan-full.json`
- Create: `~/.openclaw/profiles/mac-only.json`
- Create: `~/.openclaw/profiles/win-only.json`

- [ ] **Step 3.1: Write profiles**

```bash
cat > ~/.openclaw/profiles/lan-full.json << 'EOF'
{
  "schema": 1,
  "timestamp": "2026-04-20T00:00:00Z",
  "hash": "default",
  "recovery_tier": 4,
  "endpoints": {
    "mac": {"ip": "192.168.254.107", "port": 1234, "reachable": true},
    "win": {"ip": "192.168.254.101", "port": 1234, "reachable": true}
  },
  "models": {
    "mac": ["gemma-4-26b-a4b-it", "gemma-4-e4b-it", "qwen3.5-9b-mlx", "qwen3.5-27b-claude-4.6-opus-reasoning-distilled-v2"],
    "win": ["gemma-4-26b-a4b-it", "gemma-4-e4b-it", "qwen3.5-9b-mlx", "qwen3.5-27b-claude-4.6-opus-reasoning-distilled-v2"]
  }
}
EOF

cat > ~/.openclaw/profiles/mac-only.json << 'EOF'
{
  "schema": 1, "timestamp": "2026-04-20T00:00:00Z", "hash": "default", "recovery_tier": 4,
  "endpoints": {
    "mac": {"ip": "localhost", "port": 1234, "reachable": true},
    "win": {"ip": "", "port": 1234, "reachable": false}
  },
  "models": {
    "mac": ["qwen3.5-9b-mlx", "qwen3.5-27b-claude-4.6-opus-reasoning-distilled-v2"],
    "win": []
  }
}
EOF

cat > ~/.openclaw/profiles/win-only.json << 'EOF'
{
  "schema": 1, "timestamp": "2026-04-20T00:00:00Z", "hash": "default", "recovery_tier": 4,
  "endpoints": {
    "mac": {"ip": "", "port": 1234, "reachable": false},
    "win": {"ip": "192.168.254.101", "port": 1234, "reachable": true}
  },
  "models": {
    "mac": [],
    "win": ["qwen3.5-27b-claude-4.6-opus-reasoning-distilled-v2", "gemma-4-26b-a4b-it"]
  }
}
EOF
```

- [ ] **Step 3.2: Verify restore from profile works**

```bash
python3 ~/.openclaw/scripts/discover.py --restore profile:mac-only
python3 scripts/discover.py --status
# Expect: Mac reachable, Win not reachable
python3 ~/.openclaw/scripts/discover.py --force
# Re-probe and restore live state
python3 scripts/discover.py --status
# Expect: both live
```

---

## Task 4: Fix openclaw.json stale IPs (local only)

**Files:**
- Modify: `~/.openclaw/openclaw.json`

- [ ] **Step 4.1: Run discover.py --force (already does this)**

The `--force` in Task 2.4 already patched `openclaw.json`. Verify:

```bash
python3 -c "
import json
from pathlib import Path
cfg = json.loads((Path.home()/'.openclaw/openclaw.json').read_text())
print('mac:', cfg['models']['providers']['lmstudio-mac']['baseUrl'])
print('win:', cfg['models']['providers']['lmstudio-win']['baseUrl'])
"
```

Expected:
```
mac: http://localhost:1234/v1  (or http://192.168.254.107:1234/v1)
win: http://192.168.254.101:1234/v1
```

- [ ] **Step 4.2: If IPs still stale, force-patch manually**

```bash
python3 - << 'EOF'
import json
from pathlib import Path
p = Path.home() / ".openclaw/openclaw.json"
cfg = json.loads(p.read_text())
cfg["models"]["providers"]["lmstudio-mac"]["baseUrl"] = "http://localhost:1234/v1"
cfg["models"]["providers"]["lmstudio-win"]["baseUrl"] = "http://192.168.254.101:1234/v1"
p.write_text(json.dumps(cfg, indent=2))
print("Patched.")
EOF
```

---

## Task 5: Per-repo shell gates (push to all 3 repos)

**Files:**
- Create + push: `AlphaClaw:scripts/discover-lm-studio.sh` (branch: feature/MacOS-post-install)
- Create + push: `Perpetua-Tools:scripts/discover-lm-studio.sh` (branch: main)
- Create + push: `orama-system:scripts/discover-lm-studio.sh` (branch: main)

The shell gate content is identical for all three repos.

- [ ] **Step 5.1: Push shell gate to AlphaClaw**

```bash
CONTENT=$(cat << 'SHELL'
#!/usr/bin/env bash
# scripts/discover-lm-studio.sh
# Layer B: gossip gate for LM Studio auto-discovery.
# Checks 5-min TTL; if stale, delegates to ~/.openclaw/scripts/discover.py.
# Safe to call from Claude Code SessionStart — exits immediately when gossip is fresh.
set -euo pipefail

DISCOVER_PY="$HOME/.openclaw/scripts/discover.py"
DISCOVERY_JSON="$HOME/.openclaw/state/discovery.json"
GOSSIP_TTL=300

if [[ ! -f "$DISCOVER_PY" ]]; then
  echo "⚠️  discover.py not installed. Run: python setup_macos.py" >&2
  exit 0
fi

if [[ -f "$DISCOVERY_JSON" ]]; then
  age=$(python3 -c "
import json
from datetime import datetime, timezone
try:
    d = json.load(open('$DISCOVERY_JSON'))
    ts = datetime.fromisoformat(d['timestamp'])
    print(int((datetime.now(timezone.utc) - ts).total_seconds()))
except Exception:
    print(99999)
" 2>/dev/null || echo 99999)
  if (( age < GOSSIP_TTL )); then
    exit 0
  fi
fi

exec python3 "$DISCOVER_PY" "$@"
SHELL
)

# Get current SHA for update (returns null if file doesn't exist)
SHA=$(gh api "repos/diazMelgarejo/AlphaClaw/contents/scripts/discover-lm-studio.sh?ref=feature%2FMacOS-post-install" --jq '.sha' 2>/dev/null || echo "")
ENCODED=$(echo "$CONTENT" | base64)

if [[ -z "$SHA" ]]; then
  gh api "repos/diazMelgarejo/AlphaClaw/contents/scripts/discover-lm-studio.sh" \
    -X PUT \
    -f "message=feat(automation): add LM Studio discovery shell gate [skip ci]" \
    -f "content=$ENCODED" \
    -f "branch=feature/MacOS-post-install"
else
  gh api "repos/diazMelgarejo/AlphaClaw/contents/scripts/discover-lm-studio.sh" \
    -X PUT \
    -f "message=feat(automation): add LM Studio discovery shell gate [skip ci]" \
    -f "content=$ENCODED" \
    -f "sha=$SHA" \
    -f "branch=feature/MacOS-post-install"
fi
echo "✅ AlphaClaw shell gate pushed"
```

- [ ] **Step 5.2: Push shell gate to Perpetua-Tools**

```bash
SHA=$(gh api "repos/diazMelgarejo/Perpetua-Tools/contents/scripts/discover-lm-studio.sh" --jq '.sha' 2>/dev/null || echo "")
# Same CONTENT and ENCODED from step 5.1
if [[ -z "$SHA" ]]; then
  gh api "repos/diazMelgarejo/Perpetua-Tools/contents/scripts/discover-lm-studio.sh" \
    -X PUT -f "message=feat(automation): add LM Studio discovery shell gate [skip ci]" \
    -f "content=$ENCODED" -f "branch=main"
else
  gh api "repos/diazMelgarejo/Perpetua-Tools/contents/scripts/discover-lm-studio.sh" \
    -X PUT -f "message=feat(automation): add LM Studio discovery shell gate [skip ci]" \
    -f "content=$ENCODED" -f "sha=$SHA" -f "branch=main"
fi
echo "✅ Perpetua-Tools shell gate pushed"
```

- [ ] **Step 5.3: Push shell gate to orama-system**

```bash
SHA=$(gh api "repos/diazMelgarejo/orama-system/contents/scripts/discover-lm-studio.sh" --jq '.sha' 2>/dev/null || echo "")
if [[ -z "$SHA" ]]; then
  gh api "repos/diazMelgarejo/orama-system/contents/scripts/discover-lm-studio.sh" \
    -X PUT -f "message=feat(automation): add LM Studio discovery shell gate [skip ci]" \
    -f "content=$ENCODED" -f "branch=main"
else
  gh api "repos/diazMelgarejo/orama-system/contents/scripts/discover-lm-studio.sh" \
    -X PUT -f "message=feat(automation): add LM Studio discovery shell gate [skip ci]" \
    -f "content=$ENCODED" -f "sha=$SHA" -f "branch=main"
fi
echo "✅ orama-system shell gate pushed"
```

---

## Task 6: Update .claude/settings.json in all 3 repos

- [ ] **Step 6.1: Push AlphaClaw settings.json**

```bash
SHA=$(gh api "repos/diazMelgarejo/AlphaClaw/contents/.claude/settings.json?ref=feature%2FMacOS-post-install" --jq '.sha' 2>/dev/null || echo "")
CONTENT=$(base64 << 'EOF'
{
  "hooks": {
    "SessionStart": [
      {
        "hooks": [
          {
            "type": "command",
            "command": "bash scripts/discover-lm-studio.sh 2>&1 | grep -v '^$' || true",
            "statusMessage": "Syncing LM Studio endpoints...",
            "async": true
          },
          {
            "type": "command",
            "command": "git fetch origin pr-4-macos --quiet 2>/dev/null || true",
            "async": true
          }
        ]
      }
    ],
    "PreToolUse": [
      {
        "matcher": "Edit|Write",
        "hooks": [
          {
            "type": "command",
            "command": "python3 -c \"import sys,json,os; p=json.loads(os.environ.get('CLAUDE_TOOL_INPUT','{}')).get('file_path',''); sys.exit(1 if 'package-lock.json' in p else 0)\" && true || (echo '⛔ Direct edits to package-lock.json are blocked — run npm install instead' && exit 1)"
          }
        ]
      }
    ],
    "PostToolUse": [
      {
        "matcher": "Edit|Write",
        "hooks": [
          {
            "type": "command",
            "command": "npm test --reporter=dot 2>&1 | tail -8 || true"
          }
        ]
      }
    ]
  }
}
EOF
)
if [[ -z "$SHA" ]]; then
  gh api "repos/diazMelgarejo/AlphaClaw/contents/.claude/settings.json" \
    -X PUT -f "message=chore(automation): add hooks — discover, test-on-edit, lock-guard [skip ci]" \
    -f "content=$CONTENT" -f "branch=feature/MacOS-post-install"
else
  gh api "repos/diazMelgarejo/AlphaClaw/contents/.claude/settings.json" \
    -X PUT -f "message=chore(automation): add hooks — discover, test-on-edit, lock-guard [skip ci]" \
    -f "content=$CONTENT" -f "sha=$SHA" -f "branch=feature/MacOS-post-install"
fi
echo "✅ AlphaClaw settings.json pushed"
```

- [ ] **Step 6.2: Push Perpetua-Tools settings.json**

```bash
SHA=$(gh api "repos/diazMelgarejo/Perpetua-Tools/contents/.claude/settings.json" --jq '.sha' 2>/dev/null || echo "")
CONTENT=$(base64 << 'EOF'
{
  "hooks": {
    "SessionStart": [
      {
        "hooks": [
          {
            "type": "command",
            "command": "bash scripts/discover-lm-studio.sh 2>&1 | grep -v '^$' || true",
            "statusMessage": "Discovering LM Studio endpoints...",
            "async": true
          },
          {
            "type": "command",
            "command": "bash scripts/sync-companion-instincts.sh 2>/dev/null || true",
            "statusMessage": "Syncing companion instincts...",
            "async": true
          }
        ]
      }
    ],
    "PostToolUse": [
      {
        "matcher": "Edit|Write",
        "hooks": [
          {
            "type": "command",
            "command": "file=$(python3 -c \"import sys,json,os; print(json.loads(os.environ.get('CLAUDE_TOOL_INPUT','{}')).get('file_path',''))\" 2>/dev/null || echo ''); [[ \"$file\" == *.py ]] && ruff check \"$file\" 2>&1 | head -10 || true"
          }
        ]
      },
      {
        "matcher": "Edit|Write",
        "hooks": [
          {
            "type": "command",
            "command": "[[ -f pyproject.toml ]] && python -m pytest tests/ -x -q --tb=short 2>&1 | tail -12 || true"
          }
        ]
      }
    ]
  }
}
EOF
)
if [[ -z "$SHA" ]]; then
  gh api "repos/diazMelgarejo/Perpetua-Tools/contents/.claude/settings.json" \
    -X PUT -f "message=chore(automation): add hooks — discover, ruff, pytest [skip ci]" \
    -f "content=$CONTENT" -f "branch=main"
else
  gh api "repos/diazMelgarejo/Perpetua-Tools/contents/.claude/settings.json" \
    -X PUT -f "message=chore(automation): add hooks — discover, ruff, pytest [skip ci]" \
    -f "content=$CONTENT" -f "sha=$SHA" -f "branch=main"
fi
echo "✅ Perpetua-Tools settings.json pushed"
```

- [ ] **Step 6.3: Push orama-system settings.json**

```bash
SHA=$(gh api "repos/diazMelgarejo/orama-system/contents/.claude/settings.json" --jq '.sha' 2>/dev/null || echo "")
CONTENT=$(base64 << 'EOF'
{
  "hooks": {
    "SessionStart": [
      {
        "hooks": [
          {
            "type": "command",
            "command": "bash scripts/discover-lm-studio.sh 2>&1 | grep -v '^$' || true",
            "statusMessage": "Discovering LM Studio endpoints...",
            "async": true
          },
          {
            "type": "command",
            "command": "bash scripts/sync-companion-instincts.sh 2>/dev/null || true",
            "statusMessage": "Syncing companion instincts...",
            "async": true
          }
        ]
      }
    ],
    "PostToolUse": [
      {
        "matcher": "Edit|Write",
        "hooks": [
          {
            "type": "command",
            "command": "file=$(python3 -c \"import sys,json,os; print(json.loads(os.environ.get('CLAUDE_TOOL_INPUT','{}')).get('file_path',''))\" 2>/dev/null || echo ''); [[ \"$file\" == *.py ]] && ruff check \"$file\" 2>&1 | head -10 || true"
          }
        ]
      }
    ],
    "Stop": [
      {
        "hooks": [
          {
            "type": "command",
            "command": "git diff --name-only HEAD -- .claude/lessons/ 2>/dev/null | grep -q . || echo '⚠️  LESSONS.md not updated this session — CLAUDE.md requires a write-back before ending.'"
          }
        ]
      }
    ]
  }
}
EOF
)
if [[ -z "$SHA" ]]; then
  gh api "repos/diazMelgarejo/orama-system/contents/.claude/settings.json" \
    -X PUT -f "message=chore(automation): add hooks — discover, ruff, lessons-check [skip ci]" \
    -f "content=$CONTENT" -f "branch=main"
else
  gh api "repos/diazMelgarejo/orama-system/contents/.claude/settings.json" \
    -X PUT -f "message=chore(automation): add hooks — discover, ruff, lessons-check [skip ci]" \
    -f "content=$CONTENT" -f "sha=$SHA" -f "branch=main"
fi
echo "✅ orama-system settings.json pushed"
```

---

## Task 7: Skills — AlphaClaw

**Files to create + push on `feature/MacOS-post-install`:**
- `.claude/skills/macos-port-status/SKILL.md`
- `.claude/skills/cherry-pick-down/SKILL.md`

- [ ] **Step 7.1: Push macos-port-status skill**

```bash
CONTENT=$(base64 << 'EOF'
---
name: macos-port-status
description: Show AlphaClaw macOS port branch sync status, cherry-pick gaps, and test health
---

Check AlphaClaw macOS port status:

```bash
# 1. Commits in feature not yet cherry-picked to pr-4-macos
git log --oneline feature/MacOS-post-install ^pr-4-macos | head -15

# 2. Commits in pr-4-macos not yet in main (upstream PR delta)
git log --oneline pr-4-macos ^main | head -15

# 3. Test health
npm test --reporter=dot 2>&1 | tail -8

# 4. LM Studio endpoint status - MIGRATE properly as first-class feature, de-hack-ify?
python3 ~/.openclaw/scripts/discover.py --status
```

Report:
- Which commits need cherry-picking down (feature → pr-4-macos)
- Whether any commits in pr-4-macos contain fork-specific files (should not)
- Test pass/fail summary
- LM Studio endpoint health
EOF
)
gh api "repos/diazMelgarejo/AlphaClaw/contents/.claude/skills/macos-port-status/SKILL.md" \
  -X PUT \
  -f "message=chore(automation): add macos-port-status skill [skip ci]" \
  -f "content=$CONTENT" \
  -f "branch=feature/MacOS-post-install"
echo "✅ macos-port-status skill pushed"
```

- [ ] **Step 7.2: Push cherry-pick-down skill**

```bash
CONTENT=$(base64 << 'EOF'
---
name: cherry-pick-down
description: Safely cherry-pick a commit from feature/MacOS-post-install down to pr-4-macos with upstream-compat check
disable-model-invocation: true
---

Before cherry-picking any commit to pr-4-macos, run these checks in order:

**1. Confirm tests pass on current state:**
```bash
npm test --reporter=dot 2>&1 | tail -5
```

**2. Check the commit for fork-specific files (MUST be absent):**
Fork-specific files NEVER go to pr-4-macos:
- `.npmrc` (with @diazmelgarejo scope)
- `scripts/apply-openclaw-patches.js`
- `lib/mcp/`
- `lib/agents/`
- `.mcp.json`
- `docs/wiki/`

Check: `git show <sha> --name-only | grep -E "lib/mcp|lib/agents|apply-openclaw|\.mcp\.json|docs/wiki"`
If any match → STOP. This commit cannot go to pr-4-macos.

**3. Cherry-pick with review:**
```bash
git cherry-pick <sha> --no-commit
git diff --staged   # review before committing
git commit          # use original commit message
```

**4. Push:**
```bash
git push origin pr-4-macos
```
EOF
)
gh api "repos/diazMelgarejo/AlphaClaw/contents/.claude/skills/cherry-pick-down/SKILL.md" \
  -X PUT \
  -f "message=chore(automation): add cherry-pick-down skill [skip ci]" \
  -f "content=$CONTENT" \
  -f "branch=feature/MacOS-post-install"
echo "✅ cherry-pick-down skill pushed"
```

---

## Task 8: Subagent — AlphaClaw

- [ ] **Step 8.1: Push upstream-compat-reviewer subagent**

```bash
CONTENT=$(base64 << 'EOF'
---
name: upstream-compat-reviewer
description: Review a diff or commit for upstream compatibility before cherry-picking to pr-4-macos. Returns PASS or FAIL with specific reasoning.
---

You are a strict upstream compatibility reviewer for the AlphaClaw macOS port.

FORK-SPECIFIC (FAIL immediately if present):
- `.npmrc` containing `@diazmelgarejo` scope
- `scripts/apply-openclaw-patches.js`
- `lib/mcp/` (any file in this dir)
- `lib/agents/` (any file in this dir)
- `.mcp.json`
- `docs/wiki/` (any file in this dir)

UPSTREAM-SAFE:
- Path separator fixes (win32 → posix)
- Case-insensitive fs handling
- Symlink resolution
- Build tool version pins
- Test infrastructure fixes

Output format:
```
VERDICT: PASS | FAIL

REASON: <specific reason — quote the offending file/line if FAIL>

IF FAIL — what would make it upstream-safe:
<concrete change required, or "this cannot be made upstream-safe">
```
EOF
)
SHA=$(gh api "repos/diazMelgarejo/AlphaClaw/contents/.claude/agents/upstream-compat-reviewer.md?ref=feature%2FMacOS-post-install" --jq '.sha' 2>/dev/null || echo "")
if [[ -z "$SHA" ]]; then
  gh api "repos/diazMelgarejo/AlphaClaw/contents/.claude/agents/upstream-compat-reviewer.md" \
    -X PUT -f "message=chore(automation): add upstream-compat-reviewer subagent [skip ci]" \
    -f "content=$CONTENT" -f "branch=feature/MacOS-post-install"
else
  gh api "repos/diazMelgarejo/AlphaClaw/contents/.claude/agents/upstream-compat-reviewer.md" \
    -X PUT -f "message=chore(automation): add upstream-compat-reviewer subagent [skip ci]" \
    -f "content=$CONTENT" -f "sha=$SHA" -f "branch=feature/MacOS-post-install"
fi
echo "✅ upstream-compat-reviewer pushed"
```

---

## Task 9: Skills + Subagent — Perpetua-Tools

- [ ] **Step 9.1: Push agent-run skill**

```bash
CONTENT=$(base64 << 'EOF'
---
name: agent-run
description: Launch a Perpetua-Tools agent with LM Studio endpoint validation and env setup
disable-model-invocation: true
---

Launch steps:

**1. Verify .env.lmstudio exists:**
```bash
[[ -f .env.lmstudio ]] || python3 ~/.openclaw/scripts/discover.py --force
cat .env.lmstudio | grep LM_STUDIO
```

**2. Validate Win endpoint is reachable:**
```bash
source .env.lmstudio 2>/dev/null || true
curl -s --connect-timeout 3 "$LM_STUDIO_WIN_ENDPOINTS/v1/models" \
  | python3 -c "import sys,json; d=json.load(sys.stdin); print(len(d['data']), 'models on Win')"
```
If curl fails → run `python3 ~/.openclaw/scripts/discover.py --force` and retry once.

**3. Launch:**
```bash
set -a && source .env && source .env.lmstudio && set +a
python agent_launcher.py "$@"
```
EOF
)
gh api "repos/diazMelgarejo/Perpetua-Tools/contents/.claude/skills/agent-run/SKILL.md" \
  -X PUT -f "message=chore(automation): add agent-run skill [skip ci]" \
  -f "content=$CONTENT" -f "branch=main"

CONTENT=$(base64 << 'EOF'
---
name: model-routing-check
description: Verify LM Studio endpoint reachability and routing table validity before any agent dispatch
user-invocable: false
---

Before dispatching any agent:

1. Check Mac endpoint: `curl -s --connect-timeout 3 http://localhost:1234/v1/models | python3 -c "import sys,json; print('Mac OK:', len(json.load(sys.stdin)['data']), 'models')"`
2. Check Win endpoint: `curl -s --connect-timeout 3 "$LM_STUDIO_WIN_ENDPOINTS/v1/models" | python3 -c "import sys,json; print('Win OK:', len(json.load(sys.stdin)['data']), 'models')"`
3. Cross-check config/routing.yml task_types against config/models.yml role assignments
4. If either endpoint is down: log warning but continue with available endpoint only. Do NOT abort.
5. Report: which endpoints are live, which task_types are fully routable
EOF
)
gh api "repos/diazMelgarejo/Perpetua-Tools/contents/.claude/skills/model-routing-check/SKILL.md" \
  -X PUT -f "message=chore(automation): add model-routing-check skill [skip ci]" \
  -f "content=$CONTENT" -f "branch=main"
echo "✅ Perpetua-Tools skills pushed"
```

- [ ] **Step 9.2: Push api-validator subagent**

```bash
CONTENT=$(base64 << 'EOF'
---
name: api-validator
description: Validate Perplexity API and LM Studio API response schemas against implementation_templates.json. Flag new models and expired keys.
---

You are an API schema validator for Perpetua-Tools.

Run in order:

1. **Check LM Studio schema:**
```bash
source .env.lmstudio 2>/dev/null || true
curl -s "$LM_STUDIO_WIN_ENDPOINTS/v1/models" | python3 -c "
import sys, json
d = json.load(sys.stdin)
assert 'data' in d, 'missing data key'
print('Win models:', [m['id'] for m in d['data']])
"
```

2. **Cross-check against config/models.yml:**
Any model returned by /v1/models that is NOT in config/models.yml should be flagged as NEW.

3. **Check Perplexity key (if set):**
```bash
[[ -n "$PERPLEXITY_API_KEY" ]] && python3 scripts/test_perplexity.py --validate 2>&1 | tail -5
```

4. **Check implementation_templates.json references:**
```bash
python3 -c "
import json
templates = json.load(open('implementation_templates.json'))
print('Template keys:', list(templates.keys())[:10])
"
```

Report: any schema mismatches, new models available, expired/invalid keys.
EOF
)
SHA=$(gh api "repos/diazMelgarejo/Perpetua-Tools/contents/.claude/agents/api-validator.md" --jq '.sha' 2>/dev/null || echo "")
if [[ -z "$SHA" ]]; then
  gh api "repos/diazMelgarejo/Perpetua-Tools/contents/.claude/agents/api-validator.md" \
    -X PUT -f "message=chore(automation): add api-validator subagent [skip ci]" \
    -f "content=$CONTENT" -f "branch=main"
else
  gh api "repos/diazMelgarejo/Perpetua-Tools/contents/.claude/agents/api-validator.md" \
    -X PUT -f "message=chore(automation): add api-validator subagent [skip ci]" \
    -f "content=$CONTENT" -f "sha=$SHA" -f "branch=main"
fi
echo "✅ api-validator pushed"
```

---

## Task 10: Skills + Subagent — orama-system

- [ ] **Step 10.1: Push ecc-sync skill (promote from command)**

```bash
CONTENT=$(base64 << 'EOF'
---
name: ecc-sync
description: Post-merge ECC Tools sync — run after any ECC Tools PR merges into orama-system
disable-model-invocation: true
---

Run immediately after any ECC Tools PR is merged:

```bash
git pull origin main

# In Claude Code:
/instinct-import .claude/homunculus/instincts/inherited/orama-system-instincts.yaml
/instinct-status

git add -A
git commit -m "chore(ecc): post-merge instinct import sync $(date +%Y-%m-%d)"
git push origin main
```

If `/instinct-import` is unavailable: check that ECC Tools MCP is running, or run the
instinct import script directly: `python .claude/homunculus/import_instincts.py`

Related: `.claude/lessons/LESSONS.md` · `.claude/commands/ecc-sync.md` (legacy command alias)
EOF
)
gh api "repos/diazMelgarejo/orama-system/contents/.claude/skills/ecc-sync/SKILL.md" \
  -X PUT -f "message=chore(automation): promote ecc-sync to skill [skip ci]" \
  -f "content=$CONTENT" -f "branch=main"

CONTENT=$(base64 << 'EOF'
---
name: agent-methodology
description: orama-system 5-stage problem-solving methodology (ὅραμα). Claude-only background knowledge.
user-invocable: false
---

The orama-system methodology — 5 stages:

**1. Crystallize** — Distill to the irreducible core. What EXACTLY must be solved? What constraints cannot be violated?

**2. Architect** — Map the solution space. Identify critical path. Choose the minimal approach.

**3. Execute** — Implement with precision. One task at a time. Verify each step before the next.

**4. Refine** — Compare output against crystallized problem. Does it solve what was actually asked?

**5. Verify** — Independent check: would a fresh agent, given only the original problem and this output, agree it is solved?

Apply to every non-trivial task. Skip no stages. The crystallizer subagent handles stage 1 when the problem is complex.
EOF
)
gh api "repos/diazMelgarejo/orama-system/contents/.claude/skills/agent-methodology/SKILL.md" \
  -X PUT -f "message=chore(automation): add agent-methodology skill (Claude-only) [skip ci]" \
  -f "content=$CONTENT" -f "branch=main"
echo "✅ orama-system skills pushed"
```

- [ ] **Step 10.2: Push crystallizer subagent**

```bash
CONTENT=$(base64 << 'EOF'
---
name: crystallizer
description: Stage 1 of the orama-system methodology — distill a complex problem to its irreducible core
---

You are the Crystallizer — stage 1 of the orama-system 5-stage methodology.

Given a complex problem, return its irreducible core using this exact format:

```
PROBLEM CORE:
<One sentence — the exact thing that must be solved. No qualifiers.>

HARD CONSTRAINTS:
- <constraint that cannot be violated>
- <constraint that cannot be violated>

NON-CONSTRAINTS (appear to constrain, but don't):
- <thing that can be varied freely>

WHAT SUCCESS LOOKS LIKE:
<Specific, measurable outcome — not "the user is happy">

WHAT THIS IS NOT:
<Adjacent problem that must NOT be solved here>
```

Rules:
- PROBLEM CORE must be one sentence. If you need two, split into two problems.
- Every word in PROBLEM CORE costs reasoning budget in subsequent stages. Cut ruthlessly.
- NON-CONSTRAINTS must include at least one item — every problem has them.
EOF
)
SHA=$(gh api "repos/diazMelgarejo/orama-system/contents/.claude/agents/crystallizer.md" --jq '.sha' 2>/dev/null || echo "")
if [[ -z "$SHA" ]]; then
  gh api "repos/diazMelgarejo/orama-system/contents/.claude/agents/crystallizer.md" \
    -X PUT -f "message=chore(automation): add crystallizer subagent [skip ci]" \
    -f "content=$CONTENT" -f "branch=main"
else
  gh api "repos/diazMelgarejo/orama-system/contents/.claude/agents/crystallizer.md" \
    -X PUT -f "message=chore(automation): add crystallizer subagent [skip ci]" \
    -f "content=$CONTENT" -f "sha=$SHA" -f "branch=main"
fi
echo "✅ crystallizer pushed"
```

---

## Task 11: Patch Perpetua-Tools config/ YAMLs

**Files:**
- Modify + push: `Perpetua-Tools:config/devices.yml`
- Modify + push: `Perpetua-Tools:config/models.yml`

- [ ] **Step 11.1: Patch devices.yml (mac .103→.107, win .100→.101)**

```bash
# Fetch current content
python3 - << 'PYEOF'
import subprocess, json, base64, re

def gh_get(path):
    r = subprocess.run(["gh", "api", f"repos/diazMelgarejo/Perpetua-Tools/contents/{path}"],
                       capture_output=True, text=True)
    d = json.loads(r.stdout)
    return base64.b64decode(d["content"].replace("\n","")).decode(), d["sha"]

def gh_put(path, content, sha, msg):
    encoded = base64.b64encode(content.encode()).decode()
    args = ["gh", "api", f"repos/diazMelgarejo/Perpetua-Tools/contents/{path}",
            "-X", "PUT", "-f", f"message={msg}", "-f", f"content={encoded}",
            "-f", "branch=main"]
    if sha:
        args += ["-f", f"sha={sha}"]
    r = subprocess.run(args, capture_output=True, text=True)
    print("OK" if r.returncode == 0 else r.stderr)

content, sha = gh_get("config/devices.yml")
original = content

# Section-aware replacement
content = re.sub(
    r'(- id: "mac-studio".*?lan_ip:\s*")[^"]+(")',
    lambda m: m.group(1) + "192.168.254.107" + m.group(2),
    content, flags=re.DOTALL
)
content = re.sub(
    r'(- id: "win-rtx3080".*?lan_ip:\s*")[^"]+(")',
    lambda m: m.group(1) + "192.168.254.101" + m.group(2),
    content, flags=re.DOTALL
)

if content != original:
    gh_put("config/devices.yml", content, sha, "fix(config): update LM Studio IPs .107/.101 [skip ci]")
    print("devices.yml patched")
else:
    print("devices.yml unchanged (already correct)")
PYEOF
```

- [ ] **Step 11.2: Patch models.yml (default host env var fallbacks)**

```bash
python3 - << 'PYEOF'
import subprocess, json, base64, re

def gh_get(path):
    r = subprocess.run(["gh", "api", f"repos/diazMelgarejo/Perpetua-Tools/contents/{path}"],
                       capture_output=True, text=True)
    d = json.loads(r.stdout)
    return base64.b64decode(d["content"].replace("\n","")).decode(), d["sha"]

def gh_put(path, content, sha, msg):
    encoded = base64.b64encode(content.encode()).decode()
    args = ["gh", "api", f"repos/diazMelgarejo/Perpetua-Tools/contents/{path}",
            "-X", "PUT", "-f", f"message={msg}", "-f", f"content={encoded}",
            "-f", "branch=main"]
    if sha: args += ["-f", f"sha={sha}"]
    r = subprocess.run(args, capture_output=True, text=True)
    print("OK" if r.returncode == 0 else r.stderr)

content, sha = gh_get("config/models.yml")
original = content

content = re.sub(r'(\$\{LM_STUDIO_MAC_ENDPOINT:-)[^}]+(\})',
                 r'\g<1>http://localhost:1234\2', content)
content = re.sub(r'(\$\{LM_STUDIO_WIN_ENDPOINTS:-)[^}:,\n]+',
                 r'\g<1>http://192.168.254.101', content)
# Also patch static IPs outside env var blocks
content = content.replace('"192.168.254.103"', '"192.168.254.107"')
content = content.replace('"192.168.254.100"', '"192.168.254.101"')
content = content.replace('"192.168.254.108"', '"192.168.254.101"')

if content != original:
    gh_put("config/models.yml", content, sha, "fix(config): update LM Studio host defaults .107/.101 [skip ci]")
    print("models.yml patched")
else:
    print("models.yml unchanged")
PYEOF
```

---

## Task 12: Update .gitignore in all 3 repos

- [ ] **Step 12.1: Add .env.lmstudio to all three .gitignore files**

```bash
python3 - << 'PYEOF'
import subprocess, json, base64

repos = [
    ("diazMelgarejo/AlphaClaw", "feature/MacOS-post-install"),
    ("diazMelgarejo/Perpetua-Tools", "main"),
    ("diazMelgarejo/orama-system", "main"),
]

for repo, branch in repos:
    r = subprocess.run(
        ["gh", "api", f"repos/{repo}/contents/.gitignore?ref={branch.replace('/','%2F')}"],
        capture_output=True, text=True
    )
    d = json.loads(r.stdout)
    content = base64.b64decode(d["content"].replace("\n","")).decode()
    sha = d["sha"]

    if ".env.lmstudio" in content:
        print(f"{repo}: .env.lmstudio already ignored")
        continue

    new_content = content.rstrip() + "\n\n# LM Studio auto-discovery (generated by discover.py)\n.env.lmstudio\n"
    encoded = base64.b64encode(new_content.encode()).decode()

    args = ["gh", "api", f"repos/{repo}/contents/.gitignore",
            "-X", "PUT",
            "-f", "message=chore: gitignore .env.lmstudio [skip ci]",
            "-f", f"content={encoded}",
            "-f", f"sha={sha}",
            "-f", f"branch={branch}"]
    r2 = subprocess.run(args, capture_output=True, text=True)
    print(f"{repo}: {'OK' if r2.returncode == 0 else r2.stderr}")
PYEOF
```

---

## Task 13: Update orama-system/setup_macos.py to install discover.py

**Files:**
- Modify + push: `orama-system:setup_macos.py`

- [ ] **Step 13.1: Append discover.py install step to setup_macos.py**

```bash
python3 - << 'PYEOF'
import subprocess, json, base64

r = subprocess.run(
    ["gh", "api", "repos/diazMelgarejo/orama-system/contents/setup_macos.py"],
    capture_output=True, text=True
)
d = json.loads(r.stdout)
content = base64.b64decode(d["content"].replace("\n","")).decode()
sha = d["sha"]

INSTALL_BLOCK = '''

# ── Step N: Install ~/.openclaw/scripts/discover.py ──────────────────────────

def _install_discover_py() -> None:
    """Idempotent: copy discover.py from this repo to ~/.openclaw/scripts/."""
    src = Path(__file__).parent / "scripts" / "discover.py"
    if not src.exists():
        _warn("discover_py", f"source not found at {src} — skipping")
        return
    dest_dir = Path.home() / ".openclaw" / "scripts"
    dest = dest_dir / "discover.py"
    dest_dir.mkdir(parents=True, exist_ok=True)
    # Only copy if content differs (idempotent)
    if dest.exists() and dest.read_bytes() == src.read_bytes():
        _skip("discover_py — already up-to-date")
        return
    import shutil
    shutil.copy2(src, dest)
    dest.chmod(0o755)
    _applied("discover_py", f"installed to {dest}")
    # Also create required state/profiles dirs
    for sub in ("state/backups", "state/archive", "profiles"):
        (Path.home() / ".openclaw" / sub).mkdir(parents=True, exist_ok=True)

'''

# Inject before the main() call at the end of the file
if "_install_discover_py" not in content:
    # Find the last function call in the main block and add before it
    content = content + INSTALL_BLOCK

    # Call the function inside main() — find the main guard
    content = content.replace(
        'if __name__ == "__main__":\n',
        'if __name__ == "__main__":\n    _install_discover_py()\n',
        1
    )

    encoded = base64.b64encode(content.encode()).decode()
    r2 = subprocess.run([
        "gh", "api", "repos/diazMelgarejo/orama-system/contents/setup_macos.py",
        "-X", "PUT",
        "-f", "message=feat(setup): install discover.py to ~/.openclaw/scripts/ [skip ci]",
        "-f", f"content={encoded}",
        "-f", f"sha={sha}",
        "-f", "branch=main"
    ], capture_output=True, text=True)
    print("OK" if r2.returncode == 0 else r2.stderr)
else:
    print("setup_macos.py already has _install_discover_py — skipping")
PYEOF
```

Also, copy `discover.py` into `orama-system/scripts/` so setup_macos.py can find it:

```bash
python3 - << 'PYEOF'
import subprocess, json, base64
from pathlib import Path

discover_content = (Path.home() / ".openclaw/scripts/discover.py").read_text()
encoded = base64.b64encode(discover_content.encode()).decode()

r = subprocess.run(
    ["gh", "api", "repos/diazMelgarejo/orama-system/contents/scripts/discover.py"],
    capture_output=True, text=True
)
sha = json.loads(r.stdout).get("sha", "") if r.returncode == 0 else ""

args = [
    "gh", "api", "repos/diazMelgarejo/orama-system/contents/scripts/discover.py",
    "-X", "PUT",
    "-f", "message=feat(automation): add discover.py — LM Studio hub [skip ci]",
    "-f", f"content={encoded}",
    "-f", "branch=main"
]
if sha: args += ["-f", f"sha={sha}"]
r2 = subprocess.run(args, capture_output=True, text=True)
print("OK" if r2.returncode == 0 else r2.stderr)
PYEOF
```

---

## Task 14: AGENT_RESUME.md + LESSONS.md updates (all 3 repos)

**Files to create + push:**
- `AlphaClaw:AGENT_RESUME.md`
- `Perpetua-Tools:AGENT_RESUME.md`
- `orama-system:AGENT_RESUME.md`
- `orama-system:.claude/lessons/LESSONS.md` (append)

- [ ] **Step 14.1: Push AlphaClaw AGENT_RESUME.md**

```bash
CONTENT=$(base64 << 'EOF'
# AlphaClaw — Agent Resume Guide

**Repo:** diazMelgarejo/AlphaClaw  
**Active branch:** `feature/MacOS-post-install`  
**Last updated:** 2026-04-20

## What this repo is
macOS port of `chrysb/alphaclaw` — the OpenClaw setup harness. Manages the
5-branch strategy (main → pr-4-macos → feature → fix/* → cowork). Also the
dependency base for Perpetua-Tools and orama-system.

## Branch strategy (NEVER DEVIATE)
| Branch | Role |
|--------|------|
| `main` | Upstream mirror — NO local changes |
| `pr-4-macos` | Official upstream PR — no fork-specific code |
| `feature/MacOS-post-install` | All plans, lessons, fork add-ons live here |
| `fix/<name>` | Narrowest-scope upstream branches |

Cherry-pick direction: feature → pr-4-macos (never the reverse). Use `/cherry-pick-down`.
Use `/upstream-compat-reviewer` before any cherry-pick to pr-4-macos.

## LM Studio (auto-discovered) if this is not in PT-repo, copy from AlphaClaw integration?
Run `python3 ~/.openclaw/scripts/discover.py --status` to see live endpoints.
If stale, run `~/.openclaw/scripts/discover.py --force`.
Discovery runs automatically on every Claude Code SessionStart.

## Quick checks
```bash
npm test --reporter=dot       # must pass before any cherry-pick
/macos-port-status            # branch sync summary
```

## Key files
- `CLAUDE.md` — branch rules (authoritative)
- `.claude/skills/` — macos-port-status, cherry-pick-down
- `.claude/agents/upstream-compat-reviewer.md`
- `scripts/discover-lm-studio.sh` — Layer B gossip gate
EOF
)
SHA=$(gh api "repos/diazMelgarejo/AlphaClaw/contents/AGENT_RESUME.md?ref=feature%2FMacOS-post-install" --jq '.sha' 2>/dev/null || echo "")
ARGS=("-X" "PUT" "-f" "message=docs: add AGENT_RESUME.md for future agents [skip ci]" "-f" "content=$CONTENT" "-f" "branch=feature/MacOS-post-install")
[[ -n "$SHA" ]] && ARGS+=("-f" "sha=$SHA")
gh api "repos/diazMelgarejo/AlphaClaw/contents/AGENT_RESUME.md" "${ARGS[@]}"
echo "✅ AlphaClaw AGENT_RESUME.md pushed"
```

- [ ] **Step 14.2: Push Perpetua-Tools AGENT_RESUME.md**

```bash
CONTENT=$(base64 << 'EOF'
# Perpetua-Tools — Agent Resume Guide

**Repo:** diazMelgarejo/Perpetua-Tools  
**Branch:** `main`  
**Last updated:** 2026-04-20

## What this repo is
Multi-agent orchestration framework — routes tasks across local LM Studio models
(Mac + Win), Perplexity API, and Claude API. Local-first, privacy-aware, budget-gated.

## Key entry points
- `agent_launcher.py` — spawns agents by role
- `orchestrator/` — task routing logic
- `config/routing.yml` — task_type → role mapping
- `config/models.yml` — model registry (IPs auto-patched by discover.py)
- `config/devices.yml` — hardware profiles (IPs auto-patched by discover.py)

## LM Studio (auto-discovered)
IPs are managed by `~/.openclaw/scripts/discover.py`. Never hardcode IPs.
Use env vars: `LM_STUDIO_MAC_ENDPOINT`, `LM_STUDIO_WIN_ENDPOINTS` (from `.env.lmstudio`).
Run `source .env.lmstudio` before any manual agent launch.

## Claude Code automation
- SessionStart: discovers endpoints, syncs instincts
- PostToolUse(*.py): ruff lint + pytest smoke
- Skills: `/agent-run`, `model-routing-check` (Claude-only)
- Subagent: `api-validator`

## Quick start for a new agent
```bash
python3 scripts/discover.py --status  # confirm endpoints
source .env && source .env.lmstudio
python agent_launcher.py --list-agents            # see available roles
```

## Dependency: AlphaClaw
This repo depends on AlphaClaw's `feature/MacOS-post-install` for the
macOS setup harness and `setup_macos.py` bootstrap.
EOF
)
SHA=$(gh api "repos/diazMelgarejo/Perpetua-Tools/contents/AGENT_RESUME.md" --jq '.sha' 2>/dev/null || echo "")
ARGS=("-X" "PUT" "-f" "message=docs: add AGENT_RESUME.md for future agents [skip ci]" "-f" "content=$CONTENT" "-f" "branch=main")
[[ -n "$SHA" ]] && ARGS+=("-f" "sha=$SHA")
gh api "repos/diazMelgarejo/Perpetua-Tools/contents/AGENT_RESUME.md" "${ARGS[@]}"
echo "✅ Perpetua-Tools AGENT_RESUME.md pushed"
```

- [ ] **Step 14.3: Push orama-system AGENT_RESUME.md + append LESSONS.md**

```bash
CONTENT=$(base64 << 'EOF'
# orama-system — Agent Resume Guide

**Repo:** diazMelgarejo/orama-system  
**Branch:** `main`  
**Renamed:** orama-system → orama-system (2026-04-20)

## What this repo is
ὅραμα (vision/revelation) — complete agent methodology for solving impossible
problems. Hosts: API server (port 8001), multi-agent MCP servers, 5-stage methodology.

## Mandatory on every session
1. Read `.claude/lessons/LESSONS.md` at session start
2. Write discoveries back to `.claude/lessons/LESSONS.md` before Stop
3. Use the 5-stage methodology (`/agent-methodology`) for non-trivial tasks
4. Run `/ecc-sync` after any ECC Tools PR merges

## LM Studio (auto-discovered)
Managed by `~/.openclaw/scripts/discover.py`. Discovery runs at SessionStart.
Fallback: `~/.openclaw/scripts/discover.py --restore profile:mac-only` if Win is down.

## Claude Code automation
- SessionStart: discovers endpoints, syncs instincts
- PostToolUse(*.py): ruff lint
- Stop: checks LESSONS.md was updated this session
- Skills: `/ecc-sync`, `agent-methodology` (Claude-only)
- Subagent: `crystallizer` (stage 1 of methodology)

## Start the API server
```bash
source .env && source .env.lmstudio
python api_server.py  # listens on port 8001
```

## 5-stage methodology
Crystallize → Architect → Execute → Refine → Verify.
Use `/crystallizer` subagent for complex problem crystallization.
EOF
)
SHA=$(gh api "repos/diazMelgarejo/orama-system/contents/AGENT_RESUME.md" --jq '.sha' 2>/dev/null || echo "")
ARGS=("-X" "PUT" "-f" "message=docs: add AGENT_RESUME.md for future agents [skip ci]" "-f" "content=$CONTENT" "-f" "branch=main")
[[ -n "$SHA" ]] && ARGS+=("-f" "sha=$SHA")
gh api "repos/diazMelgarejo/orama-system/contents/AGENT_RESUME.md" "${ARGS[@]}"
echo "✅ orama-system AGENT_RESUME.md pushed"

# Append to LESSONS.md
python3 - << 'PYEOF'
import subprocess, json, base64, textwrap

r = subprocess.run(
    ["gh", "api", "repos/diazMelgarejo/orama-system/contents/.claude/lessons/LESSONS.md"],
    capture_output=True, text=True
)
d = json.loads(r.stdout)
existing = base64.b64decode(d["content"].replace("\n","")).decode()
sha = d["sha"]

lesson = textwrap.dedent("""

## 2026-04-20 — Auto-discovery & three-repo automation setup

### What was done
- Deployed `~/.openclaw/scripts/discover.py` (Layer A Python hub) + per-repo shell gates
- All 3 repos (AlphaClaw, Perpetua-Tools, orama-system) now auto-discover LM Studio endpoints at SessionStart
- Config idempotency: SHA1 hash comparison — no writes if state unchanged
- 4-tier disaster recovery: live probe → last-good JSON → versioned backup → named profiles
- Backup policy: ≤30 snapshots, 31st auto-deletes oldest; files >30 days archived (not deleted)
- Stale IPs fixed: openclaw.json (.147→localhost, .108→.101), devices.yml (.103→.107, .100→.101)
- Claude Code hooks added to all 3 repos: ruff/pytest/npm-test on edit, lessons check on Stop

### Key invariants learned
- Never hardcode LM Studio IPs — always use `$LM_STUDIO_WIN_ENDPOINTS` from `.env.lmstudio`
- `.env.lmstudio` is auto-generated and gitignored — it's safe to delete and re-run discover.py
- `python3 ~/.openclaw/scripts/discover.py --status` is always the first check when endpoints seem wrong, CHECK?
- The gossip TTL is 5 min — if you need fresh data NOW: `discover.py --force`
- orama-system was renamed from orama-system; the `ORAMA_ENDPOINT` in .env still works

### Recovery reminder
```bash
~/.openclaw/scripts/discover.py --restore profile:mac-only  # Win is down
~/.openclaw/scripts/discover.py --restore latest            # revert last change
~/.openclaw/scripts/discover.py --force                     # re-probe everything
```
""")

if "2026-04-20 — Auto-discovery" not in existing:
    new_content = existing + lesson
    encoded = base64.b64encode(new_content.encode()).decode()
    r2 = subprocess.run([
        "gh", "api", "repos/diazMelgarejo/orama-system/contents/.claude/lessons/LESSONS.md",
        "-X", "PUT",
        "-f", "message=docs(lessons): record auto-discovery setup learnings [skip ci]",
        "-f", f"content={encoded}",
        "-f", f"sha={sha}",
        "-f", "branch=main"
    ], capture_output=True, text=True)
    print("OK" if r2.returncode == 0 else r2.stderr)
else:
    print("LESSONS.md already has this entry — skipping")
PYEOF
```

---

## Task 15: Dry-run verification

- [ ] **Step 15.1: Verify all 3 repos got their files**

```bash
echo "=== AlphaClaw (feature/MacOS-post-install) ===" && \
gh api "repos/diazMelgarejo/AlphaClaw/contents/.claude?ref=feature%2FMacOS-post-install" \
  | python3 -c "import sys,json; [print(' ',f['name']) for f in json.load(sys.stdin)]"

echo "=== Perpetua-Tools (main) ===" && \
gh api "repos/diazMelgarejo/Perpetua-Tools/contents/.claude" \
  | python3 -c "import sys,json; [print(' ',f['name']) for f in json.load(sys.stdin)]"

echo "=== orama-system (main) ===" && \
gh api "repos/diazMelgarejo/orama-system/contents/.claude" \
  | python3 -c "import sys,json; [print(' ',f['name']) for f in json.load(sys.stdin)]"
```

Expected: all 3 show `skills/`, `agents/` (or `skills` entries), `settings.json`.

- [ ] **Step 15.2: Run full discovery dry-run**

```bash
python3 ~/.openclaw/scripts/discover.py --force && \
python3 scripts/discover.py --status
```

Expected:
```
Mac: ✅ localhost:1234 — 5 models
Win: ✅ 192.168.254.101:1234 — 5 models
```

- [ ] **Step 15.3: Verify .env.lmstudio was written to local repos**

```bash
cat "/Users/lawrencecyremelgarejo/Documents/Terminal xCode/claude/OpenClaw/perplexity-api/Perpetua-Tools/.env.lmstudio" 2>/dev/null || echo "Not found (expected if repo not cloned locally)"
```

- [ ] **Step 15.4: Test shell gate idempotency**

```bash
# First call: may trigger Python discover
bash "/Users/lawrencecyremelgarejo/Documents/Terminal xCode/claude/OpenClaw/perplexity-api/Perpetua-Tools/scripts/discover-lm-studio.sh" 2>&1

# Wait 1 second, call again: should exit silently (gossip still fresh)
sleep 1
bash "/Users/lawrencecyremelgarejo/Documents/Terminal xCode/claude/OpenClaw/perplexity-api/Perpetua-Tools/scripts/discover-lm-studio.sh" 2>&1
echo "Second call exit code: $?"
```

Expected: second call exits 0 with no output.

- [ ] **Step 15.5: Test disaster recovery**

```bash
# Simulate both endpoints down: point discover at a dead IP temporarily
python3 - << 'EOF'
import sys; sys.path.insert(0, str(__import__('pathlib').Path.home()/'.openclaw/scripts'))
import discover as D

# Monkeypatch to simulate both endpoints unreachable
D.probe_models = lambda *a, **k: None
async def no_scan(*a, **k): return []
import asyncio
D.scan_subnet_async = lambda *a, **k: asyncio.coroutine(lambda: [])()

# Run — should fall back to tier 2
result = D.run_discovery(force=True)
D.probe_models = __import__('discover').probe_models  # restore
print(f"Exit code: {result}")
src = (D.RECOVERY_SOURCE_TXT).read_text().strip()
print(f"Recovery source: {src}")
assert "tier" in src, "Should have fallen back to a tier"
print("✅ Disaster recovery test passed")
EOF
```

- [ ] **Step 15.6: Confirm memory file updated**

```bash
cat ~/.claude/projects/-Users-lawrencecyremelgarejo-Documents-Terminal-xCode-claude-OpenClaw/memory/project_lan_topology.md
```

Verify: Mac IP shows `.107`, Win shows `.101`, repos show new names.

---

## Self-Review Notes

**Spec coverage check:**
- ✅ Layer B shell gate (Task 5)
- ✅ Layer A Python hub with full idempotency (Task 2)
- ✅ 4-tier disaster recovery (Task 2 + 3)
- ✅ Backup ≤30, 31st deletes oldest, >30 days archived (Task 2 `_enforce_backup_limits`)
- ✅ openclaw.json IP fix (Task 4)
- ✅ devices.yml + models.yml patches (Task 11)
- ✅ All 3 repos get hooks (Task 6)
- ✅ All skills pushed (Tasks 7, 9, 10)
- ✅ All subagents pushed (Tasks 8, 9, 10)
- ✅ .gitignore updated (Task 12)
- ✅ setup_macos.py updated (Task 13)
- ✅ AGENT_RESUME.md + LESSONS.md (Task 14)
- ✅ Dry-run verification (Task 15)

**Idempotency confirmed at 3 levels:**
1. Shell gate: timestamp check — skip if < 5 min
2. Python hub: hash comparison — skip writes if unchanged
3. YAML patches: content comparison — skip if already correct
