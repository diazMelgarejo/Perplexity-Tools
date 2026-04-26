# 01. CI Dependencies — pip extras + pyproject.toml guard

**TL;DR:** Never replace `pip install pkg1 pkg2 pkg3` with `pip install ".[extras]"` without auditing every dropped package into the extras group. `hatchling` must always be in `[test]`.

---

## Root Cause

Shared with orama-system. See: [UTS wiki/01-ci-deps.md](https://github.com/diazMelgarejo/orama-system/blob/main/docs/wiki/01-ci-deps.md)

---

## PT-Specific Verification

```bash
# All required modules must import
python -c "import fastapi, httpx, uvicorn, pydantic, slowapi, pytest, hatchling, build"

# Version consistency check
grep -rn "0\.9\.9\." pyproject.toml orchestrator/__init__.py orchestrator/fastapi_app.py
```

---

## Rules

1. Never replace explicit `pip install` with `.[extras]` without auditing every dropped package
2. `hatchling` MUST always be in `[project.optional-dependencies] test`
3. CI must use `pip install ".[test]"` — never bare `pip install pytest ...`
4. Run `scripts/check_ci_deps.py` on every `.py`, `.yaml`, `.toml` change (pre-commit hook)

---

## PT Canonical Extras Group

```toml
[project.optional-dependencies]
test = [
  "pytest>=8.0.0",
  "pytest-asyncio>=0.23.0",
  "hatchling>=1.26.0",
  "build>=1.2.0",
  "tomli>=2.0.0",
]
```

---

## Related

- [Session log 2026-04-06](../LESSONS.md)
- [UTS/01-ci-deps.md](https://github.com/diazMelgarejo/orama-system/blob/main/docs/wiki/01-ci-deps.md)
