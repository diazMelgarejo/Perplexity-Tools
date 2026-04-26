---
name: self-improve
version: 1.0.0
description: Crystallize session learnings into LESSONS.md and instincts. Runs automatically at session end (Option C — proposes updates, commits only after user approval). Also invocable on-demand.
user-invocable: true
trigger: session-end
---

# Self-Improve — v1.0.0

Idempotent session-end skill. Reads what happened, proposes minimal additive updates to the canonical knowledge base, and waits for approval before committing anything.

**Trigger modes (Option C):**
- **Auto**: Claude invokes this at session end without being asked
- **Manual**: User types `/self-improve` at any checkpoint
- **Gate**: Nothing is committed until user explicitly approves the diff

---

## Version Guard (run first)

```python
BUNDLED = '1.0.0'
# Skip write if installed version is already newer
def _ver(path):
    import pathlib
    for line in pathlib.Path(path).read_text().splitlines():
        if line.strip().startswith("version:"):
            return tuple(int(x) for x in line.split(":",1)[1].strip().strip('"\'').split("."))
    return (0, 0, 0)

skill_path = ".claude/skills/self-improve/SKILL.md"
if _ver(skill_path) >= tuple(int(x) for x in BUNDLED.split(".")):
    print(f"skip — already at {BUNDLED}")
    exit(0)
```

---

## Step 1 — Read Current Knowledge Base

```bash
# Read LESSONS.md (canonical session log)
cat docs/LESSONS.md 2>/dev/null || cat .claude/lessons/LESSONS.md 2>/dev/null

# Read instincts (behavioral patterns)
cat .claude/homunculus/instincts/inherited/Perpetua-Tools-instincts.yaml 2>/dev/null

# Read this session's git log (what actually changed)
git log --oneline -10
```

---

## Step 2 — Extract Session Learnings

From the session just completed, identify:

1. **New facts** — IPs, endpoints, configs confirmed or changed
2. **Patterns discovered** — what worked, what didn't, why
3. **Decisions made** — architectural choices and their rationale
4. **Errors resolved** — root cause + fix pattern for reuse
5. **Skills updated** — which skills changed and why

Format each learning as a dated, concise entry:

```markdown
## [YYYY-MM-DD] <Topic>

- **Fact**: <what is now confirmed true>
- **Pattern**: <reusable approach>
- **Rationale**: <why this was chosen over alternatives>
```

---

## Step 3 — Generate Proposed Diff

Produce a concrete, minimal diff — **additive only, no deletions** from LESSONS.md unless correcting a factual error:

```bash
# Show current tail of LESSONS.md
tail -30 docs/LESSONS.md 2>/dev/null || tail -30 .claude/lessons/LESSONS.md 2>/dev/null
```

Compose the proposed addition. Show it to the user clearly:

```
=== PROPOSED ADDITION TO docs/LESSONS.md ===

## [YYYY-MM-DD] <Session Summary>

<entries>

=== END PROPOSAL ===
```

---

## Step 4 — User Approval Gate (HARD STOP)

**Do NOT commit or write anything until user explicitly approves.**

Present:
```
Self-improve proposal ready.

Options:
  A) Approve and commit — write to LESSONS.md + git commit
  B) Edit first — show me the text so I can revise
  C) Skip — don't save this session (discard)

Which? (A/B/C)
```

- If **A**: proceed to Step 5
- If **B**: show raw text, accept edits, re-present for approval
- If **C**: exit without writing anything

---

## Step 5 — Write and Commit (only after approval)

```bash
# Append to canonical LESSONS.md
cat >> docs/LESSONS.md << 'ENTRY'

## [YYYY-MM-DD] <Session Title>

<approved content>
ENTRY

# Stage and commit
git add docs/LESSONS.md
git commit -m "docs(lessons): crystallize session learnings [self-improve]

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>"

# Push
git push origin $(git branch --show-current)
echo "Session learnings committed and pushed."
```

---

## Step 6 — Instincts Update (optional)

If the session revealed a strong new behavioral pattern that belongs in the instincts file:

```bash
# Check current instincts
cat .claude/homunculus/instincts/inherited/Perpetua-Tools-instincts.yaml 2>/dev/null | tail -20
```

Propose the addition. Present separately for approval (same A/B/C gate). Only update if:
- The pattern is reusable across many future sessions
- It's not already covered
- It's concrete and actionable (not vague)

---

## Idempotency Rules

- Never duplicate an entry already in LESSONS.md (check for duplicate dates/topics first)
- Never overwrite existing entries — append only
- Never bump the skill version number from inside the skill itself
- If running multiple times in one session, only the last run's learnings are committed

---

## Session-End Auto-Trigger

Claude should invoke this skill proactively when:
- The user says "we're done", "wrap up", "that's it for today", "end session"
- The conversation is naturally concluding after a major task set
- The user asks to save progress

Claude should NOT invoke without asking if:
- The session was exploratory/experimental and produced no stable facts
- The user has already run `/self-improve` in this session
