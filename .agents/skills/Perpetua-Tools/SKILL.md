---
name: perpetua-tools-conventions
description: Development conventions and patterns for Perpetua-Tools. Python project with mixed commits.
---

# Perplexity Tools Conventions

> Generated from [diazMelgarejo/Perpetua-Tools](https://github.com/diazMelgarejo/Perpetua-Tools) on 2026-03-23

## Overview

This skill teaches Claude the development patterns and conventions used in Perpetua-Tools.

## Tech Stack

- **Primary Language**: Python
- **Architecture**: hybrid module organization
- **Test Location**: separate

## When to Use This Skill

Activate this skill when:
- Making changes to this repository
- Adding new features following established patterns
- Writing tests that match project conventions
- Creating commits with proper message format

## Commit Conventions

Follow these commit message conventions based on 16 analyzed commits.

### Commit Style: Mixed Style

### Prefixes Used

- `feat`
- `fix`
- `modified`
- `docs`

### Message Guidelines

- Average message length: ~64 characters
- Keep first line concise and descriptive
- Use imperative mood ("Add feature" not "Added feature")


*Commit message example*

```text
Fix: pass DELL_SSH_KEY (-i flag) through all SSH/SCP calls in autoresearch_bridge
```

*Commit message example*

```text
feat: add /autoresearch/sync + /autoresearch/gpu_status endpoints to fastapi_app.py
```

*Commit message example*

```text
modified:   orchestrator/fastapi_app.py
```

*Commit message example*

```text
docs(v0.9.0.0): Add comprehensive README with architecture, cost analysis, integration
```

*Commit message example*

```text
Merge branch 'v0.9.4.0' into main — release v0.9.4.0
```

*Commit message example*

```text
Add autoresearch Tasks, AutoResearch Integration, and ECC Tools Runtime Sync to SKILL.md
```

*Commit message example*

```text
feat: add qwen3-coder-14b + qwen3-30b-autoresearch-critic to config/models.yml
```

*Commit message example*

```text
feat: add autoresearch + ml-experiment routes to config/routing.yml
```

## Architecture

### Project Structure: Single Package

This project uses **hybrid** module organization.

### Guidelines

- This project uses a hybrid organization
- Follow existing patterns when adding new code

## Code Style

### Language: Python

### Naming Conventions

| Element | Convention |
|---------|------------|
| Files | snake_case |
| Functions | camelCase |
| Classes | PascalCase |
| Constants | SCREAMING_SNAKE_CASE |

### Import Style: Relative Imports

### Export Style: Named Exports


*Preferred import style*

```typescript
// Use relative imports
import { Button } from '../components/Button'
import { useAuth } from './hooks/useAuth'
```

*Preferred export style*

```typescript
// Use named exports
export function calculateTotal() { ... }
export const TAX_RATE = 0.1
export interface Order { ... }
```

## Common Workflows

These workflows were detected from analyzing commit patterns.

### Feature Development

Standard feature implementation workflow

**Frequency**: ~21 times per month

**Steps**:
1. Add feature implementation
2. Add tests for feature
3. Update documentation

**Files typically involved**:
- `**/*.test.*`
- `**/api/**`

**Example commit sequence**:
```
Add files via upload
feat(v0.9.0.0): Add SKILL.md - model selection, routing, fallback logic
docs(v0.9.0.0): Add comprehensive README with architecture, cost analysis, integration
```

### Add New Api Endpoint

Adds a new API endpoint to the FastAPI application, often for new orchestration features or agent management.

**Frequency**: ~2 times per month

**Steps**:
1. Edit or create endpoint in orchestrator/fastapi_app.py
2. Update config/routing.yml to include new route (if needed)
3. Optionally, update SKILL.md or docs to document the endpoint

**Files typically involved**:
- `orchestrator/fastapi_app.py`
- `config/routing.yml`
- `SKILL.md`

**Example commit sequence**:
```
Edit or create endpoint in orchestrator/fastapi_app.py
Update config/routing.yml to include new route (if needed)
Optionally, update SKILL.md or docs to document the endpoint
```

### Integrate New Agent Or Model

Integrates a new agent or model into the orchestration system, including config and documentation updates.

**Frequency**: ~2 times per month

**Steps**:
1. Add or update entry in config/models.yml
2. Update orchestrator/model_registry.py or related orchestrator files
3. Document in SKILL.md and/or README
4. Optionally, update config/routing.yml if new routes are needed

**Files typically involved**:
- `config/models.yml`
- `orchestrator/model_registry.py`
- `SKILL.md`
- `README.md`
- `config/routing.yml`

**Example commit sequence**:
```
Add or update entry in config/models.yml
Update orchestrator/model_registry.py or related orchestrator files
Document in SKILL.md and/or README
Optionally, update config/routing.yml if new routes are needed
```

### Feature Development With Documentation

Implements a new orchestration or agent feature, with code, documentation, and test updates.

**Frequency**: ~2 times per month

**Steps**:
1. Implement feature in orchestrator/*.py (e.g., new bridge, sync, or tracker modules)
2. Add or update tests (e.g., orchestrator/ecc_tools_sync_test.py)
3. Update documentation (SKILL.md, docs/*.md)
4. Update .gitignore or vendor/.gitkeep if new directories/files are added

**Files typically involved**:
- `orchestrator/*.py`
- `orchestrator/*_test.py`
- `SKILL.md`
- `docs/*.md`
- `.gitignore`
- `vendor/.gitkeep`

**Example commit sequence**:
```
Implement feature in orchestrator/*.py (e.g., new bridge, sync, or tracker modules)
Add or update tests (e.g., orchestrator/ecc_tools_sync_test.py)
Update documentation (SKILL.md, docs/*.md)
Update .gitignore or vendor/.gitkeep if new directories/files are added
```


## Best Practices

Based on analysis of the codebase, follow these practices:

### Do

- Use snake_case for file names
- Prefer named exports

### Don't

- Don't deviate from established patterns without discussion

---

*This skill was auto-generated by [ECC Tools](https://ecc.tools). Review and customize as needed for your team.*
