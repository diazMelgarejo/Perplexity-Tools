"""Tests for openclaw_skill_resolver."""

from __future__ import annotations

from pathlib import Path

import pytest

from orchestrator.openclaw_skill_resolver import (
    MAX_RECURSION_DEPTH,
    NINE_SKILLS,
    SkillResolutionError,
    resolve_skill,
)

# Note: RecursionBudgetExceeded and child_envelope are accessed via importlib.reload
# inside individual tests (e.g., `r.RecursionBudgetExceeded`), so they are NOT imported here.


def test_nine_skills_set_is_canonical() -> None:
    expected = {
        "openclaw-new-agent",
        "openclaw-add-channel",
        "openclaw-add-cron",
        "openclaw-dream-setup",
        "openclaw-add-script",
        "openclaw-add-secret",
        "openclaw-status",
        "openclaw-restart",
        "openclaw-stow",
    }
    assert NINE_SKILLS == frozenset(expected)
    assert len(NINE_SKILLS) == 9


def test_resolve_skill_unknown_id_raises() -> None:
    with pytest.raises(SkillResolutionError, match="unknown skill_id"):
        resolve_skill("openclaw-make-coffee")


def test_resolve_skill_returns_envelope_with_existing_skill(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    # Build a fake skills tree
    skill_dir = (
        tmp_path
        / "bin"
        / "orama-system"
        / "skills"
        / "openclaw-skills"
        / "skills"
        / "openclaw-status"
    )
    skill_dir.mkdir(parents=True)
    skill_md = skill_dir / "SKILL.md"
    skill_md.write_text("---\nname: openclaw-status\n---\n# Probe gateway")
    monkeypatch.setenv("ORAMA_SYSTEM_ROOT", "")  # force walk-up path
    # Re-import to pick up fresh module-level default
    import importlib

    import orchestrator.openclaw_skill_resolver as r

    importlib.reload(r)
    # Monkeypatch _find_skills_root to point at our fake tree
    fake_root = tmp_path / "bin" / "orama-system" / "skills" / "openclaw-skills"
    monkeypatch.setattr(r, "_find_skills_root", lambda: fake_root)

    env = r.resolve_skill(
        "openclaw-status", args={"verbose": True}, agent_id="test-agent"
    )
    assert env.skill_id == "openclaw-status"
    assert env.skill_path == skill_md
    assert env.args == {"verbose": True}
    assert env.agent_id == "test-agent"
    assert env.depth == 0


def test_child_envelope_extends_parent_chain(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    # Build minimal fake tree for two skills
    base = tmp_path / "bin" / "orama-system" / "skills" / "openclaw-skills" / "skills"
    for sid in ("openclaw-add-channel", "openclaw-add-secret"):
        d = base / sid
        d.mkdir(parents=True)
        (d / "SKILL.md").write_text(f"---\nname: {sid}\n---\n# {sid}")

    import importlib

    import orchestrator.openclaw_skill_resolver as r

    importlib.reload(r)
    fake_root = tmp_path / "bin" / "orama-system" / "skills" / "openclaw-skills"
    monkeypatch.setattr(r, "_find_skills_root", lambda: fake_root)

    parent = r.resolve_skill("openclaw-add-channel", agent_id="test-agent")
    child = r.child_envelope(parent, "openclaw-add-secret", args={"name": "my-token"})
    assert child.parent_chain == ["openclaw-add-channel"]
    assert child.depth == 1
    assert child.skill_id == "openclaw-add-secret"
    assert child.agent_id == "test-agent"  # propagated from parent


def test_recursion_budget_enforced(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    d = (
        tmp_path
        / "bin"
        / "orama-system"
        / "skills"
        / "openclaw-skills"
        / "skills"
        / "openclaw-stow"
    )
    d.mkdir(parents=True)
    (d / "SKILL.md").write_text("---\nname: openclaw-stow\n---")

    import importlib

    import orchestrator.openclaw_skill_resolver as r

    importlib.reload(r)
    fake_root = tmp_path / "bin" / "orama-system" / "skills" / "openclaw-skills"
    monkeypatch.setattr(r, "_find_skills_root", lambda: fake_root)

    deep_chain = ["a", "b", "c"]  # already at MAX_RECURSION_DEPTH=3
    assert len(deep_chain) >= MAX_RECURSION_DEPTH
    with pytest.raises(r.RecursionBudgetExceeded) as exc_info:
        r.resolve_skill("openclaw-stow", parent_chain=deep_chain)
    assert "spawn depth 3" in str(exc_info.value)
    assert "max 3" in str(exc_info.value)
