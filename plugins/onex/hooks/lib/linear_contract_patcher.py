#!/usr/bin/env python3
"""Linear Contract Patcher - Safe, marker-based patching of Linear ticket descriptions.

Provides safe operations for reading and updating the YAML contract block
within a Linear ticket description, without destroying human-authored content.

Safety Guarantees:
    1. Only patches content between known markers (## Contract + fenced YAML)
    2. Validates YAML before every write — malformed YAML stops the operation
    3. Human edits outside the contract block are always preserved
    4. Never performs full-description rewrites
    5. Returns structured errors instead of raising exceptions

Marker Format:
    The contract block is delimited by:
    - Start: ``## Contract`` header followed by a fenced code block (```yaml ... ```)
    - Everything before the ## Contract header is preserved verbatim

Usage:
    from linear_contract_patcher import (
        extract_contract_yaml,
        patch_contract_yaml,
        validate_contract_yaml,
    )

    # Extract
    result = extract_contract_yaml(description)
    if result.success:
        contract = result.parsed  # dict

    # Patch
    result = patch_contract_yaml(description, updated_yaml_str)
    if result.success:
        new_description = result.patched_description

Related Tickets:
    - OMN-1970: Linear contract safety for ticket-pipeline
    - OMN-1967: Pipeline created with basic marker-based patching

.. versionadded:: 0.2.2
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass

import yaml

logger = logging.getLogger(__name__)

# Regex to find the ## Contract section with its fenced YAML block
# Matches: ## Contract\n...\n```yaml\n{content}\n```
# The [\s\S] allows matching across lines within the code fence
_CONTRACT_PATTERN = re.compile(
    r"(## Contract\s*\n+"  # Group 1: header
    r"```(?:yaml)?\s*\n)"  # Opening fence
    r"([\s\S]*?)"  # Group 2: YAML content
    r"(\n```)",  # Group 3: Closing fence
    re.MULTILINE,
)

# Simpler pattern for ## Pipeline Status block (separate from contract)
_PIPELINE_STATUS_PATTERN = re.compile(
    r"(## Pipeline Status\s*\n+"
    r"```(?:yaml)?\s*\n)"
    r"([\s\S]*?)"
    r"(\n```)",
    re.MULTILINE,
)


@dataclass(frozen=True)
class ContractExtractResult:
    """Result of extracting a contract from a Linear description.

    Attributes:
        success: True if the contract was found and parsed.
        raw_yaml: The raw YAML string (before parsing).
        parsed: The parsed YAML as a dict (None if parsing failed).
        error: Error message if extraction/parsing failed.
        has_contract_marker: Whether the ## Contract marker exists at all.
    """

    success: bool
    raw_yaml: str = ""
    parsed: dict | None = None  # type: ignore[type-arg]
    error: str | None = None
    has_contract_marker: bool = False


@dataclass(frozen=True)
class ContractPatchResult:
    """Result of patching a contract in a Linear description.

    Attributes:
        success: True if the patch was applied.
        patched_description: The full description with the patched contract.
        error: Error message if patching failed.
        validation_error: Specific YAML validation error (subset of error).
    """

    success: bool
    patched_description: str = ""
    error: str | None = None
    validation_error: str | None = None


def extract_contract_yaml(description: str) -> ContractExtractResult:
    """Extract and parse the YAML contract block from a Linear ticket description.

    Finds the ``## Contract`` section, extracts the fenced YAML block,
    and parses it with yaml.safe_load().

    Args:
        description: Full Linear ticket description (markdown).

    Returns:
        ContractExtractResult with parsed contract or error details.
    """
    if not description:
        return ContractExtractResult(
            success=False,
            error="Empty description",
            has_contract_marker=False,
        )

    has_marker = "## Contract" in description

    match = _CONTRACT_PATTERN.search(description)
    if not match:
        return ContractExtractResult(
            success=False,
            error="No ## Contract section with fenced YAML block found",
            has_contract_marker=has_marker,
        )

    raw_yaml = match.group(2)

    # Parse the YAML
    try:
        parsed = yaml.safe_load(raw_yaml)
    except yaml.YAMLError as e:
        return ContractExtractResult(
            success=False,
            raw_yaml=raw_yaml,
            error=f"YAML parse error in contract block: {e}",
            has_contract_marker=True,
        )

    if not isinstance(parsed, dict):
        return ContractExtractResult(
            success=False,
            raw_yaml=raw_yaml,
            error=f"Contract YAML must be a mapping (dict), got {type(parsed).__name__}",
            has_contract_marker=True,
        )

    return ContractExtractResult(
        success=True,
        raw_yaml=raw_yaml,
        parsed=parsed,
        has_contract_marker=True,
    )


def validate_contract_yaml(yaml_str: str) -> tuple[bool, str | None]:
    """Validate a YAML string as a valid contract.

    Checks:
    1. YAML parses without error
    2. Result is a dict (mapping)
    3. Required fields are present (ticket_id, phase)

    Args:
        yaml_str: YAML string to validate.

    Returns:
        Tuple of (is_valid, error_message).
    """
    try:
        parsed = yaml.safe_load(yaml_str)
    except yaml.YAMLError as e:
        return False, f"YAML parse error: {e}"

    if not isinstance(parsed, dict):
        return False, f"Contract must be a mapping (dict), got {type(parsed).__name__}"

    required_keys = {"ticket_id", "phase"}
    missing = required_keys - set(parsed.keys())
    if missing:
        return False, f"Missing required keys: {sorted(missing)}"

    return True, None


def patch_contract_yaml(
    description: str,
    new_yaml_str: str,
    *,
    validate: bool = True,
) -> ContractPatchResult:
    """Patch the YAML contract block in a Linear ticket description.

    Replaces only the YAML content inside the ``## Contract`` fenced code block.
    Everything outside the contract block is preserved verbatim.

    Safety:
    - Validates the new YAML before writing (unless validate=False)
    - Never rewrites content outside the contract block
    - Fails if no contract marker exists (won't create one)

    Args:
        description: Full Linear ticket description (markdown).
        new_yaml_str: New YAML content to replace the contract block.
        validate: Whether to validate YAML before patching (default True).

    Returns:
        ContractPatchResult with the patched description or error details.
    """
    if not description:
        return ContractPatchResult(
            success=False,
            error="Empty description",
        )

    # Validate new YAML before patching
    if validate:
        is_valid, validation_error = validate_contract_yaml(new_yaml_str)
        if not is_valid:
            return ContractPatchResult(
                success=False,
                error=f"YAML validation failed: {validation_error}",
                validation_error=validation_error,
            )

    # Find the contract block
    match = _CONTRACT_PATTERN.search(description)
    if not match:
        return ContractPatchResult(
            success=False,
            error="No ## Contract section with fenced YAML block found. "
            "Cannot patch without existing contract marker.",
        )

    # Ensure new YAML doesn't have leading/trailing whitespace issues
    clean_yaml = new_yaml_str.rstrip()

    # Replace only the YAML content (group 2), preserving header and fences
    patched = description[: match.start(2)] + clean_yaml + description[match.end(2) :]

    return ContractPatchResult(
        success=True,
        patched_description=patched,
    )


def patch_pipeline_status(
    description: str,
    status_yaml_str: str,
) -> ContractPatchResult:
    """Patch the ## Pipeline Status block in a Linear ticket description.

    Similar to patch_contract_yaml but targets the Pipeline Status section.
    If the section doesn't exist, appends it before the ## Contract section.

    Args:
        description: Full Linear ticket description (markdown).
        status_yaml_str: New YAML content for the pipeline status block.

    Returns:
        ContractPatchResult with the patched description or error details.
    """
    if not description:
        return ContractPatchResult(success=False, error="Empty description")

    # Validate YAML
    try:
        parsed = yaml.safe_load(status_yaml_str)
        if not isinstance(parsed, dict):
            return ContractPatchResult(
                success=False,
                error=f"Pipeline status must be a mapping, got {type(parsed).__name__}",
                validation_error=f"Expected dict, got {type(parsed).__name__}",
            )
    except yaml.YAMLError as e:
        return ContractPatchResult(
            success=False,
            error=f"YAML validation failed: {e}",
            validation_error=str(e),
        )

    clean_yaml = status_yaml_str.rstrip()
    new_block = f"## Pipeline Status\n\n```yaml\n{clean_yaml}\n```"

    # Try to find existing Pipeline Status block
    match = _PIPELINE_STATUS_PATTERN.search(description)
    if match:
        # Replace existing block content
        patched = (
            description[: match.start(2)] + clean_yaml + description[match.end(2) :]
        )
        return ContractPatchResult(success=True, patched_description=patched)

    # No existing block — insert before ## Contract
    contract_idx = description.find("## Contract")
    if contract_idx >= 0:
        patched = (
            description[:contract_idx].rstrip()
            + "\n\n"
            + new_block
            + "\n\n<!-- /pipeline-status -->\n\n---\n\n"
            + description[contract_idx:]
        )
    else:
        # No contract section either — append at end
        patched = (
            description.rstrip()
            + "\n\n"
            + new_block
            + "\n\n<!-- /pipeline-status -->\n"
        )

    return ContractPatchResult(success=True, patched_description=patched)


__all__ = [
    "ContractExtractResult",
    "ContractPatchResult",
    "extract_contract_yaml",
    "patch_contract_yaml",
    "patch_pipeline_status",
    "validate_contract_yaml",
]
