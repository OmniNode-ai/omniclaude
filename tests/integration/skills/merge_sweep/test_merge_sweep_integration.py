# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Integration-level contract tests for the merge-sweep thin shim (v7.0.0).

The skill now builds a contract-canonical
`ModelEventEnvelope[ModelPrLifecycleStartCommand]` and invokes
`uv run onex run-node node_pr_lifecycle_orchestrator --input`.

These tests ride alongside `tests/unit/skills/test_merge_sweep_shim.py` and
assert the same invariants at integration scope so the
`Merge-Sweep Contract` CI job stays wired to the current skill contract.

All tests are static analysis / structural tests that run without external
credentials, live GitHub access, or live PRs. Safe for CI.

Test markers:
    @pytest.mark.unit — repeatable, no external mutations, CI-safe
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

_REPO_ROOT = Path(__file__).parent.parent.parent.parent.parent
_SKILLS_ROOT = _REPO_ROOT / "plugins" / "onex" / "skills"
_MERGE_SWEEP_DIR = _SKILLS_ROOT / "merge_sweep"
_MERGE_SWEEP_PROMPT = _MERGE_SWEEP_DIR / "prompt.md"
_MERGE_SWEEP_SKILL = _MERGE_SWEEP_DIR / "SKILL.md"


def _read(path: Path) -> str:
    if not path.exists():
        pytest.skip(f"Skill file not found: {path}")
    return path.read_text(encoding="utf-8")


def _frontmatter(content: str) -> dict[str, object]:
    parts = content.split("---", 2)
    assert len(parts) >= 3, "Frontmatter not properly delimited"
    loaded = yaml.safe_load(parts[1])
    assert isinstance(loaded, dict)
    return loaded


# ---------------------------------------------------------------------------
# SKILL.md — thin-shim structural contract
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestSkillMdIsThinShim:
    def test_skill_md_exists(self) -> None:
        assert _MERGE_SWEEP_SKILL.exists()

    def test_skill_md_version_is_v7(self) -> None:
        fm = _frontmatter(_read(_MERGE_SWEEP_SKILL))
        assert fm["version"] == "7.0.0"

    def test_skill_md_tagged_dispatch_only(self) -> None:
        fm = _frontmatter(_read(_MERGE_SWEEP_SKILL))
        tags = fm.get("tags") or []
        assert "dispatch-only" in tags
        assert "routing-enforced" in tags

    def test_skill_md_references_backing_node(self) -> None:
        content = _read(_MERGE_SWEEP_SKILL)
        assert "node_pr_lifecycle_orchestrator" in content
        assert "omnimarket" in content

    def test_skill_md_has_dispatch_command(self) -> None:
        content = _read(_MERGE_SWEEP_SKILL)
        assert "onex run-node node_pr_lifecycle_orchestrator" in content
        assert (
            "python -m omnimarket.nodes.node_pr_lifecycle_orchestrator" not in content
        )

    def test_skill_md_surfaces_nonzero_exit_passthrough(self) -> None:
        content = _read(_MERGE_SWEEP_SKILL)
        assert "non-zero exits" in content
        assert "do not produce prose" in content.lower()

    def test_skill_md_no_inline_gh_script(self) -> None:
        content = _read(_MERGE_SWEEP_SKILL)
        assert "gh pr merge --auto" not in content
        assert "gh pr merge --admin" not in content
        assert "gh pr merge --squash" not in content

    def test_skill_md_no_direct_kafka_publish(self) -> None:
        content = _read(_MERGE_SWEEP_SKILL)
        assert "kcat -P" not in content
        assert "kcat " not in content

    def test_skill_md_preserves_v3x_cli_surface(self) -> None:
        fm = _frontmatter(_read(_MERGE_SWEEP_SKILL))
        args = fm.get("args") or []
        arg_names = {a["name"] for a in args if isinstance(a, dict)}
        # Spot-check the v7 command fields the operator surface depends on.
        for required in (
            "--repos",
            "--dry-run",
            "--inventory-only",
            "--fix-only",
            "--merge-only",
            "--max-parallel-polish",
            "--enable-auto-rebase",
            "--use-dag-ordering",
            "--enable-trivial-comment-resolution",
            "--enable-admin-merge-fallback",
            "--admin-fallback-threshold-minutes",
            "--verify",
            "--verify-timeout-seconds",
        ):
            assert required in arg_names, f"missing preserved arg: {required}"


