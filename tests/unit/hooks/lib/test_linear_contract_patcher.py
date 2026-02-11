"""Tests for linear_contract_patcher module.

Tests the safe marker-based patching of Linear ticket descriptions
used by the ticket-pipeline for contract and pipeline status updates.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(
    0,
    str(
        Path(__file__).parent.parent.parent.parent.parent
        / "plugins"
        / "onex"
        / "hooks"
        / "lib"
    ),
)

from linear_contract_patcher import (
    extract_contract_yaml,
    patch_contract_yaml,
    patch_pipeline_status,
    validate_contract_yaml,
)

# =============================================================================
# Fixtures
# =============================================================================


SAMPLE_DESCRIPTION = """## Summary

This is a test ticket with human-authored content.

## Definition of Done

- [ ] Something

---

## Contract

```yaml
ticket_id: "OMN-1234"
phase: implementation
context:
  relevant_files:
    - "src/main.py"
questions: []
requirements: []
verification: []
gates: []
commits: []
pr_url: null
```
"""

SAMPLE_WITH_PIPELINE_STATUS = """## Summary

Human content here.

## Pipeline Status

```yaml
run_id: "abc-1234"
phase: "local_review"
blocked_reason: null
artifacts: {}
```

<!-- /pipeline-status -->

---

## Contract

