"""openclaw_skill_resolver — PT-side resolver for the openclaw-skills folder.

Locates skill SKILL.md files, validates input args against the skill's
YAML frontmatter, and returns a SkillEnvelope that any agent can execute.

The actual procedural work happens in the calling agent (Claude / Hermes /
Gemini / Codex / Cursor / WindSurf / Antigravity / OpenCode / 8gent.dev).
This module is intentionally THIN — it does not run procedures.

Canonical home of skills:
    orama-system/bin/orama-system/skills/openclaw-skills/

See:
    bin/orama-system/skills/openclaw-skills/SKILL.md
    bin/orama-system/skills/openclaw-skills/references/pt-orama-weave.md
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


_DEFAULT_OPENCLAW_SKILLS_ROOT = (
    Path(os.environ.get("ORAMA_SYSTEM_ROOT", ""))
    / "bin"
    / "orama-system"
    / "skills"
    / "openclaw-skills"
)

# The canonical 9 subskill IDs. Add new ones HERE before adding new skill folders.
NINE_SKILLS: frozenset[str] = frozenset(
    {
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
)

# Recursion safety — see references/recursive-spawn-protocol.md
MAX_RECURSION_DEPTH: int = 3


class SkillResolutionError(RuntimeError):
    """Raised when a requested skill cannot be located or validated."""


class RecursionBudgetExceeded(RuntimeError):
    """Raised when spawn depth would exceed MAX_RECURSION_DEPTH."""


@dataclass
class SkillEnvelope:
    """Result returned to the calling agent.

    The agent reads `skill_path`, follows the procedure, and writes back
    a structured response per the skill's Output Contract.
    """

    skill_id: str
    skill_path: Path
    args: dict[str, Any]
    agent_id: str
    openclaw_home: Path
    parent_chain: list[str] = field(default_factory=list)

    @property
    def depth(self) -> int:
        return len(self.parent_chain)

    def to_dict(self) -> "dict[str, Any]":
        """Return a JSON-serialisable dict.

        ``SkillEnvelope`` is a plain ``@dataclass`` — it has no Pydantic
        ``model_dump()``.  Path fields are converted to ``str`` so callers
        can safely JSON-encode the result without a custom encoder.
        """
        return {
            "skill_id": self.skill_id,
            "skill_path": str(self.skill_path),
            "args": self.args,
            "agent_id": self.agent_id,
            "openclaw_home": str(self.openclaw_home),
            "parent_chain": list(self.parent_chain),
            "depth": self.depth,
        }


def _find_skills_root() -> Path:
    """Locate openclaw-skills folder. Honor ORAMA_SYSTEM_ROOT env or walk up."""
    if _DEFAULT_OPENCLAW_SKILLS_ROOT.is_dir():
        return _DEFAULT_OPENCLAW_SKILLS_ROOT
    # Walk up from this file looking for orama-system/bin/orama-system/skills/openclaw-skills
    here = Path(__file__).resolve()
    for ancestor in here.parents:
        candidate = (
            ancestor
            / "orama-system"
            / "bin"
            / "orama-system"
            / "skills"
            / "openclaw-skills"
        )
        if candidate.is_dir():
            return candidate
    raise SkillResolutionError(
        "openclaw-skills folder not found. Set ORAMA_SYSTEM_ROOT or "
        "ensure orama-system/ is a sibling of this repo."
    )


def resolve_skill(
    skill_id: str,
    args: dict[str, Any] | None = None,
    agent_id: str = "unknown",
    openclaw_home: Path | str | None = None,
    parent_chain: list[str] | None = None,
) -> SkillEnvelope:
    """Resolve a skill_id to a SkillEnvelope the agent can execute.

    Raises:
        SkillResolutionError: skill_id not in the canonical 9 or SKILL.md missing
        RecursionBudgetExceeded: parent_chain length >= MAX_RECURSION_DEPTH
    """
    parent_chain = parent_chain or []
    if len(parent_chain) >= MAX_RECURSION_DEPTH:
        raise RecursionBudgetExceeded(
            f"spawn depth {len(parent_chain)} >= max {MAX_RECURSION_DEPTH}; "
            f"chain: {' -> '.join(parent_chain)}"
        )
    if skill_id not in NINE_SKILLS:
        raise SkillResolutionError(
            f"unknown skill_id={skill_id!r}; expected one of {sorted(NINE_SKILLS)}"
        )

    root = _find_skills_root()
    skill_path = root / "skills" / skill_id / "SKILL.md"
    if not skill_path.is_file():
        raise SkillResolutionError(f"SKILL.md not found at {skill_path}")

    home = Path(openclaw_home) if openclaw_home else Path.home() / ".openclaw"

    return SkillEnvelope(
        skill_id=skill_id,
        skill_path=skill_path,
        args=dict(args or {}),
        agent_id=agent_id,
        openclaw_home=home,
        parent_chain=list(parent_chain),
    )


def child_envelope(
    parent: SkillEnvelope, skill_id: str, args: dict[str, Any] | None = None
) -> SkillEnvelope:
    """Create a child SkillEnvelope from a parent, extending parent_chain.

    Use when a skill needs to invoke another skill (e.g., add-channel calls add-secret).
    """
    return resolve_skill(
        skill_id=skill_id,
        args=args,
        agent_id=parent.agent_id,
        openclaw_home=parent.openclaw_home,
        parent_chain=[*parent.parent_chain, parent.skill_id],
    )


__all__ = [
    "NINE_SKILLS",
    "MAX_RECURSION_DEPTH",
    "SkillEnvelope",
    "SkillResolutionError",
    "RecursionBudgetExceeded",
    "resolve_skill",
    "child_envelope",
]
