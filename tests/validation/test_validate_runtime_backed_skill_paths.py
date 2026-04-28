# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""Unit tests for runtime-backed skill path advisory validation (OMN-10239)."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
VALIDATOR = (
    REPO_ROOT / "scripts" / "validation" / "validate_runtime_backed_skill_paths.py"
)

sys.path.insert(0, str(REPO_ROOT / "scripts" / "validation"))
from validate_runtime_backed_skill_paths import (  # noqa: E402
    CHECK_NONCANONICAL_RUNTIME_PATH,
    PATH_DIRECT_HANDLER_CALL,
    PATH_DIRECT_HANDLER_IMPORT,
    PATH_DIRECT_NODE_CLI,
    PATH_DIRECT_TOPIC_PUBLISH,
    PATH_ONEX_NODE,
    PATH_ONEX_RUN_NODE,
    PATH_REPO_LOCAL_RUNTIME_PATH,
    load_manifest,
    scan_skill,
    scan_skills_root,
)


def _write_skill(tmp_path: Path, skill_name: str, surfaces: dict[str, str]) -> Path:
    skill_dir = tmp_path / skill_name
    skill_dir.mkdir()
    for rel_path, content in surfaces.items():
        path = skill_dir / rel_path
        path.write_text(content, encoding="utf-8")
    return skill_dir


def _write_manifest(tmp_path: Path, body: str) -> Path:
    path = tmp_path / "skills_to_market_manifest.yaml"
    path.write_text(body, encoding="utf-8")
    return path


@pytest.fixture
def manifest_path(tmp_path: Path) -> Path:
    return _write_manifest(
        tmp_path,
        """
version: 1
skills:
  runtime_sweep:
    canonical_path: onex_node
    canonical_target: node_runtime_sweep
  merge_sweep:
    canonical_path: onex_run_node
    canonical_target: node_pr_lifecycle_orchestrator
  pr_review_bot:
    canonical_path: onex_run_node
    canonical_target: node_pr_review_bot
  delegate:
    canonical_path: direct_topic_publish
    canonical_target: node_delegation_orchestrator
""".strip()
        + "\n",
    )


@pytest.mark.unit
class TestLoadManifest:
    def test_loads_skill_mapping(self, manifest_path: Path) -> None:
        manifest = load_manifest(manifest_path)
        assert manifest["runtime_sweep"].canonical_path == PATH_ONEX_NODE
        assert manifest["merge_sweep"].canonical_path == PATH_ONEX_RUN_NODE


@pytest.mark.unit
class TestCanonicalPathPasses:
    def test_onex_node_matches_manifest(
        self, tmp_path: Path, manifest_path: Path
    ) -> None:
        skill_dir = _write_skill(
            tmp_path,
            "runtime_sweep",
            {
                "SKILL.md": (
                    "---\n---\n\n"
                    "```bash\nuv run onex node node_runtime_sweep -- --scope all\n```\n"
                )
            },
        )
        manifest = load_manifest(manifest_path)
        findings = scan_skill(skill_dir, manifest["runtime_sweep"])
        assert findings == [], [f.format_line() for f in findings]

    def test_onex_node_wrong_target_emits_finding(
        self, tmp_path: Path, manifest_path: Path
    ) -> None:
        skill_dir = _write_skill(
            tmp_path,
            "runtime_sweep",
            {
                "SKILL.md": (
                    "---\n---\n\n"
                    "```bash\nuv run onex node node_other_target -- --scope all\n```\n"
                )
            },
        )
        manifest = load_manifest(manifest_path)
        findings = scan_skill(skill_dir, manifest["runtime_sweep"])
        assert findings, (
            "Expected finding for canonical path kind with non-canonical target"
        )


@pytest.mark.unit
class TestDirectNodeCliInventory:
    def test_direct_node_cli_is_flagged(
        self, tmp_path: Path, manifest_path: Path
    ) -> None:
        skill_dir = _write_skill(
            tmp_path,
            "merge_sweep",
            {
                "run.sh": (
                    "uv run python -m omnimarket.nodes.node_pr_lifecycle_orchestrator "
                    "--input '{}'\n"
                )
            },
        )
        manifest = load_manifest(manifest_path)
        findings = scan_skill(skill_dir, manifest["merge_sweep"])
        observed = {f.observed_path for f in findings}
        assert PATH_DIRECT_NODE_CLI in observed
        assert all(f.check == CHECK_NONCANONICAL_RUNTIME_PATH for f in findings)

    def test_repo_local_path_reference_is_flagged(
        self, tmp_path: Path, manifest_path: Path
    ) -> None:
        skill_dir = _write_skill(
            tmp_path,
            "merge_sweep",
            {
                "SKILL.md": (
                    "Use omnimarket/src/omnimarket/nodes/node_pr_lifecycle_orchestrator/\n"
                    'cd "${OMNIMARKET_ROOT}" && uv run onex run-node node_pr_lifecycle_orchestrator\n'
                )
            },
        )
        manifest = load_manifest(manifest_path)
        findings = scan_skill(skill_dir, manifest["merge_sweep"])
        observed = {f.observed_path for f in findings}
        assert PATH_REPO_LOCAL_RUNTIME_PATH in observed


