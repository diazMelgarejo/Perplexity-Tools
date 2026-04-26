#!/usr/bin/env python3
"""Hardware policy helper used by existing orama `start.sh` and Portal.

Human entry points remain:
  - orama-system/start.sh --hardware-policy
  - Orama Portal http://localhost:8002
"""
from __future__ import annotations
import argparse, json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
POLICY_PATH = ROOT / "config" / "model_hardware_policy.yml"


def _simple_policy_parse(text: str) -> dict[str, list[str]]:
    parsed: dict[str, list[str]] = {"windows_only": [], "mac_only": [], "shared": []}
    current: str | None = None
    for raw_line in text.splitlines():
        line = raw_line.split("#", 1)[0].rstrip()
        if not line.strip():
            continue
        stripped = line.strip()
        if stripped.endswith(":") and not stripped.startswith("-"):
            key = stripped[:-1]
            current = key if key in parsed else None
            continue
        if current and stripped.startswith("-"):
            value = stripped[1:].strip().strip('"').strip("'")
            if value:
                parsed[current].append(value)
    return parsed


def load_policy() -> dict[str, list[str]]:
    if not POLICY_PATH.exists():
        return {"windows_only": [], "mac_only": [], "shared": []}
    return _simple_policy_parse(POLICY_PATH.read_text(encoding="utf-8"))


def _forbidden(platform: str, policy: dict[str, list[str]]) -> set[str]:
    p = platform.lower().strip()
    if p in {"mac", "macos", "darwin", "lmstudio-mac", "mac-studio"}:
        return {m.lower() for m in policy.get("windows_only", [])}
    if p in {"win", "windows", "lmstudio-win", "win-rtx3080"}:
        return {m.lower() for m in policy.get("mac_only", [])}
    return set()


def check_affinity(model_id: str, platform: str, policy: dict[str, list[str]]) -> tuple[bool, str]:
    forbidden = _forbidden(platform, policy)
    if model_id.lower() in forbidden:
        if platform.lower().startswith("mac"):
            return False, f"[alphaclaw] Fatal: '{model_id}' is NEVER_MAC. Assign to lmstudio-win only."
        return False, f"[alphaclaw] Fatal: '{model_id}' is NEVER_WIN. Assign to lmstudio-mac only."
    return True, ""


def cmd_list() -> int:
    policy = load_policy()
    print("Windows-only (NEVER_MAC):", ", ".join(policy["windows_only"]) or "none")
    print("Mac-only     (NEVER_WIN):", ", ".join(policy["mac_only"]) or "none")
    print("Shared                  :", ", ".join(policy["shared"]) or "none (intentional)")
    return 0


def cmd_check_openclaw() -> int:
    policy = load_policy()
    path = Path.home() / ".openclaw" / "openclaw.json"
    if not path.exists():
        print(f"⚠ {path} not found")
        return 1
    cfg = json.loads(path.read_text(encoding="utf-8"))
    violations: list[str] = []
    for pid, provider in cfg.get("models", {}).get("providers", {}).items():
        if "lmstudio" not in pid.lower():
            continue
        platform = "mac" if "mac" in pid.lower() else "win"
        for model in provider.get("models", []):
            ok, detail = check_affinity(model.get("id", ""), platform, policy)
            if not ok:
                violations.append(f"{pid}: {detail}")
    if violations:
        print("❌ openclaw.json hardware policy violations:")
        for v in violations:
            print(f"  {v}")
        return 1
    print("✅ openclaw.json clean")
    for pid in ["lmstudio-mac", "lmstudio-win"]:
        models = [m["id"] for m in cfg.get("models", {}).get("providers", {}).get(pid, {}).get("models", [])]
        print(f"  {pid}: {models}")
    return 0


def cmd_validate(model_id: str, platform: str) -> int:
    ok, detail = check_affinity(model_id, platform, load_policy())
    if ok:
        print(f"✅ {model_id} → {platform}")
        return 0
    print(f"❌ {detail}")
    return 1


def cmd_filter(models: list[str], platform: str) -> int:
    forbidden = _forbidden(platform, load_policy())
    allowed = [m for m in models if m.lower() not in forbidden]
    removed = [m for m in models if m.lower() in forbidden]
    print(f"Allowed: {allowed}")
    if removed:
        print(f"Removed: {removed}")
    return 0


def main() -> int:
    p = argparse.ArgumentParser(description="Hardware model affinity helper")
    p.add_argument("--list", action="store_true")
    p.add_argument("--check-openclaw", action="store_true")
    p.add_argument("--validate", nargs=2, metavar=("MODEL_ID", "PLATFORM"))
    p.add_argument("--filter", nargs="+")
    p.add_argument("--platform", default="mac")
    args = p.parse_args()
    if args.list:
        return cmd_list()
    if args.check_openclaw:
        return cmd_check_openclaw()
    if args.validate:
        return cmd_validate(args.validate[0], args.validate[1])
    if args.filter:
        return cmd_filter(args.filter, args.platform)
    p.print_help()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
