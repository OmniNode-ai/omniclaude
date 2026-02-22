# SPDX-License-Identifier: MIT
# Copyright (c) 2025 OmniNode Team
"""Unit tests for consumer group guard (F5 rules).

Tests:
- has_version_suffix()
- validate_consumer_group_config()
- FatalStartupError
- SKILL_NODE_CONSUMER_GROUPS naming rules
"""

from __future__ import annotations

import re

import pytest

from omniclaude.lib.consumer_group_guard import (
    SKILL_NODE_CONSUMER_GROUPS,
    FatalStartupError,
    has_version_suffix,
    validate_consumer_group_config,
)

# Pattern for valid consumer group format: omniclaude-{name}.v{N}
_GROUP_ID_PATTERN = re.compile(r"^omniclaude-[a-z][a-z0-9-]+\.v\d+$")


class TestHasVersionSuffix:
    """Tests for has_version_suffix()."""

    def test_returns_true_for_v1_suffix(self) -> None:
        assert has_version_suffix("omniclaude-git-effect.v1") is True

    def test_returns_true_for_v2_suffix(self) -> None:
        assert has_version_suffix("omniclaude-compliance-subscriber.v2") is True

    def test_returns_true_for_large_version(self) -> None:
        assert has_version_suffix("omniclaude-something.v100") is True

    def test_returns_false_for_missing_version(self) -> None:
        assert has_version_suffix("omniclaude-git-effect") is False

    def test_returns_false_for_v_without_number(self) -> None:
        assert has_version_suffix("omniclaude-git-effect.v") is False

    def test_returns_false_for_wrong_suffix(self) -> None:
        assert has_version_suffix("omniclaude-git-effect-v1") is False

    def test_returns_false_for_empty_string(self) -> None:
        assert has_version_suffix("") is False

    def test_existing_compliance_subscriber(self) -> None:
        """Existing consumer omniclaude-compliance-subscriber.v1 should pass."""
        assert has_version_suffix("omniclaude-compliance-subscriber.v1") is True


class TestValidateConsumerGroupConfig:
    """Tests for validate_consumer_group_config()."""

    def test_latest_offset_reset_always_passes(self) -> None:
        """F5.3 only applies to 'earliest' resets."""
        # Should not raise even with missing version
        validate_consumer_group_config(
            group_id="omniclaude-missing-version",
            auto_offset_reset="latest",
            has_committed_offsets=True,
        )

    def test_none_offset_reset_passes(self) -> None:
        """'none' offset reset is not a reset, should pass."""
        validate_consumer_group_config(
            group_id="omniclaude-no-version",
            auto_offset_reset="none",
            has_committed_offsets=True,
        )

    def test_earliest_with_version_passes(self) -> None:
        """earliest reset with versioned group ID is allowed."""
        validate_consumer_group_config(
            group_id="omniclaude-git-effect.v1",
            auto_offset_reset="earliest",
            has_committed_offsets=True,
        )

    def test_earliest_with_version_first_run_passes(self) -> None:
        """earliest reset on first run (no committed offsets) passes."""
        validate_consumer_group_config(
            group_id="omniclaude-git-effect.v1",
            auto_offset_reset="earliest",
            has_committed_offsets=False,
        )

    def test_earliest_without_version_first_run_passes(self) -> None:
        """First run bypass: no committed offsets means guard skipped."""
        validate_consumer_group_config(
            group_id="omniclaude-no-version",  # missing version
            auto_offset_reset="earliest",
            has_committed_offsets=False,  # first run bypass
        )

    def test_earliest_without_version_with_offsets_raises(self) -> None:
        """F5.3: earliest + no version + committed offsets → FatalStartupError."""
        with pytest.raises(FatalStartupError) as exc_info:
            validate_consumer_group_config(
                group_id="omniclaude-no-version",
                auto_offset_reset="earliest",
                has_committed_offsets=True,
            )
        err = exc_info.value
        assert err.group_id == "omniclaude-no-version"
        assert err.auto_offset_reset == "earliest"
        assert err.rule == "F5.3"

    def test_fatal_startup_error_message_is_actionable(self) -> None:
        """FatalStartupError message should tell the user how to fix it."""
        with pytest.raises(FatalStartupError) as exc_info:
            validate_consumer_group_config(
                group_id="omniclaude-bad-group",
                auto_offset_reset="earliest",
                has_committed_offsets=True,
            )
        msg = str(exc_info.value)
        assert "omniclaude-bad-group" in msg
        assert "version" in msg.lower()
        assert "F5.3" in msg

    def test_default_has_committed_offsets_is_false(self) -> None:
        """Default value is False (safe default for first-run bypass)."""
        # Should not raise: default has_committed_offsets=False
        validate_consumer_group_config(
            group_id="omniclaude-no-version",
            auto_offset_reset="earliest",
        )


