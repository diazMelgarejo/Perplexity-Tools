#orama-system Lessons

This file is the high-signal summary of what we have learned so far while turning orama-system into a clean delegate and methodology layer in the PT-first stack.

## Core role

- orama-system is the reasoning and execution layer, not the orchestration authority.
- The repo should remain stateless at runtime. PT decides gateway, routing, and lifecycle; UTS applies the resolved state and exposes execution interfaces.

## Architecture lessons

- Thin delegation is more robust than duplicated control logic. `start.sh` should invoke PT, read the resolved payload, and launch only what PT says is ready.
- Gateway decision authority should not be split. `openclaw_bootstrap.py` is safest when it only applies PT-provided `openclaw.json` values and prepares local workspaces.
- `api_server.py` works best as a stateless interface plus shared-state reader. It should report runtime state, not invent it.

## Migration lessons

- Cross-repo migrations need a repaired baseline first. An empty orchestrator implementation and stale import paths make larger architecture work much riskier than it looks.
- PT-to-UTS integration is easiest to reason about when the contract is concrete. Reading a runtime payload is clearer and more testable than inferring behavior from ad hoc environment variables.
- Repeated startup must be idempotent. Running `start.sh` again should reuse the current gateway and config unless real drift is detected.

## Bootstrap and runtime lessons

- Commandeer-first remains the correct daemon pattern. If a compatible gateway already answers on any candidate port, reuse it and do not restart it.
- Local application is separate from lifecycle management. Writing `~/.openclaw/openclaw.json` and ensuring agent workspaces are valid UTS responsibilities once PT has already resolved runtime.
- Visible preflight matters. Users should be able to tell whether the system is waiting on PT bootstrap, applying config, or starting distributed workers.

## Reliability lessons

- Bootstrap subprocesses must stream output. Hidden output makes install and startup failures much harder to diagnose.
- npm-installed binaries can exist without execute bits. Permission handling has to include both execute-bit repair and explicit `PermissionError` handling.
- State files need shape discipline. Tracker records and routing data must not be mixed, and typed loads need structure guards before unpacking.
- Bulk replacement work is risky around import-path refactors. Import strings, filenames, docs, and shell commands must be reviewed separately before automated replacement.

## Testing and CI lessons

- Tests should import from the real package layout. The move from old `multi_agent` paths to `bin/shared` and `bin/agents` required test repairs before any migration could be trusted.
- Top-level script imports can fail in CI even when they work locally. Explicit pytest `pythonpath = ["."]` keeps tests such as `test_openclaw_bootstrap.py` stable on GitHub Actions.
- CI dependency refactors need parity checks. Replacing explicit installs with extras only works when the extras group contains every required test and build dependency.
- Cross-repo contract tests are worth the effort. Runtime-state and bootstrap tests catch delegate regressions early.

## Current operating rules

- PT is authoritative for gateway discovery, route choice, topology, and readiness.
- UTS should only apply PT-resolved config, expose runtime state, and execute methodology-driven work.
- Any future change that pulls routing logic back into UTS should be treated as architectural drift and justified explicitly.
