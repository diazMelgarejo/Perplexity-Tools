---
name: ecc-sync
description: Mandatory post-merge workflow — run after any ECC Tools PR is merged into this repo.
---

# /ecc-sync — ECC Post-Merge Sync

Run this immediately after merging any ECC Tools PR.

## Steps

```bash
# 1. Pull latest main
git pull origin main
```

Then in Claude Code:

```
/instinct-import .claude/homunculus/instincts/inherited/Perpetua-Tools-instincts.yaml
/instinct-status
```

Then commit any changes the import produced:

```bash
git add -A
git commit -m "chore(ecc): post-merge instinct import sync $(date +%Y-%m-%d)"
git push origin main
```

## What this does

- Loads the 14+ repo-specific continuous-learning-v2 instincts into your local homunculus
- Makes ECC-learned patterns available for the current session and all future sessions
- Keeps the instinct store in sync with the repo's ECC bundle version

## Related

- Lessons file: `.claude/lessons/LESSONS.md`
- Instincts YAML: `.claude/homunculus/instincts/inherited/Perpetua-Tools-instincts.yaml`
- Companion repo sync: run the same command in orama-system after merging US ECC PRs
