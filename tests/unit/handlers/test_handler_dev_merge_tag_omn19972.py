# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""OMN-19972: one definition of the internal-sibling dev merge tag rule.

The dep-provenance gate, the internal-sibling-pins check and the nightly
dev-tag train each held their own copy of ``dev-<14 digits>-<12 hex>``, and the
copies disagreed (two used ``re.match``, which lets a trailing newline through).
All three now import the stdlib-only rule in ``handler_dev_merge_tag``, and this
file holds that rule equal to omnibase_core's first-party ref contract.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

import pytest
from omnibase_core.validation.validator_first_party_ref import dev_tag_pattern

from omniclaude.handlers.handler_dev_merge_tag import (
    DEV_MERGE_TAG_PATTERN,
    dev_merge_tag_stamp,
    is_dev_merge_tag,
)

pytestmark = pytest.mark.unit

_ROOT = Path(__file__).resolve().parents[3]
# The tail every spelling of the rule carries, with or without the stamp group.
_RULE_TAIL = re.compile(r"\{14\}\)?-\[0-9a-f\]\{12\}")
_DEV_TAG = "dev-20261019090050-c330f5a7d597"
_INVALID_TAGS = (
    "dev-20261019090050-c330f5a7d597\n",
    "dev-20261019090050-C330F5A7D597",
    "dev-20261019090050-c330f5a7d59",
    "dev-2026101909005-c330f5a7d597",
    "v0.47.52",
    "dev-latest",
    "",
)


def test_accept_dev_merge_tag_and_extract_stamp() -> None:
    assert dev_merge_tag_stamp(_DEV_TAG) == "20261019090050"
    assert is_dev_merge_tag(_DEV_TAG)


@pytest.mark.parametrize("tag", _INVALID_TAGS)
def test_refuse_invalid_dev_merge_tag(tag: str) -> None:
    assert dev_merge_tag_stamp(tag) is None
    assert not is_dev_merge_tag(tag)


def test_rule_matches_omnibase_core_contract() -> None:
    core_pattern = dev_tag_pattern()
    assert (
        re.sub(r"\(\?P<stamp>(\[0-9\]\{14\})\)", r"\1", DEV_MERGE_TAG_PATTERN)
        == core_pattern
    )
    core_re = re.compile(core_pattern)
    for tag in (_DEV_TAG, *_INVALID_TAGS):
        assert is_dev_merge_tag(tag) == (core_re.fullmatch(tag) is not None), tag


def test_dev_merge_tag_has_one_definition() -> None:
    definitions = {
        path.relative_to(_ROOT)
        for directory in ("src", "scripts")
        for path in (_ROOT / directory).rglob("*.py")
        if _RULE_TAIL.search(path.read_text(encoding="utf-8"))
    }
    assert definitions == {Path("src/omniclaude/handlers/handler_dev_merge_tag.py")}


@pytest.mark.parametrize(("tag", "returncode"), [(_DEV_TAG, 0), ("v0.47.52", 1)])
def test_gate_needs_only_stdlib_and_src(
    tmp_path: Path, tag: str, returncode: int
) -> None:
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text(
        "[project]\n"
        'name = "omniclaude"\n'
        'version = "0.0.0"\n'
        'dependencies = ["omnibase-core>=0.47.0,<0.48.0"]\n'
        "\n"
        "[tool.uv.sources]\n"
        'omnibase-core = { git = "https://github.com/OmniNode-ai/omnibase_core.git", '
        f'tag = "{tag}" }}\n',
        encoding="utf-8",
    )
    script = _ROOT / "scripts" / "check_dep_provenance.py"
    result = subprocess.run(
        [sys.executable, "-S", str(script), "--pyproject", str(pyproject)],
        env={**os.environ, "PYTHONPATH": str(_ROOT / "src")},
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == returncode, result.stdout + result.stderr


def test_train_imports_with_only_stdlib_and_src() -> None:
    """The sibling-lock-refresh workflow imports the train with a bare python3."""
    result = subprocess.run(
        [
            sys.executable,
            "-S",
            "-c",
            "import sys; sys.path.insert(0, 'scripts'); import relock_git_sources",
        ],
        cwd=_ROOT,
        env={**os.environ, "PYTHONPATH": str(_ROOT / "src")},
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
