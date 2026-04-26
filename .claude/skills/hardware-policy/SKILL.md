# Hardware Policy Manager — Skill

Manage hardware-bound model affinity for OpenClaw multi-agent stack.

## When to Use

Use this skill whenever:
- Assigning models to hardware platforms (mac/win)
- Validating `openclaw.json` or LM Studio configurations
- Adding new models to any provider
- Running discovery (`discover.py --force`)

## Key Concepts

- **NEVER_MAC**: models that MUST NOT run on Mac (Windows-only GGUF)
- **NEVER_WIN**: models that MUST NOT run on Windows (Mac MLX / Apple Silicon)
- **shared**: models verified on both platforms (intentionally empty until confirmed)

## Unified Human Surfaces

Do **not** create new human entry points. Use the existing orama CLI and Portal:

```bash
# Existing CLI surface
cd ../orama-system
./start.sh --hardware-policy
./start.sh --status

# Existing GUI surface
./start.sh
# Open Portal: http://localhost:8002
```

The helper script below is implementation detail used by `start.sh`, tests, and agents.

## Internal Helper Commands

```bash
# Check live openclaw.json for violations (called by ./start.sh --hardware-policy)
python scripts/hardware_policy_cli.py --check-openclaw

# List all policy model lists
python scripts/hardware_policy_cli.py --list

# Validate a single model/platform assignment
python scripts/hardware_policy_cli.py --validate "MODEL_ID" mac|win

# Filter a list of models through policy
python scripts/hardware_policy_cli.py --filter model1 model2 --platform mac

# Force re-run discovery (cleans config, re-probes)
python3 ~/.openclaw/scripts/discover.py --force

# Check discovery status
python3 ~/.openclaw/scripts/discover.py --status
```

## Policy Source of Truth

`Perpetua-Tools/config/model_hardware_policy.yml`

All other docs cite this file — do not duplicate policy in markdown.

### Current Policy (2026-04-26)

**NEVER_MAC** (Windows-only): `gemma-4-26b-a4b-it`, `qwen3.5-27b-claude-4.6-opus-reasoning-distilled-v2`

**NEVER_WIN** (Mac-only): `gemma-4-e4b-it`, `qwen3.5-9b-mlx`

**shared**: empty (intentional)

## Enforcement Layers

| Layer | Component | Action |
|-------|-----------|--------|
| L1 | `discover.py` | Filters model lists before writing `openclaw.json` |
| L2 | `agent_launcher.py`, `alphaclaw_manager.py` | Raises `HardwareAffinityError` before spawn |
| L3 | `api_server.py` | Returns HTTP 400 `HARDWARE_MISMATCH` |

## Rules for AI Agents

1. **Never add unverified model IDs** to any policy file or config. Confirm with `discover.py --status` on actual hardware.
2. **Do not use hallucinated model IDs**: `qwen3-coder-14b` and `gemma4:e4b` do NOT exist in this system.
3. **Case-insensitive matching**: policy enforcement is case-insensitive.
4. **Three-layer enforcement**: if one layer fails silently, the next catches it.

## Adding a New Model

1. Run `discover.py --force` to detect models on live hardware
2. Use `--validate MODEL_ID mac` and `--validate MODEL_ID win` to determine platform affinity
3. Add to `config/model_hardware_policy.yml` under appropriate section
4. Re-run `--check-openclaw` to verify
5. Update `hardware/SKILL.md` Role Matrix with Constraint column entry

## Common Fixes

```bash
# Fix contaminated openclaw.json (if violations found)
python3 ~/.openclaw/scripts/discover.py --force
python scripts/hardware_policy_cli.py --check-openclaw

# Remove stale last_discovery and re-probe
rm ~/.openclaw/state/last_discovery.json
python3 ~/.openclaw/scripts/discover.py --force
```

## Portal GUI

Check model validity in the Orama Portal at `http://localhost:8002` under
**Hardware Policy & Safe Defaults**. It exposes:
- Live Mac/Win LM Studio model lists
- Current policy source path
- Violations, if any
- Safe selectable defaults for Mac and Windows
- CLI reminder: `./start.sh --hardware-policy`
