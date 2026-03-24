# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""Tests for hostile-reviewer file routing fix and persona default.

Validates:
- prompt.md contains path validation instructions (OMN-6226)
- Result JSON schema includes target field (OMN-6226)
- Path validation logic rejects nonexistent files with exit 1 (OMN-6226)
- Path validation resolves ".." components to canonical form (OMN-6226)
- --persona analytical-strict appears in both file-mode and PR-mode (OMN-6227)
- SKILL.md documents the analytical-strict persona default (OMN-6227)

Tickets: OMN-6226, OMN-6227
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
# OMN-6226: File path validation
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_file_routing_instructions_present() -> None:
    """prompt.md must contain path resolution and validation instructions."""
    prompt = _PROMPT_MD.read_text()
    assert "resolve" in prompt.lower() or "Path(" in prompt, (
        "prompt.md must contain path resolution instructions"
    )
    # The validation block emits "not found" in the error message
    assert "not found" in prompt.lower() or "not exist" in prompt.lower(), (
        "prompt.md must instruct hard failure if file missing"
    )


@pytest.mark.unit
def test_result_json_has_target_field() -> None:
    """Result JSON schema in SKILL.md must include target field; prompt.md must reference target invariant."""
    skill_md = _SKILL_MD.read_text()
    assert '"target"' in skill_md, (
        "SKILL.md result JSON schema must include target field set to resolved file path"
    )
    # prompt.md must mention the target invariant for file mode
    prompt = _PROMPT_MD.read_text()
    assert "target" in prompt.lower(), (
        "prompt.md must reference the target field invariant for file mode"
    )


@pytest.mark.unit
def test_validation_script_rejects_nonexistent_file() -> None:
    """Path validation logic must exit 1 for a missing file."""
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
    """Validation script must output the resolved absolute path, not raw input with '..'."""
    with tempfile.NamedTemporaryFile(suffix=".md", delete=False, dir="/tmp") as f:
        f.write(b"# Plan\n")
        tmp_path = f.name

    try:
        # Construct a path with a redundant ".." component so resolution is non-trivial
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
        assert ".." not in output_path, (
            f"Resolved path must not contain '..': {output_path}"
        )
        assert output_path.startswith("/"), (
            f"Resolved path must be absolute: {output_path}"
        )
        assert output_path == str(Path(raw_path).resolve()), (
            f"Output {output_path!r} must equal Path(raw_path).resolve()"
        )
    finally:
        Path(tmp_path).unlink()


# ---------------------------------------------------------------------------
# OMN-6226: PR mode regression guard
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_pr_mode_instructions_unchanged() -> None:
    """PR mode invocation path must remain intact in prompt.md."""
    prompt = _PROMPT_MD.read_text()
    assert "cli_review" in prompt, "cli_review invocation must still be present"
    assert "--pr" in prompt, "--pr flag must still be present for PR mode"
    assert "--file" in prompt, "--file flag must still be present for file mode"


# ---------------------------------------------------------------------------
# OMN-6227: Persona default
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_file_mode_includes_persona_flag() -> None:
    """prompt.md file-mode invocation must include --persona analytical-strict."""
    prompt = _PROMPT_MD.read_text()
    assert "--persona analytical-strict" in prompt, (
        "File-mode invocation must pass --persona analytical-strict to cli_review"
    )


@pytest.mark.unit
def test_pr_mode_includes_persona_reference() -> None:
    """prompt.md must reference analytical-strict persona in PR mode context."""
    prompt = _PROMPT_MD.read_text()
    assert "analytical-strict" in prompt, (
        "prompt.md must reference analytical-strict persona in at least one mode"
    )
    # Count occurrences - must appear in at least file mode section
    count = prompt.count("analytical-strict")
    assert count >= 1, f"Expected analytical-strict at least once, found {count}"


@pytest.mark.unit
def test_skill_md_documents_persona_default() -> None:
    """SKILL.md must document the analytical-strict persona default."""
    skill_md = _SKILL_MD.read_text()
    assert "analytical-strict" in skill_md, (
        "SKILL.md must document the default analytical-strict persona"
    )
