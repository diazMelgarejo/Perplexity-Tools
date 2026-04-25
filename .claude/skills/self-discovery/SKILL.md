---
name: self-discovery
version: 0.9.9.7
description: Query live state across all 3 repos — versions, branch status, LM Studio endpoints, file manifests. Run whenever you need a situational snapshot of the stack.
user-invocable: true
---

# Self-Discovery  (v0.9.9.7)

> **Idempotency:** This file carries a `version` in its frontmatter. Any script or agent updating this skill must compare versions (semver) and skip the write if the installed version is ≥ `0.9.9.7`.

Query live state across the three-repo stack (AlphaClaw, Perpetua-Tools, orama-system) and the OpenClaw hub.

---

## Version Snapshot

```python
import subprocess, json, base64

repos = [
    ("AlphaClaw",      "feature%2FMacOS-post-install", "package.json"),
    ("Perpetua-Tools", "main",                         "pyproject.toml"),
    ("orama-system",   "main",                         "pyproject.toml"),
]

for repo, branch, f in repos:
    r = subprocess.run(
        ["gh", "api", f"repos/diazMelgarejo/{repo}/contents/{f}?ref={branch}"],
        capture_output=True, text=True
    )
    if r.returncode == 0:
        content = base64.b64decode(json.loads(r.stdout)["content"].replace("\n","")).decode()
        if f == "package.json":
            print(f"{repo}: {json.loads(content).get('version','?')} ({f})")
        else:
            for line in content.splitlines():
                if line.strip().startswith("version"):
                    print(f"{repo}: {line.strip()} ({f})"); break
```

Expected (current baseline):

| Repo | Branch | Version |
|------|--------|---------|
| AlphaClaw | `feature/MacOS-post-install` | `0.9.9.6` |
| Perpetua-Tools | `main` | `0.9.9.7` |
| orama-system | `main` | `0.9.9.7` |

---

## LM Studio Endpoint Status

```bash
python3 ~/.openclaw/scripts/discover.py --status   # current tier + reachability
python3 ~/.openclaw/scripts/discover.py --force    # bypass 5-min TTL, re-probe now
```

Expected when both nodes live:
```
Tier:    1
  mac: ✅ localhost:1234 — N models
  win: ✅ 192.168.254.101:1234 — N models
Source:  tier1
```

---

## File Manifest Check

Verify all automation files across the stack:

```python
import subprocess, json

checks = [
    ("AlphaClaw",      "feature%2FMacOS-post-install", ".claude/settings.json"),
    ("AlphaClaw",      "feature%2FMacOS-post-install", ".claude/skills/macos-port-status"),
    ("AlphaClaw",      "feature%2FMacOS-post-install", ".claude/skills/cherry-pick-down"),
    ("AlphaClaw",      "feature%2FMacOS-post-install", ".claude/agents/upstream-compat-reviewer.md"),
    ("AlphaClaw",      "feature%2FMacOS-post-install", "scripts/discover-lm-studio.sh"),
    ("Perpetua-Tools", "main", ".claude/settings.json"),
    ("Perpetua-Tools", "main", ".claude/skills/agent-run"),
    ("Perpetua-Tools", "main", ".claude/skills/model-routing-check"),
    ("Perpetua-Tools", "main", ".claude/skills/self-discovery"),
    ("Perpetua-Tools", "main", ".claude/agents/api-validator.md"),
    ("Perpetua-Tools", "main", "scripts/discover-lm-studio.sh"),
    ("Perpetua-Tools", "main", "config/devices.yml"),
    ("orama-system",   "main", ".claude/settings.json"),
    ("orama-system",   "main", ".claude/skills/ecc-sync"),
    ("orama-system",   "main", ".claude/skills/agent-methodology"),
    ("orama-system",   "main", ".claude/skills/self-discovery"),
    ("orama-system",   "main", ".claude/agents/crystallizer.md"),
    ("orama-system",   "main", "scripts/discover-lm-studio.sh"),
    ("orama-system",   "main", "scripts/discover.py"),
    ("orama-system",   "main", "scripts/tests/test_discover.py"),
    ("orama-system",   "main", "setup_macos.py"),
]

for repo, branch, path in checks:
    r = subprocess.run(
        ["gh", "api", f"repos/diazMelgarejo/{repo}/contents/{path}?ref={branch}"],
        capture_output=True, text=True
    )
    print(f"  {'✅' if r.returncode == 0 else '❌'} {repo}/{path}")
```

---

## Hub State Files

| Path | Purpose |
|------|---------|
| `~/.openclaw/state/discovery.json` | Live gossip (5-min TTL) |
| `~/.openclaw/state/last_discovery.json` | Last-good snapshot |
| `~/.openclaw/state/recovery_source.txt` | Active tier (tier1–tier4) |
| `~/.openclaw/state/backups/` | Snapshots ≤30; older → archive |
| `~/.openclaw/profiles/lan-full.json` | Tier-4 fallback |
| `~/.openclaw/openclaw.json` | Master config (provider URLs + model lists) |

---

## Disaster Recovery

```bash
python3 ~/.openclaw/scripts/discover.py --restore latest
python3 ~/.openclaw/scripts/discover.py --restore 2026-04-20
python3 ~/.openclaw/scripts/discover.py --restore profile:lan-full
python3 ~/.openclaw/scripts/discover.py --restore profile:mac-only
```

---

## Test Suite

```bash
cd ~/.openclaw/scripts && python3 -m pytest tests/test_discover.py -v
# Expected: 12 passed
```

---

## Skill Version Guard (for scripts/agents updating this file)

```python
import re
from pathlib import Path
from packaging.version import Version  # or manual tuple compare

def _skill_ver(path: Path) -> tuple:
    try:
        for line in path.read_text().splitlines():
            if line.strip().startswith("version:"):
                return tuple(int(x) for x in line.split(":",1)[1].strip().strip('"\' ').split("."))
    except Exception:
        pass
    return (0, 0, 0)

BUNDLED = '0.9.9.7'
installed = _skill_ver(Path(".claude/skills/self-discovery/SKILL.md"))
if installed >= tuple(int(x) for x in BUNDLED.split(".")):
    print(f"  [·] skip  self-discovery skill (installed={'.'.join(map(str,installed))} >= {BUNDLED})")
else:
    # write new version
    ...
```
