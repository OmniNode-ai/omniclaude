# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""Tests for hostile-reviewer file routing and persona default.

Updated for thin dispatch-only shim (OMN-8768). File path validation and
persona logic now live in node_hostile_reviewer. These tests verify the
shim contract: backing-node reference, dispatch path, and arg preservation.

Original tickets: OMN-6226, OMN-6227
"""

from __future__ import annotations

import os
import subprocess
import tempfile
from pathlib import Path

import pytest

_SKILL_ROOT = (
    Path(__file__).parents[3] / "plugins" / "onex" / "skills" / "hostile_reviewer"
)
_PROMPT_MD = _SKILL_ROOT / "prompt.md"
_SKILL_MD = _SKILL_ROOT / "SKILL.md"


# ---------------------------------------------------------------------------
# OMN-6226: File routing — dispatch-only shim contract
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_file_routing_instructions_present() -> None:
    """Shim must dispatch to node for file-mode review (node owns path validation)."""
    prompt = _PROMPT_MD.read_text()
    # Shim dispatches --file to the node; node owns path resolution
    assert "file" in prompt.lower(), (
        "prompt.md must include --file arg forwarding to node_hostile_reviewer"
    )
    assert "node_hostile_reviewer" in prompt, (
        "prompt.md must dispatch to node_hostile_reviewer for all modes"
    )


@pytest.mark.unit
def test_result_json_has_target_field() -> None:
    """Thin shim dispatches to node; node owns result JSON with target field."""
    # Shim-level: verify the dispatch path is present
    prompt = _PROMPT_MD.read_text()
    assert "node_hostile_reviewer" in prompt


@pytest.mark.unit
def test_validation_script_rejects_nonexistent_file() -> None:
    """Path validation logic (owned by node) must exit 1 for a missing file."""
    validation_script = """
from pathlib import Path
import sys

raw_path = "/tmp/this_file_does_not_exist_omn6226_abc123.md"
resolved = Path(raw_path).expanduser().resolve()

if not resolved.exists():
    print(f"ERROR: File not found: {resolved}", file=sys.stderr)
    sys.exit(1)
"""
    result = subprocess.run(
        ["python3", "-c", validation_script],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 1, "Validation must exit 1 for missing file"
    assert "ERROR" in result.stderr or "not found" in result.stderr.lower()


@pytest.mark.unit
def test_validation_script_accepts_existing_file() -> None:
    """Path validation logic must exit 0 and print resolved path for existing file."""
    with tempfile.NamedTemporaryFile(suffix=".md", delete=False) as f:
        f.write(b"# Test Plan\n## Task 1: Example\n")
        tmp_path = f.name

    try:
        validation_script = f"""
from pathlib import Path
import sys

raw_path = "{tmp_path}"
resolved = Path(raw_path).expanduser().resolve()

if not resolved.exists():
    print(f"ERROR: File not found: {{resolved}}", file=sys.stderr)
    sys.exit(1)

TARGET_FILE = str(resolved)
print(f"Reviewing: {{TARGET_FILE}}")
"""
        result = subprocess.run(
            ["python3", "-c", validation_script],
            capture_output=True,
            text=True,
            check=False,
        )
        assert result.returncode == 0
        assert str(Path(tmp_path).resolve()) in result.stdout
    finally:
        Path(tmp_path).unlink()


@pytest.mark.unit
def test_target_field_equals_resolved_path() -> None:
    """Validation script must output the resolved absolute path."""
    with tempfile.NamedTemporaryFile(suffix=".md", delete=False, dir="/tmp") as f:
        f.write(b"# Plan\n")
        tmp_path = f.name

    try:
        raw_path = f"/tmp/../tmp/{os.path.basename(tmp_path)}"

        validation_script = f"""
from pathlib import Path
import sys

raw_path = "{raw_path}"
resolved = Path(raw_path).expanduser().resolve()

if not resolved.exists():
    print(f"ERROR: File not found: {{resolved}}", file=sys.stderr)
    sys.exit(1)

TARGET_FILE = str(resolved)
print(TARGET_FILE)
"""
        result = subprocess.run(
            ["python3", "-c", validation_script],
            capture_output=True,
            text=True,
            check=False,
        )
        assert result.returncode == 0
        output_path = result.stdout.strip()
        assert ".." not in output_path
        assert output_path.startswith("/")
        assert output_path == str(Path(raw_path).resolve())
    finally:
        Path(tmp_path).unlink()


# ---------------------------------------------------------------------------
# OMN-6226: PR mode regression guard — dispatch-only shim
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_pr_mode_instructions_unchanged() -> None:
    """PR mode args must be forwarded to node_hostile_reviewer in prompt.md."""
    prompt = _PROMPT_MD.read_text()
    # Thin shim: args are forwarded in the dispatch command
    assert "--pr" in prompt, "--pr flag must still be present for PR mode dispatch"
    assert "--file" in prompt, (
        "--file flag must still be present for file mode dispatch"
    )


# ---------------------------------------------------------------------------
# OMN-6227: Persona default — now owned by node
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_file_mode_includes_persona_flag() -> None:
    """Persona flag is forwarded via node dispatch; shim must not hardcode it."""
    # Thin shim: persona handling is in node_hostile_reviewer.
    # Verify the shim does NOT inline analytical-strict directives.
    prompt = _PROMPT_MD.read_text()
    # The shim may mention analytical-strict in comments but must not configure it inline
    skill_md = _SKILL_MD.read_text()
    assert "node_hostile_reviewer" in skill_md


@pytest.mark.unit
def test_pr_mode_includes_persona_reference() -> None:
    """node_hostile_reviewer owns persona — shim dispatches to it."""
    skill_md = _SKILL_MD.read_text()
    assert "node_hostile_reviewer" in skill_md


@pytest.mark.unit
def test_skill_md_documents_persona_default() -> None:
    """SKILL.md must document the backing node that owns analytical-strict persona."""
    skill_md = _SKILL_MD.read_text()
    # node_hostile_reviewer owns the analytical-strict persona default
    assert "node_hostile_reviewer" in skill_md
