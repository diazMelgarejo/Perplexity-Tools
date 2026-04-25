# Paste into orama-system `SKILL.md` (branch `v0.9.4.0`)

Add the following subsection (e.g. after your main methodology sections, or under a “Integrations” heading).

---

## autoresearch Integration (Mode 3 Task Type)

When the coordinating system reports **`task_type`** of **`autoresearch`** or **`ml-experiment`** (from **Perpetua-Tools**):

1. **Defer execution topology** to Perpetua-Tools: `POST /autoresearch/sync` must succeed (`sync_ok == true`) before deep multi-step planning assumes the GPU workspace is ready.
2. **Reasoning layer (this repo)**: apply **CIDF / orama** methodology for hypotheses, critique, and next-step narrative — but **do not** assume cloud models for autoresearch unless the user explicitly overrides (see Perpetua-Tools `SKILL.md` “autoresearch Tasks”).
3. **GPU lock & metrics**: treat **`swarm_state.md`** (IDLE/BUSY) and **`log.txt` / `val_bpb`** as the source of truth for whether a run is active and whether metrics are valid.
4. **Cross-repo stack**: Perpetua-Tools (orchestrator) → orama-system (reasoning) → ECC Tools → uditgoenka/autoresearch (Claude Code plugin loop) → GPU substrate (optional, via autoresearch_bridge.py for ML experiments).

For local setup work inside Perpetua-Tools, the Perplexity client now exposes optional `base_url` and `timeout` overrides, and the smoke-test script accepts the same values:

```bash
python scripts/test_perplexity.py --validate --base-url https://api.perplexity.ai --timeout 30
```

---

This file is a **copy-paste helper** only; edit **orama-system** in its own repository.