class TestFatalStartupError:
    """Tests for FatalStartupError exception."""

    def test_attributes_set_correctly(self) -> None:
        err = FatalStartupError(
            group_id="omniclaude-test",
            auto_offset_reset="earliest",
            rule="F5.3",
        )
        assert err.group_id == "omniclaude-test"
        assert err.auto_offset_reset == "earliest"
        assert err.rule == "F5.3"

    def test_is_exception(self) -> None:
        err = FatalStartupError(
            group_id="omniclaude-test",
            auto_offset_reset="earliest",
            rule="F5.3",
        )
        assert isinstance(err, Exception)

    def test_message_includes_group_id(self) -> None:
        err = FatalStartupError(
            group_id="my-group-id",
            auto_offset_reset="earliest",
            rule="F5.3",
        )
        assert "my-group-id" in str(err)


class TestSkillNodeConsumerGroups:
    """Tests for SKILL_NODE_CONSUMER_GROUPS (F5.4 naming rules)."""

    _EXPECTED_NODES = {
        "NodeGitEffect",
        "NodeClaudeCodeSessionEffect",
        "NodeLocalLlmInferenceEffect",
        "NodeLinearEffect",
        "NodeTicketingEffect",
        "NodeLocalCodingOrchestrator",
    }

    def test_all_6_skill_nodes_have_group_id(self) -> None:
        """F5.4: All 6 skill nodes from OMN-2593 must have consumer group IDs."""
        assert set(SKILL_NODE_CONSUMER_GROUPS.keys()) == self._EXPECTED_NODES

    def test_all_group_ids_have_omniclaude_prefix(self) -> None:
        for node, group_id in SKILL_NODE_CONSUMER_GROUPS.items():
            assert group_id.startswith("omniclaude-"), (
                f"{node}: group_id '{group_id}' must start with 'omniclaude-'"
            )

    def test_all_group_ids_have_version_suffix(self) -> None:
        for node, group_id in SKILL_NODE_CONSUMER_GROUPS.items():
            assert has_version_suffix(group_id), (
                f"{node}: group_id '{group_id}' must have a version suffix (.v{{N}})"
            )

    def test_all_group_ids_match_naming_convention(self) -> None:
        """F5.4: omniclaude-{node-name}.v{N} format."""
        for node, group_id in SKILL_NODE_CONSUMER_GROUPS.items():
            assert _GROUP_ID_PATTERN.match(group_id), (
                f"{node}: group_id '{group_id}' does not match "
                "omniclaude-{{name}}.v{{N}} pattern"
            )

    def test_git_effect_group_id(self) -> None:
        assert SKILL_NODE_CONSUMER_GROUPS["NodeGitEffect"] == "omniclaude-git-effect.v1"

    def test_claude_code_session_group_id(self) -> None:
        assert (
            SKILL_NODE_CONSUMER_GROUPS["NodeClaudeCodeSessionEffect"]
            == "omniclaude-claude-code-session-effect.v1"
        )

    def test_local_llm_inference_group_id(self) -> None:
        assert (
            SKILL_NODE_CONSUMER_GROUPS["NodeLocalLlmInferenceEffect"]
            == "omniclaude-local-llm-inference-effect.v1"
        )

    def test_linear_effect_group_id(self) -> None:
        assert (
            SKILL_NODE_CONSUMER_GROUPS["NodeLinearEffect"]
            == "omniclaude-linear-effect.v1"
        )

    def test_ticketing_effect_group_id(self) -> None:
        assert (
            SKILL_NODE_CONSUMER_GROUPS["NodeTicketingEffect"]
            == "omniclaude-ticketing-effect.v1"
        )

    def test_local_coding_orchestrator_group_id(self) -> None:
        assert (
            SKILL_NODE_CONSUMER_GROUPS["NodeLocalCodingOrchestrator"]
            == "omniclaude-local-coding-orchestrator.v1"
        )

    def test_no_duplicate_group_ids(self) -> None:
        group_ids = list(SKILL_NODE_CONSUMER_GROUPS.values())
        assert len(group_ids) == len(set(group_ids)), (
            "Duplicate consumer group IDs found in SKILL_NODE_CONSUMER_GROUPS"
        )

    def test_all_group_ids_pass_startup_validation(self) -> None:
        """All skill node group IDs must pass F5.3 validation with earliest reset."""
        for node, group_id in SKILL_NODE_CONSUMER_GROUPS.items():
            # Should not raise: all group IDs have version suffix
            validate_consumer_group_config(
                group_id=group_id,
                auto_offset_reset="earliest",
                has_committed_offsets=True,
            )