@pytest.mark.unit
class TestDirectHandlerInventory:
    def test_run_review_import_and_call_are_flagged(
        self, tmp_path: Path, manifest_path: Path
    ) -> None:
        skill_dir = _write_skill(
            tmp_path,
            "pr_review_bot",
            {
                "SKILL.md": (
                    "from omnimarket.nodes.node_pr_review_bot.workflow_runner import run_review\n"
                    "result = run_review(pr_number=42, repo='OmniNode-ai/omnimarket')\n"
                )
            },
        )
        manifest = load_manifest(manifest_path)
        findings = scan_skill(skill_dir, manifest["pr_review_bot"])
        observed = {f.observed_path for f in findings}
        assert PATH_DIRECT_HANDLER_IMPORT in observed
        assert PATH_DIRECT_HANDLER_CALL in observed


@pytest.mark.unit
class TestTopicPublishInventory:
    def test_noncanonical_direct_topic_publish_is_flagged(
        self, tmp_path: Path, manifest_path: Path
    ) -> None:
        skill_dir = _write_skill(
            tmp_path,
            "merge_sweep",
            {
                "SKILL.md": (
                    "Publish to onex.cmd.omnimarket.pr-lifecycle-start.v1 via the emit daemon.\n"
                    "The skill publishes via the omniclaude emit daemon (`EmitClient`).\n"
                    "emitted = emit_event('merge_sweep.start', envelope)\n"
                )
            },
        )
        manifest = load_manifest(manifest_path)
        findings = scan_skill(skill_dir, manifest["merge_sweep"])
        observed = {f.observed_path for f in findings}
        assert PATH_DIRECT_TOPIC_PUBLISH in observed

    def test_delegate_direct_topic_publish_is_canonical(
        self, tmp_path: Path, manifest_path: Path
    ) -> None:
        skill_dir = _write_skill(
            tmp_path,
            "delegate",
            {
                "SKILL.md": (
                    "Publish to onex.cmd.omniclaude.delegate-task.v1 via the emit daemon.\n"
                    "The skill publishes via the omniclaude emit daemon (`EmitClient`).\n"
                    "emitted = emit_event('delegate.task', envelope)\n"
                )
            },
        )
        manifest = load_manifest(manifest_path)
        findings = scan_skill(skill_dir, manifest["delegate"])
        assert findings == [], [f.format_line() for f in findings]


@pytest.mark.unit
class TestScanSkillsRoot:
    def test_scans_manifest_entries(self, tmp_path: Path, manifest_path: Path) -> None:
        _write_skill(
            tmp_path,
            "runtime_sweep",
            {"SKILL.md": "uv run onex node node_runtime_sweep -- --scope all\n"},
        )
        _write_skill(
            tmp_path,
            "merge_sweep",
            {
                "run.sh": (
                    "uv run python -m omnimarket.nodes.node_pr_lifecycle_orchestrator "
                    "--input '{}'\n"
                )
            },
        )
        manifest = load_manifest(manifest_path)
        result = scan_skills_root(tmp_path, manifest)
        assert result.skills_scanned == 4
        assert result.skills_with_findings >= 1
        assert result.total_findings >= 1


@pytest.mark.unit
class TestCliInterface:
    def _run(self, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(VALIDATOR), *args],
            capture_output=True,
            text=True,
            check=False,
        )

    def test_advisory_mode_exits_zero_with_findings(
        self, tmp_path: Path, manifest_path: Path
    ) -> None:
        _write_skill(
            tmp_path,
            "merge_sweep",
            {
                "run.sh": (
                    "uv run python -m omnimarket.nodes.node_pr_lifecycle_orchestrator "
                    "--input '{}'\n"
                )
            },
        )
        result = self._run(
            "--skills-root",
            str(tmp_path),
            "--manifest",
            str(manifest_path),
        )
        assert result.returncode == 0, result.stdout + result.stderr
        assert "advisory finding" in result.stdout.lower()

    def test_strict_mode_exits_one_with_findings(
        self, tmp_path: Path, manifest_path: Path
    ) -> None:
        _write_skill(
            tmp_path,
            "merge_sweep",
            {
                "run.sh": (
                    "uv run python -m omnimarket.nodes.node_pr_lifecycle_orchestrator "
                    "--input '{}'\n"
                )
            },
        )
        result = self._run(
            "--skills-root",
            str(tmp_path),
            "--manifest",
            str(manifest_path),
            "--strict",
        )
        assert result.returncode == 1, result.stdout + result.stderr

    def test_clean_manifest_entries_exit_zero(
        self, tmp_path: Path, manifest_path: Path
    ) -> None:
        _write_skill(
            tmp_path,
            "runtime_sweep",
            {
                "SKILL.md": (
                    "```bash\nuv run onex node node_runtime_sweep -- --scope all\n```\n"
                )
            },
        )
        _write_skill(
            tmp_path,
            "merge_sweep",
            {
                "SKILL.md": (
                    "```bash\nuv run onex run-node node_pr_lifecycle_orchestrator --input '{}'\n```\n"
                )
            },
        )
        _write_skill(
            tmp_path,
            "pr_review_bot",
            {
                "SKILL.md": (
                    "```bash\nuv run onex run-node node_pr_review_bot --input '{}'\n```\n"
                )
            },
        )
        _write_skill(
            tmp_path,
            "delegate",
            {
                "SKILL.md": (
                    "Publish to onex.cmd.omniclaude.delegate-task.v1 via the emit daemon.\n"
                    "emitted = emit_event('delegate.task', envelope)\n"
                )
            },
        )
        result = self._run(
            "--skills-root",
            str(tmp_path),
            "--manifest",
            str(manifest_path),
            "--strict",
        )
        assert result.returncode == 0, result.stdout + result.stderr
