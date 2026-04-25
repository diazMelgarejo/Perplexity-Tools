# Perpetua-Tools — Knowledge Wiki

> **TL;DR for agents:** Read `docs/LESSONS.md` for the session log. Read pages here for deep dives.
> For quick behavioral rules: **[SKILL.md →](../../SKILL.md)**

This wiki organizes hard-won lessons by topic. Each page contains root cause, exact fix, verification commands, and prevention rules. Derived from [docs/LESSONS.md](../LESSONS.md) and cross-linked with the [orama-system wiki](https://github.com/diazMelgarejo/orama-system/blob/main/docs/wiki/README.md).

---

## Index

| # | Page | TL;DR |
| --- | --- | --- |
| 01 | [CI Dependencies](01-ci-deps.md) | pip extras, hatchling mandatory in `[test]`, never drop packages during refactor |
| 02 | [Idempotent Installs](02-idempotent-installs.md) | Execute bits, capture_output=False, runtime model name discovery |
| 03 | [Device Identity & GPU Recovery](03-device-identity.md) | One role per device, 30s crash cooldown, local IP detection |
| 04 | [Gateway Discovery](04-gateway-discovery.md) | Probe before install, commandeer running gateway |
| 05 | [AutoResearcher Migration](05-autoresearcher-migration.md) | uditgoenka plugin primary, GPU runner secondary, uv sync |
| 06 | [Startup & IP Detection](06-startup-ip-detection.md) | stdin deadlock, load_dotenv placement, concurrent asyncio probing |
| 07 | [Multi-Agent Collaboration](07-multi-agent-collab.md) | Version registry, scope claims, no LAN IPs in source, test isolation |
| 08 | [macOS alphaclaw Compat](08-macos-alphaclaw-compat.md) | EACCES fixes, ~/.local/bin pattern, idempotent setup_macos.py |

---

## How to Add a Lesson

1. Append the session entry to `docs/LESSONS.md` (short, dated, agent-tagged)
2. If the lesson warrants a wiki page, create `docs/wiki/NN-topic.md`:

```markdown
# NN. Topic Title

**TL;DR:** One sentence.

---

## Root Cause
...

## Fix
...

## Rules
...

## Related
- [Session log entry](../LESSONS.md#anchor)
- [UTS companion lesson](https://github.com/diazMelgarejo/orama-system/blob/main/docs/wiki/README.md)
```

3. Add a row to the index table above
4. Add `→ [wiki/NN-topic.md](wiki/NN-topic.md)` at the bottom of the LESSONS.md session entry

---

## Cross-Repo Lessons

Some lessons are shared across PT and UTS. Canonical entry lives where the bug was fixed; a cross-reference appears in the companion repo.

| Session | PT Lesson | UTS Companion |
| --- | --- | --- |
| 2026-04-07 | [Idempotent Installs](02-idempotent-installs.md) | [UTS/02](https://github.com/diazMelgarejo/orama-system/blob/main/docs/wiki/02-idempotent-installs.md) |
| 2026-04-07 | [Device Identity](03-device-identity.md) | [UTS/03](https://github.com/diazMelgarejo/orama-system/blob/main/docs/wiki/03-device-identity.md) |
| 2026-04-07 | [Gateway Discovery](04-gateway-discovery.md) | [UTS/04](https://github.com/diazMelgarejo/orama-system/blob/main/docs/wiki/04-gateway-discovery.md) |
| 2026-04-12 | [Multi-Agent Collab](07-multi-agent-collab.md) | [UTS/06](https://github.com/diazMelgarejo/orama-system/blob/main/docs/wiki/06-multi-agent-collab.md) |
| 2026-04-13 | [Startup IP Detection](06-startup-ip-detection.md) | [UTS/07](https://github.com/diazMelgarejo/orama-system/blob/main/docs/wiki/07-startup-ip-detection.md) |
