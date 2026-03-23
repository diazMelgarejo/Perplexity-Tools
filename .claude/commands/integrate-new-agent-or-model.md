---
name: integrate-new-agent-or-model
description: Workflow command scaffold for integrate-new-agent-or-model in Perplexity-Tools.
allowed_tools: ["Bash", "Read", "Write", "Grep", "Glob"]
---

# /integrate-new-agent-or-model

Use this workflow when working on **integrate-new-agent-or-model** in `Perplexity-Tools`.

## Goal

Integrates a new agent or model into the orchestration system, including config and documentation updates.

## Common Files

- `config/models.yml`
- `orchestrator/model_registry.py`
- `SKILL.md`
- `README.md`
- `config/routing.yml`

## Suggested Sequence

1. Understand the current state and failure mode before editing.
2. Make the smallest coherent change that satisfies the workflow goal.
3. Run the most relevant verification for touched files.
4. Summarize what changed and what still needs review.

## Typical Commit Signals

- Add or update entry in config/models.yml
- Update orchestrator/model_registry.py or related orchestrator files
- Document in SKILL.md and/or README
- Optionally, update config/routing.yml if new routes are needed

## Notes

- Treat this as a scaffold, not a hard-coded script.
- Update the command if the workflow evolves materially.