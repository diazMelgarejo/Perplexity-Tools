"""Tests for Cursor cloud commit-attribution guard scripts."""
from __future__ import annotations

import base64
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STRIP_HOOK = ROOT / "scripts/git/hooks/commit-msg.strip-coauthor"


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
    script = ROOT / "scripts/git/check_commit_message.sh"
    for body, label in (
        ("feat: x\n\nCo-authored-by: Codex <codex@openai.com>\n", "codex"),
        ("feat: x\n\nCo-authored-by: Cursor <cursoragent@cursor.com>\n", "cursor"),
    ):
        msg = tmp_path / f"msg-{label}"
        msg.write_text(body, encoding="utf-8")
        subprocess.run(["bash", str(script), str(msg)], check=True, cwd=ROOT)


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
