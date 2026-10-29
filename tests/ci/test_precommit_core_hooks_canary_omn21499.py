# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""T2.6 (OMN-21499): the consumed omnibase_core hooks refuse a canary and write nothing.

This repository takes the end-of-file, staged ``tmp/`` and AI co-author trailer
rules from omnibase_core's ``commit-hygiene`` and ``commit-hygiene-message``
hooks. This test asks the behavioural question and nothing else: run those hooks
through ``pre-commit`` on a throwaway git tree, and check that each defect is
refused and that the tree, the index and the commit message are byte-identical
afterwards. It does not read hook text out of ``.pre-commit-config.yaml``; the
only thing it takes from the config is the pin (repository URL and rev) of the
block that declares the hook, so the hooks under test are the ones this
repository consumes.
"""

from __future__ import annotations

import hashlib
import os
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

pytestmark = pytest.mark.unit

REPO_ROOT = Path(__file__).resolve().parents[2]
CONFIG = REPO_ROOT / ".pre-commit-config.yaml"

HYGIENE_HOOK = "commit-hygiene"
MESSAGE_HOOK = "commit-hygiene-message"
AI_TRAILER = "Co-Authored-By: Claude <noreply@anthropic.com>"


def _consumed_pin() -> tuple[str, str]:
    """The (repo, rev) of the block of this repository's config that declares the hooks."""
    config = yaml.safe_load(CONFIG.read_text(encoding="utf-8"))
    blocks = [
        block
        for block in config["repos"]
        if HYGIENE_HOOK in {hook["id"] for hook in block.get("hooks", [])}
    ]
    assert len(blocks) == 1, f"{HYGIENE_HOOK}: expected one declaring block"
    return blocks[0]["repo"], blocks[0]["rev"]


def _run(argv: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    env = {key: value for key, value in os.environ.items() if key != "GIT_DIR"}
    env.pop("GIT_WORK_TREE", None)
    env["PRE_COMMIT_COLOR"] = "never"
    return subprocess.run(
        argv, cwd=cwd, env=env, capture_output=True, text=True, check=False
    )


def _git(tree: Path, *args: str) -> str:
    result = _run(["git", *args], tree)
    assert result.returncode == 0, result.stderr
    return result.stdout


def _fingerprint(tree: Path, message: Path) -> dict[str, str]:
    """Every working-tree byte, the staged tree, the status and the message file."""
    files = {
        str(path.relative_to(tree)): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(tree.rglob("*"))
        if path.is_file() and ".git" not in path.relative_to(tree).parts
    }
    files["<index tree>"] = _git(tree, "write-tree")
    files["<status>"] = _git(tree, "status", "--porcelain")
    files["<message>"] = hashlib.sha256(message.read_bytes()).hexdigest()
    return files


def _pre_commit(
    config: Path, tree: Path, *args: str
) -> subprocess.CompletedProcess[str]:
    return _run(
        [sys.executable, "-m", "pre_commit", "run", "-c", str(config), *args], tree
    )


def test_canary_commit_is_refused_and_tree_is_byte_identical(tmp_path: Path) -> None:
    repo, rev = _consumed_pin()
    config = tmp_path / "canary-config.yaml"
    config.write_text(
        yaml.safe_dump(
            {
                "repos": [
                    {
                        "repo": repo,
                        "rev": rev,
                        "hooks": [{"id": HYGIENE_HOOK}, {"id": MESSAGE_HOOK}],
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    tree = tmp_path / "tree"
    tree.mkdir()
    _git(tree, "init", "-q")
    # Where git itself writes the message; the core hook refuses a path outside the tree.
    message = tree / ".git" / "COMMIT_EDITMSG"

    # Positive control: a clean tree and a clean message are accepted, so a refusal
    # below cannot come from a hook that refuses everything.
    (tree / "clean.txt").write_bytes(b"alpha\nbeta\n")
    _git(tree, "add", "clean.txt")
    message.write_text("fix(x): y\n\nCo-Authored-By: A Person <a@example.com>\n")
    before = _fingerprint(tree, message)
    result = _pre_commit(config, tree, HYGIENE_HOOK, "--hook-stage", "pre-commit")
    assert result.returncode == 0, result.stdout + result.stderr
    result = _pre_commit(
        config,
        tree,
        MESSAGE_HOOK,
        "--hook-stage",
        "commit-msg",
        "--commit-msg-filename",
        ".git/COMMIT_EDITMSG",
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert _fingerprint(tree, message) == before

    # The canary: no final newline, extra final newlines, a staged tmp/ file and an
    # AI co-author trailer.
    (tree / "no_newline.txt").write_bytes(b"alpha\nbeta")
    (tree / "extra_newline.txt").write_bytes(b"alpha\nbeta\n\n")
    (tree / "tmp").mkdir()
    (tree / "tmp" / "scratch.txt").write_bytes(b"scratch\n")
    _git(tree, "add", "no_newline.txt", "extra_newline.txt", "tmp/scratch.txt")
    message.write_text(f"fix(x): y\n\n{AI_TRAILER}\n", encoding="utf-8")
    before = _fingerprint(tree, message)

    result = _pre_commit(config, tree, HYGIENE_HOOK, "--hook-stage", "pre-commit")
    assert result.returncode != 0, f"canary accepted: {result.stdout}"
    for rule in ("missing_final_newline", "extra_final_newline", "staged_tmp_file"):
        assert rule in result.stdout + result.stderr, f"{rule} not reported"

    result = _pre_commit(
        config,
        tree,
        MESSAGE_HOOK,
        "--hook-stage",
        "commit-msg",
        "--commit-msg-filename",
        ".git/COMMIT_EDITMSG",
    )
    assert result.returncode != 0, f"trailer accepted: {result.stdout}"
    assert "ai_coauthor_trailer" in result.stdout + result.stderr

    assert _fingerprint(tree, message) == before