class TestValidateNoCompactCmdTopicScript:
    """Tests for validate_no_compact_cmd_topic.py script."""

    def test_script_imports_cleanly(self) -> None:
        """The validation script module should be importable."""
        import importlib.util
        from pathlib import Path

        script_path = (
            Path(__file__).parent.parent.parent
            / "scripts"
            / "validation"
            / "validate_no_compact_cmd_topic.py"
        )
        assert script_path.exists(), f"Script not found: {script_path}"

        spec = importlib.util.spec_from_file_location(
            "validate_no_compact", script_path
        )
        assert spec is not None
        module = importlib.util.module_from_spec(spec)
        assert spec.loader is not None
        spec.loader.exec_module(module)  # type: ignore[attr-defined]

        assert hasattr(module, "main")
        assert hasattr(module, "scan_file")

    def test_no_violations_on_existing_codebase(self) -> None:
        """The existing codebase should not have any compact cmd topic violations."""
        import importlib.util
        from pathlib import Path

        script_path = (
            Path(__file__).parent.parent.parent
            / "scripts"
            / "validation"
            / "validate_no_compact_cmd_topic.py"
        )
        spec = importlib.util.spec_from_file_location(
            "validate_no_compact", script_path
        )
        assert spec is not None
        module = importlib.util.module_from_spec(spec)
        assert spec.loader is not None
        spec.loader.exec_module(module)  # type: ignore[attr-defined]

        result = module.main([])
        assert result == 0, "validate_no_compact_cmd_topic found violations in codebase"

    def test_scan_file_detects_compact_violation(
        self, tmp_path: pytest.TempPathFactory
    ) -> None:  # type: ignore[name-defined]
        """scan_file should detect cleanup.policy=compact on cmd topics."""
        import importlib.util
        from pathlib import Path

        script_path = (
            Path(__file__).parent.parent.parent
            / "scripts"
            / "validation"
            / "validate_no_compact_cmd_topic.py"
        )
        spec = importlib.util.spec_from_file_location(
            "validate_no_compact", script_path
        )
        assert spec is not None
        module = importlib.util.module_from_spec(spec)
        assert spec.loader is not None
        spec.loader.exec_module(module)  # type: ignore[attr-defined]

        # Create a config file with a cmd topic and compact policy
        config_file = tmp_path / "topic_config.yaml"
        config_file.write_text(
            "topic: onex.cmd.omniclaude.my-event.v1\ncleanup.policy: compact\n"
        )

        violations = module.scan_file(config_file)
        assert len(violations) > 0, "Expected violation for compact cmd topic"

    def test_scan_file_allows_compact_on_evt_topic(
        self, tmp_path: pytest.TempPathFactory
    ) -> None:  # type: ignore[name-defined]
        """scan_file should NOT flag cleanup.policy=compact on evt topics."""
        import importlib.util
        from pathlib import Path

        script_path = (
            Path(__file__).parent.parent.parent
            / "scripts"
            / "validation"
            / "validate_no_compact_cmd_topic.py"
        )
        spec = importlib.util.spec_from_file_location(
            "validate_no_compact", script_path
        )
        assert spec is not None
        module = importlib.util.module_from_spec(spec)
        assert spec.loader is not None
        spec.loader.exec_module(module)  # type: ignore[attr-defined]

        # evt topics CAN use compact policy
        config_file = tmp_path / "evt_topic_config.yaml"
        config_file.write_text(
            "topic: onex.evt.omniclaude.session-started.v1\ncleanup.policy: compact\n"
        )

        violations = module.scan_file(config_file)
        assert len(violations) == 0, f"Unexpected violation for evt topic: {violations}"

    def test_scan_file_respects_noqa_suppression(
        self, tmp_path: pytest.TempPathFactory
    ) -> None:  # type: ignore[name-defined]
        """scan_file should skip lines with # noqa: arch-no-compact-cmd-topic."""
        import importlib.util
        from pathlib import Path

        script_path = (
            Path(__file__).parent.parent.parent
            / "scripts"
            / "validation"
            / "validate_no_compact_cmd_topic.py"
        )
        spec = importlib.util.spec_from_file_location(
            "validate_no_compact", script_path
        )
        assert spec is not None
        module = importlib.util.module_from_spec(spec)
        assert spec.loader is not None
        spec.loader.exec_module(module)  # type: ignore[attr-defined]

        config_file = tmp_path / "suppressed.yaml"
        config_file.write_text(
            "topic: onex.cmd.omniclaude.my-event.v1  # noqa: arch-no-compact-cmd-topic\n"
            "cleanup.policy: compact\n"
        )

        violations = module.scan_file(config_file)
        assert len(violations) == 0, f"Expected suppression to work: {violations}"
