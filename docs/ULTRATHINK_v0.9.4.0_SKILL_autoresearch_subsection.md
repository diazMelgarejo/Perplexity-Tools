# Paste into ultrathink-system `SKILL.md` (branch `v0.9.4.0`)

Add the following subsection (e.g. after your main methodology sections, or under a “Integrations” heading).

---

## autoresearch Integration (Mode 3 Task Type)

When the coordinating system reports **`task_type`** of **`autoresearch`** or **`ml-experiment`** (from **Perplexity-Tools**):

1. **Defer execution topology** to Perplexity-Tools: `POST /autoresearch/sync` must succeed (`sync_ok == true`) before deep multi-step planning assumes the GPU workspace is ready.
2. **Reasoning layer (this repo)**: apply **CIDF / ultrathink** methodology for hypotheses, critique, and next-step narrative — but **do not** assume cloud models for autoresearch unless the user explicitly overrides (see Perplexity-Tools `SKILL.md` “autoresearch Tasks”).
3. **GPU lock & metrics**: treat **`swarm_state.md`** (IDLE/BUSY) and **`log.txt` / `val_bpb`** as the source of truth for whether a run is active and whether metrics are valid.
4. **Cross-repo stack**: Perplexity-Tools (orchestrator) → ultrathink-system (reasoning) → ECC Tools (optional parallel executors) → Karpathy autoresearch loop on the GPU host.

---

This file is a **copy-paste helper** only; edit **ultrathink-system** in its own repository.
