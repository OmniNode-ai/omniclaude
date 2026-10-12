# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""No Anthropic key value can enter a workflow (OMN-20967).

No Anthropic key lives in a repository, an Actions variable, an Actions secret or a workflow;
keys resolve through secret store references only. Nothing in this repository refused the
Anthropic key prefix before this test: the secret scans that exist here either do not read it or
run with --only-verified, which passes a key the vendor no longer accepts. This ratchet reads
every file under .github/workflows/, including hostile-reviewer.yml, for the prefix. No allowlist.

The positive control assembles its key-shaped string at test time; nothing key-shaped is spelled
in this file.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

pytestmark = [pytest.mark.unit]

REPO = Path(__file__).resolve().parents[2]
WORKFLOWS = REPO / ".github" / "workflows"
THIS_TEST = "tests/ci/test_anthropic_key_prefix_workflows_omn20967.py"

# Assembled so this file never spells the prefix it forbids elsewhere.
ANTHROPIC_PREFIX = "sk" + "-" + "ant" + "-"


def _workflow_files(root: Path) -> list[Path]:
    return sorted(
        p for p in root.rglob("*") if p.is_file() and p.suffix in (".yaml", ".yml")
    )


def scan_workflows(root: Path) -> list[str]:
    """Every workflow file that spells the Anthropic key prefix."""
    return [
        f"{path.relative_to(root)}: Anthropic key prefix"
        for path in _workflow_files(root)
        if ANTHROPIC_PREFIX in path.read_text(encoding="utf-8", errors="replace")
    ]


def test_workflows_hold_no_anthropic_key_value() -> None:
    files = _workflow_files(WORKFLOWS)
    assert len(files) >= 5, "the workflow scan found too few files to mean anything"
    assert (WORKFLOWS / "hostile-reviewer.yml") in files
    assert scan_workflows(WORKFLOWS) == []


@pytest.mark.parametrize("where", ["env value", "comment", "run line"])
def test_positive_control_a_seeded_key_fails_the_scan(
    tmp_path: Path, where: str
) -> None:
    key = ANTHROPIC_PREFIX + "api03-" + "A" * 40
    body = {
        "env value": f"name: gate\nenv:\n  K: {key}\n",
        "comment": f"# {key}\nname: gate\n",
        "run line": f"name: gate\njobs:\n  j:\n    steps:\n      - run: echo {key}\n",
    }[where]
    (tmp_path / "gate.yml").write_text(body, encoding="utf-8")
    assert scan_workflows(tmp_path) == ["gate.yml: Anthropic key prefix"]


def test_negative_control_a_clean_workflow_passes(tmp_path: Path) -> None:
    (tmp_path / "gate.yml").write_text(
        "name: gate\njobs:\n  j:\n    steps:\n      - run: echo ok\n"
        "        env:\n          T: ${{ secrets.GITHUB_TOKEN }}\n",
        encoding="utf-8",
    )
    assert scan_workflows(tmp_path) == []


def test_the_scan_is_wired_as_a_pre_commit_hook_and_a_ci_step() -> None:
    config = yaml.safe_load(
        (REPO / ".pre-commit-config.yaml").read_text(encoding="utf-8")
    )
    hook_entries = [
        hook["entry"]
        for repo in config["repos"]
        for hook in repo["hooks"]
        if THIS_TEST in hook.get("entry", "")
    ]
    assert len(hook_entries) == 1, "exactly one pre-commit hook runs the key scan"
    ci = (WORKFLOWS / "ci.yml").read_text(encoding="utf-8")
    assert f"pytest {THIS_TEST}" in ci, "ci.yml has no step that runs the key scan"