```yaml
ticket_id: "OMN-1234"
phase: implementation
```
"""


# =============================================================================
# extract_contract_yaml tests
# =============================================================================


class TestExtractContractYaml:
    """Test extraction of YAML contract from Linear descriptions."""

    def test_extracts_valid_contract(self) -> None:
        result = extract_contract_yaml(SAMPLE_DESCRIPTION)
        assert result.success
        assert result.has_contract_marker
        assert result.parsed is not None
        assert result.parsed["ticket_id"] == "OMN-1234"
        assert result.parsed["phase"] == "implementation"

    def test_empty_description(self) -> None:
        result = extract_contract_yaml("")
        assert not result.success
        assert result.error == "Empty description"
        assert not result.has_contract_marker

    def test_no_contract_marker(self) -> None:
        result = extract_contract_yaml("Just some text without contract")
        assert not result.success
        assert not result.has_contract_marker

    def test_contract_marker_without_yaml_fence(self) -> None:
        desc = "## Contract\n\nSome text but no yaml fence"
        result = extract_contract_yaml(desc)
        assert not result.success
        assert result.has_contract_marker  # Marker exists but no fence

    def test_malformed_yaml(self) -> None:
        desc = "## Contract\n\n```yaml\n{invalid: yaml: [broken\n```"
        result = extract_contract_yaml(desc)
        assert not result.success
        assert result.has_contract_marker
        assert "YAML parse error" in (result.error or "")

    def test_yaml_not_a_dict(self) -> None:
        desc = "## Contract\n\n```yaml\n- item1\n- item2\n```"
        result = extract_contract_yaml(desc)
        assert not result.success
        assert "must be a mapping" in (result.error or "")

    def test_preserves_raw_yaml(self) -> None:
        result = extract_contract_yaml(SAMPLE_DESCRIPTION)
        assert result.success
        assert "ticket_id" in result.raw_yaml
        assert "OMN-1234" in result.raw_yaml

    def test_with_pipeline_status_section(self) -> None:
        """Extracts contract even when Pipeline Status section exists."""
        result = extract_contract_yaml(SAMPLE_WITH_PIPELINE_STATUS)
        assert result.success
        assert result.parsed["ticket_id"] == "OMN-1234"


# =============================================================================
# validate_contract_yaml tests
# =============================================================================


class TestValidateContractYaml:
    """Test YAML validation for contract blocks."""

    def test_valid_contract(self) -> None:
        yaml_str = 'ticket_id: "OMN-1234"\nphase: implementation'
        is_valid, error = validate_contract_yaml(yaml_str)
        assert is_valid
        assert error is None

    def test_missing_required_keys(self) -> None:
        yaml_str = "title: something"
        is_valid, error = validate_contract_yaml(yaml_str)
        assert not is_valid
        assert "Missing required keys" in (error or "")

    def test_invalid_yaml(self) -> None:
        yaml_str = "{broken: yaml: [nope"
        is_valid, error = validate_contract_yaml(yaml_str)
        assert not is_valid
        assert "YAML parse error" in (error or "")

    def test_not_a_dict(self) -> None:
        yaml_str = "- item1\n- item2"
        is_valid, error = validate_contract_yaml(yaml_str)
        assert not is_valid
        assert "must be a mapping" in (error or "")

    def test_minimal_valid(self) -> None:
        yaml_str = "ticket_id: X\nphase: intake"
        is_valid, _error = validate_contract_yaml(yaml_str)
        assert is_valid


# =============================================================================
# patch_contract_yaml tests
# =============================================================================


class TestPatchContractYaml:
    """Test safe patching of contract YAML blocks."""

    def test_patches_contract_preserves_surrounding(self) -> None:
        new_yaml = 'ticket_id: "OMN-1234"\nphase: review\ncommits:\n  - "abc123"'
        result = patch_contract_yaml(SAMPLE_DESCRIPTION, new_yaml)
        assert result.success
        # Human content preserved
        assert "This is a test ticket" in result.patched_description
        assert "Definition of Done" in result.patched_description
        # Contract updated
        assert "phase: review" in result.patched_description
        assert 'commits:\n  - "abc123"' in result.patched_description
        # Old contract values replaced
        assert "phase: implementation" not in result.patched_description

    def test_rejects_invalid_yaml(self) -> None:
        result = patch_contract_yaml(SAMPLE_DESCRIPTION, "{broken: yaml: [nope")
        assert not result.success
        assert result.validation_error is not None

    def test_rejects_missing_required_keys(self) -> None:
        result = patch_contract_yaml(SAMPLE_DESCRIPTION, "title: something")
        assert not result.success
        assert "Missing required keys" in (result.error or "")

    def test_empty_description(self) -> None:
        result = patch_contract_yaml("", "ticket_id: X\nphase: Y")
        assert not result.success
        assert "Empty description" in (result.error or "")

    def test_no_contract_marker(self) -> None:
        result = patch_contract_yaml("No contract here", "ticket_id: X\nphase: Y")
        assert not result.success
        assert "No ## Contract section" in (result.error or "")

    def test_skip_validation(self) -> None:
        """With validate=False, patches without checking YAML validity."""
        result = patch_contract_yaml(
            SAMPLE_DESCRIPTION,
            "any: content\nwhatever: true",
            validate=False,
        )
        assert result.success
        assert "any: content" in result.patched_description

    def test_idempotent_patch(self) -> None:
        """Patching twice with same content produces same result."""
        new_yaml = 'ticket_id: "OMN-1234"\nphase: done'
        result1 = patch_contract_yaml(SAMPLE_DESCRIPTION, new_yaml)
        assert result1.success
        result2 = patch_contract_yaml(result1.patched_description, new_yaml)
        assert result2.success
        assert result1.patched_description == result2.patched_description


# =============================================================================
# patch_pipeline_status tests
# =============================================================================


class TestPatchPipelineStatus:
    """Test patching of Pipeline Status blocks."""

    def test_creates_status_before_contract(self) -> None:
        status_yaml = 'run_id: "xyz"\nphase: "implement"'
        result = patch_pipeline_status(SAMPLE_DESCRIPTION, status_yaml)
        assert result.success
        desc = result.patched_description
        # Status block inserted
        assert "## Pipeline Status" in desc
        assert 'run_id: "xyz"' in desc
        # Contract still present
        assert "## Contract" in desc
        # Status appears before contract
        assert desc.index("## Pipeline Status") < desc.index("## Contract")

    def test_updates_existing_status(self) -> None:
        status_yaml = 'run_id: "abc-1234"\nphase: "create_pr"\nblocked_reason: null'
        result = patch_pipeline_status(SAMPLE_WITH_PIPELINE_STATUS, status_yaml)
        assert result.success
        desc = result.patched_description
        assert 'phase: "create_pr"' in desc
        # Old content replaced
        assert 'phase: "local_review"' not in desc
        # Contract preserved
        assert "## Contract" in desc

    def test_invalid_yaml_rejected(self) -> None:
        result = patch_pipeline_status(SAMPLE_DESCRIPTION, "{broken: [yaml")
        assert not result.success
        assert result.validation_error is not None

    def test_not_a_dict_rejected(self) -> None:
        result = patch_pipeline_status(SAMPLE_DESCRIPTION, "- item1")
        assert not result.success

    def test_empty_description(self) -> None:
        result = patch_pipeline_status("", "phase: x")
        assert not result.success

    def test_appends_when_no_contract(self) -> None:
        desc = "## Summary\n\nSome text without contract section."
        status_yaml = 'run_id: "abc"\nphase: "implement"'
        result = patch_pipeline_status(desc, status_yaml)
        assert result.success
        assert "## Pipeline Status" in result.patched_description
        assert "## Summary" in result.patched_description

    def test_preserves_human_content(self) -> None:
        """Ensures human-authored content outside markers is never touched."""
        status_yaml = 'run_id: "new"\nphase: "done"'
        result = patch_pipeline_status(SAMPLE_WITH_PIPELINE_STATUS, status_yaml)
        assert result.success
        assert "Human content here." in result.patched_description

    def test_pipeline_status_skips_contract_inside_fence(self) -> None:
        """Pipeline Status is inserted before the real Contract, skipping fenced ones.

        When a description contains '## Contract' inside a fenced code block
        (e.g., documentation examples), _find_outside_fence skips it and
        inserts Pipeline Status before the real (unfenced) Contract block.
        """
        desc = (
            "## Summary\n\n"
            "Here's an example of a contract format:\n\n"
            "```\n"
            "## Contract\n\n"
            "```yaml\n"
            'example: "not real"\n'
            "```\n"
            "```\n\n"
            "## Contract\n\n"
            "```yaml\n"
            'ticket_id: "OMN-1234"\n'
            "phase: implementation\n"
            "```\n"
        )
        status_yaml = 'run_id: "r1"\nphase: "implement"'
        result = patch_pipeline_status(desc, status_yaml)
        assert result.success
        patched = result.patched_description

        # Pipeline Status must appear before the real (unfenced) Contract.
        status_idx = patched.index("## Pipeline Status")
        # The real contract is the second occurrence of "## Contract"
        real_contract_idx = patched.index(
            "## Contract", patched.index("## Contract") + 1
        )
        assert status_idx < real_contract_idx
        # The fenced example should remain untouched before Pipeline Status
        fenced_example_idx = patched.index("```\n## Contract")
        assert fenced_example_idx < status_idx
        # The outer fence closes with the second-to-last ``` before Pipeline Status.
        # Find the end of the last ``` before the real contract (outer fence close).
        outer_fence_close = patched.rindex("```\n", 0, status_idx)
        assert outer_fence_close < status_idx, (
            "Pipeline Status must appear after the outer fence closes"
        )


# =============================================================================
# Bare fence / whitespace edge-case tests
# =============================================================================


class TestEdgeCases:
    """Edge-case tests for fence syntax and whitespace handling."""

    def test_bare_fence_without_yaml_specifier(self) -> None:
        """Contract block using ``` instead of ```yaml should still extract."""
        desc = '## Contract\n\n```\nticket_id: "OMN-5678"\nphase: review\n```\n'
        result = extract_contract_yaml(desc)
        assert result.success
        assert result.parsed is not None
        assert result.parsed["ticket_id"] == "OMN-5678"
        assert result.parsed["phase"] == "review"

    def test_lstrip_yaml_content(self) -> None:
        """Leading whitespace in new YAML must not produce extra blank lines."""
        new_yaml = '\n\n  ticket_id: "OMN-1234"\n  phase: review\n\n'
        result = patch_contract_yaml(SAMPLE_DESCRIPTION, new_yaml)
        assert result.success
        # The YAML inserted into the fence should not start with blank lines
        assert "```yaml\n\n" not in result.patched_description
        # Verify content is present (stripped)
        assert 'ticket_id: "OMN-1234"' in result.patched_description

        # Same check for patch_pipeline_status
        status_yaml = "\n  run_id: abc\n  phase: implement\n\n"
        result2 = patch_pipeline_status(SAMPLE_DESCRIPTION, status_yaml)
        assert result2.success
        assert "```yaml\n\n" not in result2.patched_description
        assert "run_id: abc" in result2.patched_description
