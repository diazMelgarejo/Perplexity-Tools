---
name: add-new-api-endpoint
description: Workflow command scaffold for add-new-api-endpoint in Perpetua-Tools.
allowed_tools: ["Bash", "Read", "Write", "Grep", "Glob"]
---

# /add-new-api-endpoint

Use this workflow when working on **add-new-api-endpoint** in `Perpetua-Tools`.

## Goal

Adds a new API endpoint to the FastAPI application, often for new orchestration features or agent management.

## Common Files

- `orchestrator/fastapi_app.py`
- `config/routing.yml`
- `SKILL.md`

## Suggested Sequence

1. Understand the current state and failure mode before editing.
2. Make the smallest coherent change that satisfies the workflow goal.
3. Run the most relevant verification for touched files.
4. Summarize what changed and what still needs review.

## Typical Commit Signals

- Edit or create endpoint in orchestrator/fastapi_app.py
- Update config/routing.yml to include new route (if needed)
- Optionally, update SKILL.md or docs to document the endpoint

## Notes

- Treat this as a scaffold, not a hard-coded script.
- Update the command if the workflow evolves materially.