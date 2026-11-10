# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""OMN-21900: omniclaude consumes the core first_party_ref validator by hook id."""

from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
CORE_REPO = "https://github.com/OmniNode-ai/omnibase_core"
HOOK_IDS = ("check-internal-sibling-pins", "check-action-pins")
BASELINE = ".onex/baselines/first_party_ref.yaml"
DEV_TAG = re.compile(r"^dev-[0-9]{14}-[0-9a-f]{12}$")
RUNTIME = (
    "omnibase_core.nodes.node_first_party_tag_inventory_effect.runtime_first_party_ref"
)

pytestmark = pytest.mark.unit


def _hook_rows() -> dict[str, tuple[dict, dict]]:
    config = yaml.safe_load((ROOT / ".pre-commit-config.yaml").read_text("utf-8"))
    return {
        hook["id"]: (repo, hook)
        for repo in config["repos"]
        for hook in repo["hooks"]
        if hook["id"] in HOOK_IDS
    }


def _runtime(root: Path, core_tag: str, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            "uv",
            "run",
            "--no-project",
            "--with",
            f"omnibase-core @ git+{CORE_REPO}@{core_tag}",
            "python",
            "-m",
            RUNTIME,
            "--root",
            str(root),
            *args,
        ],
        capture_output=True,
        text=True,
        check=False,
        timeout=180,
        cwd=root,
    )


def test_both_hook_ids_are_wired_from_core_at_a_dev_merge_tag() -> None:
    rows = _hook_rows()
    assert sorted(rows) == sorted(HOOK_IDS)
    for repo, hook in rows.values():
        assert repo["repo"] == CORE_REPO
        assert DEV_TAG.fullmatch(repo["rev"])
        assert hook["args"] == ["--baseline", BASELINE]
        assert "entry" not in hook


def test_ci_runs_the_validator_with_the_baseline_and_feeds_quality_gate() -> None:
    workflow = yaml.safe_load((ROOT / ".github/workflows/ci.yml").read_text("utf-8"))
    job = workflow["jobs"]["first-party-ref"]
    commands = "\n".join(step.get("run", "") for step in job["steps"])
    # OMN-19612: the validator allows one home per tag literal and reads a literal,
    # so the job runs the hook ids whole-tree at the rev the pre-commit block owns.
    for hook_id in HOOK_IDS:
        assert f"pre-commit run {hook_id} --all-files" in commands
    assert not re.search(r"dev-[0-9]{14}-[0-9a-f]{12}", commands)
    assert "first-party-ref" in workflow["jobs"]["quality-gate"]["needs"]
    rows = _hook_rows()
    assert all(hook["args"] == ["--baseline", BASELINE] for _, hook in rows.values())


def test_pyproject_first_party_sources_name_a_tag_never_a_rev() -> None:
    pyproject = (ROOT / "pyproject.toml").read_text("utf-8")
    for line in pyproject.splitlines():
        if line.lstrip().startswith("#") or "github.com/OmniNode-ai/" not in line:
            continue
        assert not re.search(r"\brev\s*=", line), line
        if "tag =" in line:
            assert DEV_TAG.fullmatch(re.search(r'tag = "([^"]+)"', line)[1]), line


def test_baseline_is_generated_with_a_zero_target_and_no_suppression_marker() -> None:
    text = (ROOT / BASELINE).read_text("utf-8")
    assert "Zero target" in text
    data = yaml.safe_load(text)
    assert data["hook"] == "first_party_ref"
    assert data["entries"]
    assert set(data) == {"schema_version", "hook", "entries"}
    assert all(set(entry) == {"path", "rule", "text"} for entry in data["entries"])
    assert {e["rule"] for e in data["entries"]} <= {
        "third_party_not_sha",
        "cross_repo_ref_not_dev_tag",
        "first_party_not_dev_tag",
        "first_party_ref_two_homes",
        "missing_source",
    }


def test_tree_passes_and_a_reintroduced_sha_rev_is_refused(tmp_path: Path) -> None:
    core_tag = _hook_rows()["check-action-pins"][0]["rev"]
    clean = _runtime(ROOT, core_tag, "--baseline", BASELINE)
    assert clean.returncode == 0, clean.stdout + clean.stderr

    copy = tmp_path / "tree"
    shutil.copytree(ROOT / ".github", copy / ".github")
    shutil.copytree(ROOT / ".onex", copy / ".onex")
    for name in (".pre-commit-config.yaml", "pyproject.toml"):
        shutil.copy(ROOT / name, copy / name)
    config = copy / ".pre-commit-config.yaml"
    config.write_text(
        config.read_text("utf-8").replace(core_tag, "a" * 40, 1), encoding="utf-8"
    )
    canary = _runtime(copy, core_tag, "--baseline", BASELINE)
    assert canary.returncode != 0
    assert "first_party_not_dev_tag" in canary.stdout + canary.stderr


def test_one_more_finding_in_a_baselined_file_is_refused(tmp_path: Path) -> None:
    core_tag = _hook_rows()["check-action-pins"][0]["rev"]
    copy = tmp_path / "tree"
    shutil.copytree(ROOT / ".github", copy / ".github")
    shutil.copytree(ROOT / ".onex", copy / ".onex")
    for name in (".pre-commit-config.yaml", "pyproject.toml"):
        shutil.copy(ROOT / name, copy / name)
    ci = copy / ".github/workflows/ci.yml"
    ci.write_text(
        ci.read_text("utf-8") + "\n      - uses: actions/checkout@v7\n",
        encoding="utf-8",
    )
    canary = _runtime(copy, core_tag, "--baseline", BASELINE)
    assert canary.returncode != 0
    assert "third_party_not_sha" in canary.stdout + canary.stderr
