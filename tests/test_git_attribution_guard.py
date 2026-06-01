"""Tests for Cursor cloud commit-attribution guard scripts."""
from __future__ import annotations

import base64
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STRIP_HOOK = ROOT / "scripts/git/hooks/commit-msg.strip-coauthor"
SYNC_PRIVATE = ROOT / "scripts/cursor/sync-private-attribution-from-home.sh"
ORAMA_WRITE = Path("/agent/repos/orama-system/scripts/cursor/write-openclaw-private-attribution.sh")


def _ensure_banned_patterns() -> None:
    patterns = ROOT / ".cursor/private/banned-attribution-patterns"
    if not patterns.is_file():
        if ORAMA_WRITE.is_file():
            subprocess.run(["bash", str(ORAMA_WRITE)], check=True, cwd=ROOT)
        if SYNC_PRIVATE.is_file():
            subprocess.run(["bash", str(SYNC_PRIVATE)], check=True, cwd=ROOT)
    assert patterns.is_file(), "banned-attribution-patterns missing"


def _first_banned_token() -> str:
    _ensure_banned_patterns()
    for line in (ROOT / ".cursor/private/banned-attribution-patterns").read_text(
        encoding="utf-8"
    ).splitlines():
        line = line.split("#", 1)[0].strip()
        if line:
            return line
    raise AssertionError("no banned tokens in pattern file")


def test_strip_coauthor_hook_removes_cursor_trailers(tmp_path):
    legacy_domain = "bettermind" + ".ph"
    msg = tmp_path / "COMMIT_EDITMSG"
    msg.write_text(
        "feat: example\n\n"
        "Co-authored-by: Cursor <cursoragent@cursor.com>\n"
        f"Co-authored-by: cyre <Lawrence@{legacy_domain}>\n",
        encoding="utf-8",
    )
    subprocess.run(
        ["bash", str(STRIP_HOOK), str(msg)],
        check=True,
        cwd=ROOT,
    )
    text = msg.read_text(encoding="utf-8")
    assert "Co-authored-by" not in text
    assert "feat: example" in text


def test_cursor_hooks_id_matches_workspace():
    lib = ROOT / "scripts/git/cursor-hooks-id.sh"
    repo_abs = str(ROOT.resolve())
    out = subprocess.check_output(
        ["bash", "-c", f'source "{lib}" && cursor_hooks_id "{ROOT}"'],
        text=True,
        cwd=ROOT,
    ).strip()
    expected = base64.b64encode(repo_abs.encode()).decode().rstrip("=")
    assert out == expected


def test_check_commit_message_allows_well_known_coauthors(tmp_path):
    _ensure_banned_patterns()
    script = ROOT / "scripts/git/check_commit_message.sh"
    for body, label in (
        ("feat: x\n\nCo-authored-by: Codex <codex@openai.com>\n", "codex"),
        ("feat: x\n\nCo-authored-by: Cursor <cursoragent@cursor.com>\n", "cursor"),
    ):
        msg = tmp_path / f"msg-{label}"
        msg.write_text(body, encoding="utf-8")
        subprocess.run(["bash", str(script), str(msg)], check=True, cwd=ROOT)


def test_check_commit_message_rejects_banned_coauthor_fixture(tmp_path):
    token = _first_banned_token()
    script = ROOT / "scripts/git/check_commit_message.sh"
    msg = tmp_path / "msg-banned-fixture"
    msg.write_text(
        f"feat: x\n\nCo-authored-by: X <{token}@example.invalid>\n",
        encoding="utf-8",
    )
    proc = subprocess.run(
        ["bash", str(script), str(msg)],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    assert proc.returncode != 0


def test_check_identity_rejects_cursor_agent_as_author():
    proc = subprocess.run(
        ["bash", str(ROOT / "scripts/git/check_identity.sh")],
        cwd=ROOT,
        capture_output=True,
        text=True,
        env={
            **dict(__import__("os").environ),
            "GIT_CONFIG_COUNT": "2",
            "GIT_CONFIG_KEY_0": "user.name",
            "GIT_CONFIG_VALUE_0": "Cursor Agent",
            "GIT_CONFIG_KEY_1": "user.email",
            "GIT_CONFIG_VALUE_1": "cursoragent@cursor.com",
        },
    )
    assert proc.returncode != 0
    assert "must not be the git author" in proc.stderr + proc.stdout


def test_check_commit_message_rejects_unknown_gmail(tmp_path):
    script = ROOT / "scripts/git/check_commit_message.sh"
    msg = tmp_path / "msg-bad"
    msg.write_text(
        "feat: x\n\nCo-authored-by: Random <randomperson@gmail.com>\n",
        encoding="utf-8",
    )
    proc = subprocess.run(
        ["bash", str(script), str(msg)],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    assert proc.returncode != 0
