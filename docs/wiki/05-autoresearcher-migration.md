# 05. AutoResearcher Migration — uditgoenka Plugin + uv sync

**TL;DR:** Primary mode is now the `uditgoenka/autoresearch` Claude Code plugin (runs anywhere). GPU runner is secondary — Verify substrate for ML experiments only. Use `uv sync --dev` not bare `pip install`.

---

## What Changed (2026-04-11)

The autoresearch loop migrated from a hardcoded Python script cloned to a GPU runner to a Claude Code plugin that can run anywhere, with the GPU runner demoted to an optional Verify substrate.

---

## Key Changes

### 1. `AUTORESEARCH_REMOTE` is now an env var

```bash
# .env (not source code)
AUTORESEARCH_REMOTE=https://github.com/uditgoenka/autoresearch.git
AUTORESEARCH_BRANCH=main  # was hardcoded 'master' — now env-configurable
```

### 2. Plugin install (primary mode — idempotent)

```bash
claude plugin marketplace add uditgoenka/autoresearch
claude plugin install autoresearch@autoresearch
```

`install_autoresearch_plugin()` in `autoresearch_bridge.py` handles this idempotently (checks `claude plugin list` first).

### 3. GPU runner is secondary

Still used for `ml-experiment` task types only. Requires:
- SSH access to the GPU runner
- `swarm_state.md` shows `GPU: BUSY` = false before dispatch

### 4. `uv sync --dev` everywhere

```bash
# All bootstrap paths now use:
uv sync --dev
# Never:
pip install uv && uv sync   # old pattern
```

### 5. Valid Windows model names

```
✓  Qwen3.5-27B-Claude-4.6-Opus-Reasoning-Distilled-v2
✗  Qwen3.5-27B-Instruct   ← DOES NOT EXIST — never hardcode this
```

Always verify available models via `GET http://192.168.254.108:1234/v1/models` before using.

### 6. `preflight()` return keys

```python
{
    "plugin_ok": bool,
    "plugin_error": str | None,
    "sync_ok": bool,
    "sha": str | None,
    "error": str | None,
    "swarm_state_initialised": bool,
}
```

---

## Rules

1. **`AUTORESEARCH_REMOTE` must be an env var** — never hardcode fork URLs in source
2. **Plugin install first** — check `claude plugin list` before re-installing
3. **GPU runner: Windows sequential load rule** — never dispatch while `swarm_state.md` shows `GPU: BUSY`
4. **Use `uv sync --dev`** in all bootstrap and CI paths
5. **Never hardcode model names** — query `/v1/models` at runtime

---

## Related

- [Session log 2026-04-11](../LESSONS.md#2026-04-11--claude--autoresearcher-migration-karpathy--uditgoenka-plugin)
- CLAUDE.md § 4 AutoResearcher Integration