# ---------------------------------------------------------------------------
# prompt.md — thin-shim structural contract
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestPromptMdIsThinShim:
    def test_prompt_md_exists(self) -> None:
        assert _MERGE_SWEEP_PROMPT.exists()

    def test_prompt_md_has_announce(self) -> None:
        content = _read(_MERGE_SWEEP_PROMPT)
        assert "Announce" in content

    def test_prompt_md_dispatches_to_node(self) -> None:
        content = _read(_MERGE_SWEEP_PROMPT)
        assert "onex run-node node_pr_lifecycle_orchestrator" in content
        assert (
            "python -m omnimarket.nodes.node_pr_lifecycle_orchestrator" not in content
        )

    def test_prompt_md_single_dispatch(self) -> None:
        content = _read(_MERGE_SWEEP_PROMPT)
        matches = re.findall(
            r"onex\s+run-node\s+node_pr_lifecycle_orchestrator", content
        )
        assert len(matches) == 1, (
            f"Expected exactly 1 onex run-node dispatch, found {len(matches)}"
        )

    def test_prompt_md_no_inline_orchestration(self) -> None:
        content = _read(_MERGE_SWEEP_PROMPT)
        assert "kcat -P" not in content
        assert "result.json" not in content
        assert "poll_interval" not in content

    def test_prompt_md_no_gh_subprocess(self) -> None:
        content = _read(_MERGE_SWEEP_PROMPT)
        assert "gh pr merge --auto" not in content
        assert "gh pr merge --admin" not in content
        assert "gh pr merge --squash" not in content
        assert "gh api graphql" not in content

    def test_prompt_md_no_agent_spawning(self) -> None:
        content = _read(_MERGE_SWEEP_PROMPT)
        assert "TeamCreate" not in content
        assert "Agent(" not in content
        assert "CronCreate" not in content
        assert "SendMessage" not in content

    def test_prompt_md_no_llm_sdk_imports(self) -> None:
        content = _read(_MERGE_SWEEP_PROMPT)
        assert "import anthropic" not in content
        assert "from anthropic" not in content
        assert "import openai" not in content
        assert "from openai" not in content

    def test_prompt_md_no_subprocess_wrappers(self) -> None:
        content = _read(_MERGE_SWEEP_PROMPT)
        assert "subprocess.run" not in content
        assert "subprocess.Popen" not in content

    def test_prompt_md_surfaces_nonzero_exit_passthrough(self) -> None:
        content = _read(_MERGE_SWEEP_PROMPT)
        assert "exits non-zero" in content
        assert "stop" in content.lower()

    def test_prompt_md_preserves_cli_args(self) -> None:
        content = _read(_MERGE_SWEEP_PROMPT)
        for flag in (
            "--repos",
            "--dry-run",
            "--inventory-only",
            "--fix-only",
            "--merge-only",
            "--max-parallel-polish",
            "--enable-admin-merge-fallback",
            "--verify",
        ):
            assert flag in content, f"missing preserved arg in prompt: {flag}"

    def test_prompt_md_is_thin(self) -> None:
        content = _read(_MERGE_SWEEP_PROMPT)
        line_count = len(content.splitlines())
        assert line_count <= 100, (
            f"Thin shim must be <= 100 lines, got {line_count}. "
            "If the skill is growing logic, move it into the backing node."
        )

    def test_prompt_md_no_claim_registry(self) -> None:
        """The claim registry belongs to the node, not the shim."""
        content = _read(_MERGE_SWEEP_PROMPT)
        assert "claim_registry" not in content.lower()
        assert "dispatched.yaml" not in content
