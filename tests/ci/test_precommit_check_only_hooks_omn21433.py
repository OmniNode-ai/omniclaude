# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""T2.6 (OMN-21433): the omniclaude hooks that rewrote files are check-only.

Seven pre-commit hooks of ``.pre-commit-config.yaml`` wrote to the working tree
(validators-to-core plan, Appendix 1 rows omniclaude:267, 492, 934, 942, 950,
1060, 1443). A hook that rewrites a file during a commit leaves the commit
holding bytes nobody reviewed, and a failed hook run changes the tree under the
author. The standing rule is check-only: a defect is refused and the tree is
byte-identical afterwards.

Each test below runs the hook's own ``entry`` from the config, exactly as
pre-commit would (the entry's argv plus the file names), against a canary
defect in a scratch directory, then asserts two things: the hook refused
(non-zero exit), and every byte of the scratch tree is unchanged. A positive
control per hook proves the check passes a clean input, so a refusal cannot
come from an entry that refuses everything.

The two script-backed hooks (``detect-secrets-update`` and
``auto-generate-skill-nodes``) have their check-only mode covered in
``tests/scripts/test_detect_secrets_guard.py`` and
``tests/unit/scripts/test_auto_generate_skill_nodes.py``; here the test pins
that the config invokes them in that mode.
"""

from __future__ import annotations

import hashlib
import os
import re
import shlex
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest
import yaml

pytestmark = pytest.mark.unit

REPO_ROOT = Path(__file__).resolve().parents[2]
CONFIG = REPO_ROOT / ".pre-commit-config.yaml"
UV_WRAPPER = "scripts/uv-run-worktree-safe.sh"

COAUTHOR_TRAILER = "Co-Authored-By: Claude <noreply@anthropic.com>"


def _hook(hook_id: str) -> dict[str, Any]:
    config = yaml.safe_load(CONFIG.read_text(encoding="utf-8"))
    found = [
        hook
        for block in config["repos"]
        for hook in block.get("hooks", [])
        if hook.get("id") == hook_id
    ]
    assert len(found) == 1, f"{hook_id}: expected one hook definition, got {found}"
    return found[0]


def _entry_argv(hook_id: str) -> list[str]:
    entry = _hook(hook_id).get("entry")
    assert entry, f"{hook_id}: no entry; a third-party hook cannot be check-only here"
    return shlex.split(entry)


def _ruff_argv(hook_id: str) -> list[str]:
    """The hook's ruff arguments, run with the ruff of this environment.

    The entry is ``bash scripts/uv-run-worktree-safe.sh ruff <args>``; the
    wrapper only resolves the interpreter, so the arguments after it are what
    the hook decides.
    """
    argv = _entry_argv(hook_id)
    assert argv[:2] == ["bash", UV_WRAPPER], argv
    # --frozen: `uv run` must not rewrite uv.lock while a hook is only checking.
    assert argv[2] == "--frozen", argv
    ruff_args = argv[3:]
    assert ruff_args[0] == "ruff", ruff_args
    binary = shutil.which("ruff")
    prefix = [binary] if binary else [sys.executable, "-m", "ruff"]
    # --no-cache: ruff's own cache directory is a write the hook may make, and
    # the snapshot below compares every byte of the scratch tree.
    subcommand, *rest = ruff_args[1:]
    return [*prefix, subcommand, "--no-cache", *rest]


def _snapshot(root: Path) -> dict[str, str]:
    return {
        str(path.relative_to(root)): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def _run(argv: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    env = {key: value for key, value in os.environ.items() if key != "GIT_DIR"}
    env.pop("GIT_WORK_TREE", None)
    return subprocess.run(
        argv, cwd=cwd, env=env, capture_output=True, text=True, check=False
    )


def _assert_refused_and_untouched(
    argv: list[str], scratch: Path
) -> subprocess.CompletedProcess[str]:
    before = _snapshot(scratch)
    result = _run(argv, scratch)
    assert result.returncode != 0, f"hook accepted the canary: {result.stdout}"
    assert _snapshot(scratch) == before, "hook run changed the working tree"
    return result


def _assert_accepted_and_untouched(argv: list[str], scratch: Path) -> None:
    before = _snapshot(scratch)
    result = _run(argv, scratch)
    assert result.returncode == 0, f"hook refused clean input: {result.stderr}"
    assert _snapshot(scratch) == before


# --- ruff-format (omniclaude:942) -------------------------------------------


def test_ruff_format_refuses_unformatted_file_and_leaves_it_alone(
    tmp_path: Path,
) -> None:
    canary = tmp_path / "canary.py"
    canary.write_text("x=1\n", encoding="utf-8")
    argv = [*_ruff_argv("ruff-format"), str(canary)]
    _assert_refused_and_untouched(argv, tmp_path)


def test_ruff_format_accepts_formatted_file(tmp_path: Path) -> None:
    (tmp_path / "clean.py").write_text("x = 1\n", encoding="utf-8")
    argv = [*_ruff_argv("ruff-format"), str(tmp_path / "clean.py")]
    _assert_accepted_and_untouched(argv, tmp_path)


# --- ruff-fix (omniclaude:950) ----------------------------------------------


def test_ruff_check_refuses_lint_defect_and_leaves_it_alone(tmp_path: Path) -> None:
    canary = tmp_path / "canary.py"
    canary.write_text("import os\n", encoding="utf-8")
    argv = [*_ruff_argv("ruff-fix"), str(canary)]
    _assert_refused_and_untouched(argv, tmp_path)


def test_ruff_check_accepts_clean_file(tmp_path: Path) -> None:
    (tmp_path / "clean.py").write_text("x = 1\n", encoding="utf-8")
    argv = [*_ruff_argv("ruff-fix"), str(tmp_path / "clean.py")]
    _assert_accepted_and_untouched(argv, tmp_path)


# --- end-of-file-fixer (omniclaude:267) -------------------------------------


@pytest.mark.parametrize(
    ("name", "content"),
    [
        ("no_newline.txt", b"alpha\nbeta"),
        ("extra_blank.txt", b"alpha\nbeta\n\n"),
        ("only_newline.txt", b"\n"),
        ("crlf_extra_blank.txt", b"alpha\r\n\r\n"),
        ("only_crlf.txt", b"\r\n"),
    ],
)
def test_end_of_file_check_refuses_and_leaves_file_alone(
    tmp_path: Path, name: str, content: bytes
) -> None:
    (tmp_path / name).write_bytes(content)
    argv = [*_entry_argv("end-of-file-fixer"), name]
    _assert_refused_and_untouched(argv, tmp_path)


def test_end_of_file_check_accepts_single_trailing_newline(tmp_path: Path) -> None:
    (tmp_path / "clean.txt").write_bytes(b"alpha\nbeta\n")
    (tmp_path / "empty.txt").write_bytes(b"")
    (tmp_path / "crlf.txt").write_bytes(b"alpha\r\nbeta\r\n")
    argv = [*_entry_argv("end-of-file-fixer"), "clean.txt", "empty.txt", "crlf.txt"]
    _assert_accepted_and_untouched(argv, tmp_path)


def test_end_of_file_check_keeps_the_workflow_exclude() -> None:
    assert _hook("end-of-file-fixer")["exclude"] == (
        r"\.github/workflows(?:-generated)?/.*\.ya?ml$"
    )


# --- strip-ai-coauthor-trailer (omniclaude:492) -----------------------------


def test_commit_message_with_ai_trailer_is_refused_not_rewritten(
    tmp_path: Path,
) -> None:
    message = tmp_path / "COMMIT_EDITMSG"
    message.write_text(f"fix(x): y\n\n{COAUTHOR_TRAILER}\n", encoding="utf-8")
    argv = [*_entry_argv("strip-ai-coauthor-trailer"), str(message)]
    result = _assert_refused_and_untouched(argv, tmp_path)
    assert "Co-Authored-By" in result.stderr, "refusal must name the trailer"


def test_trailer_check_is_case_insensitive(tmp_path: Path) -> None:
    message = tmp_path / "COMMIT_EDITMSG"
    message.write_text(
        "fix(x): y\n\nco-authored-by: CLAUDE <NoReply@Anthropic.com>\n",
        encoding="utf-8",
    )
    argv = [*_entry_argv("strip-ai-coauthor-trailer"), str(message)]
    _assert_refused_and_untouched(argv, tmp_path)


def test_commit_message_with_human_trailer_passes(tmp_path: Path) -> None:
    message = tmp_path / "COMMIT_EDITMSG"
    message.write_text(
        "fix(x): y\n\nCo-Authored-By: A Person <person@example.com>\n",
        encoding="utf-8",
    )
    argv = [*_entry_argv("strip-ai-coauthor-trailer"), str(message)]
    _assert_accepted_and_untouched(argv, tmp_path)


def test_trailer_hook_stays_a_commit_msg_hook() -> None:
    hook = _hook("strip-ai-coauthor-trailer")
    assert hook["stages"] == ["commit-msg"]
    assert hook.get("pass_filenames", True) is True


# --- clean-output-directory (omniclaude:934) --------------------------------


def test_staged_output_file_is_refused_and_directory_survives(tmp_path: Path) -> None:
    hook = _hook("clean-output-directory")
    staged = "output/artifact.txt"
    assert re.search(hook["files"], staged), "hook must select staged output/ files"
    (tmp_path / "output").mkdir()
    (tmp_path / staged).write_text("artifact\n", encoding="utf-8")
    argv = [*_entry_argv("clean-output-directory"), staged]
    result = _assert_refused_and_untouched(argv, tmp_path)
    assert "output/" in result.stderr


def test_output_hook_does_not_select_other_paths() -> None:
    hook = _hook("clean-output-directory")
    assert not re.search(hook["files"], "src/output/handler.py")
    assert not re.search(hook["files"], "docs/output.md")
    assert hook.get("always_run") is not True


# --- script-backed hooks: the config selects the check-only mode ------------


def test_auto_generate_skill_nodes_hook_runs_in_check_mode() -> None:
    argv = _entry_argv("auto-generate-skill-nodes")
    assert "--check" in argv
    assert "--frozen" in argv, "uv run must not rewrite uv.lock"


def test_detect_secrets_hook_runs_in_check_mode() -> None:
    assert "--check" in _entry_argv("detect-secrets-update")


# --- no rewriting spelling is left in any of the seven entries --------------

WRITING_SPELLINGS = ("--fix", "rm -rf", "perl -i", "sed -i", "git add")
SEVEN = (
    "end-of-file-fixer",
    "strip-ai-coauthor-trailer",
    "clean-output-directory",
    "ruff-format",
    "ruff-fix",
    "detect-secrets-update",
    "auto-generate-skill-nodes",
)


@pytest.mark.parametrize("hook_id", SEVEN)
def test_entry_has_no_writing_spelling(hook_id: str) -> None:
    entry = _hook(hook_id).get("entry", "")
    assert entry, f"{hook_id}: third-party hook with no entry; it rewrites files"
    for spelling in WRITING_SPELLINGS:
        assert spelling not in entry, f"{hook_id}: entry still contains {spelling!r}"
    if hook_id == "ruff-format":
        assert "--check" in entry
