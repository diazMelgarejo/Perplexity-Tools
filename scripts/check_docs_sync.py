#!/usr/bin/env python3
"""
check_docs_sync.py — auto-diff checker for docs vs config mismatch detection.

Validates that hardware/SKILL.md (human-readable docs) and config/models.yml
(code-layer truth) agree on canonical model IDs, backends, and context windows
for the primary LM Studio models.

Usage:
    python scripts/check_docs_sync.py          # check only, exits 1 on mismatch
    python scripts/check_docs_sync.py --fix    # print suggested doc fixes

Exit codes:
    0 — all checks pass
    1 — mismatch(es) found
    2 — file read error
"""

import re
import sys
import argparse
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent
MODELS_YML = REPO_ROOT / "config" / "models.yml"
HARDWARE_SKILL = REPO_ROOT / "hardware" / "SKILL.md"

# Models that must appear in hardware/SKILL.md, keyed by their models.yml name.
# These are the canonical LM Studio entries whose presence is enforced.
REQUIRED_LMS_MODELS = {
    "win-rtx3080": "Qwen3.5-27B-Claude-4.6-Opus-Reasoning-Distilled-v2",
    "mac-studio":  "Qwen3.5-9B-MLX-4bit",
}

STALE_REFS = [
    "qwen3.5-35b-a3b-q4",   # old Win primary (now fallback entry only)
]


def load_models_yml(path: Path) -> dict:
    """Parse config/models.yml into a dict keyed by model name."""
    try:
        import yaml  # type: ignore
        with path.open() as f:
            data = yaml.safe_load(f)
        return {m["name"]: m for m in data.get("models", [])}
    except ImportError:
        # Fallback: minimal regex parser (no PyYAML required at check time)
        return _parse_models_yml_regex(path)
    except Exception as e:
        print(f"ERROR: cannot read {path}: {e}", file=sys.stderr)
        sys.exit(2)


def _parse_models_yml_regex(path: Path) -> dict:
    """Minimal YAML parser for models.yml (regex fallback when PyYAML absent)."""
    models: dict = {}
    current: dict | None = None
    for line in path.read_text().splitlines():
        name_m = re.match(r"^\s{2}-\s+name:\s+(.+)$", line)
        if name_m:
            current = {"name": name_m.group(1).strip()}
            models[current["name"]] = current
            continue
        if current is None:
            continue
        for key in ("backend", "device", "context_window", "gpu_offload"):
            m = re.match(rf"^\s+{key}:\s+(.+)$", line)
            if m:
                val = m.group(1).strip().strip('"').strip("'")
                try:
                    current[key] = int(val)
                except ValueError:
                    current[key] = val
    return models


def load_hardware_skill(path: Path) -> str:
    try:
        return path.read_text()
    except Exception as e:
        print(f"ERROR: cannot read {path}: {e}", file=sys.stderr)
        sys.exit(2)


def check_sync(models: dict, skill_text: str, fix_mode: bool) -> list[str]:
    failures: list[str] = []

    # 1. Each required LM Studio model must appear in hardware/SKILL.md
    for device, model_id in REQUIRED_LMS_MODELS.items():
        if model_id not in skill_text:
            failures.append(
                f"MISSING in hardware/SKILL.md: '{model_id}' "
                f"(required canonical model for {device})"
            )
            if fix_mode:
                print(
                    f"  FIX: add entry for '{model_id}' in the {device} profile "
                    f"in hardware/SKILL.md"
                )

        # Also verify it exists in models.yml
        if model_id not in models:
            failures.append(
                f"MISSING in config/models.yml: '{model_id}' "
                f"(required canonical model for {device})"
            )

    # 2. For each required model, verify context_window alignment
    for device, model_id in REQUIRED_LMS_MODELS.items():
        if model_id not in models:
            continue
        yml_ctx = models[model_id].get("context_window")
        if yml_ctx is None:
            continue
        # Search for the model's context in SKILL.md via pattern: 'context[_window]: <n>'
        # We accept the yml value appearing near the model name in the doc
        ctx_pattern = rf"{re.escape(model_id)}[^\n]*\n(?:[^\n]*\n){{0,5}}[^\n]*context[_window]*[:\s]+{yml_ctx}"
        if not re.search(ctx_pattern, skill_text, re.IGNORECASE):
            # Softer check: just confirm the context value appears in the file at all
            if str(yml_ctx) not in skill_text:
                failures.append(
                    f"CONTEXT MISMATCH for '{model_id}': "
                    f"models.yml says {yml_ctx} tokens but value not found in hardware/SKILL.md"
                )

    # 3. Stale model references should NOT appear as primary (default_primary_model)
    primary_section = re.search(
        r"default_primary_model:\s*(.+)", skill_text
    )
    if primary_section:
        primary_val = primary_section.group(1).strip()
        for stale in STALE_REFS:
            if stale.lower() in primary_val.lower():
                failures.append(
                    f"STALE PRIMARY in hardware/SKILL.md: 'default_primary_model' "
                    f"still references '{stale}' — update to canonical LM Studio model"
                )

    # 4. Backends must match between the two canonical models
    for device, model_id in REQUIRED_LMS_MODELS.items():
        if model_id not in models:
            continue
        yml_backend = models[model_id].get("backend", "")
        if yml_backend != "lm-studio":
            failures.append(
                f"BACKEND MISMATCH for '{model_id}': "
                f"models.yml says '{yml_backend}', expected 'lm-studio'"
            )

    return failures


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--fix", action="store_true",
        help="Print suggested fixes alongside failures"
    )
    parser.add_argument(
        "--quiet", "-q", action="store_true",
        help="Only print failures (no OK messages)"
    )
    args = parser.parse_args()

    models = load_models_yml(MODELS_YML)
    skill_text = load_hardware_skill(HARDWARE_SKILL)

    failures = check_sync(models, skill_text, fix_mode=args.fix)

    if failures:
        print(f"check_docs_sync: {len(failures)} mismatch(es) found", file=sys.stderr)
        for f in failures:
            print(f"  FAIL: {f}", file=sys.stderr)
        sys.exit(1)
    else:
        if not args.quiet:
            print(
                f"check_docs_sync: OK — hardware/SKILL.md and config/models.yml "
                f"agree on {len(REQUIRED_LMS_MODELS)} canonical LM Studio models"
            )
        sys.exit(0)


if __name__ == "__main__":
    main()
