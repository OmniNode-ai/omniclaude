# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Tests for test offloading framework [OMN-6735].

Verifies:
- Command detection (pytest, mypy, ruff, pre-commit)
- Offload decision logic
- Fallback when Gemini/Codex unavailable
- Error propagation (stderr captured, exit codes preserved)
- Direct invocation and hook event chain paths
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

# Add the module path
_MODULE_DIR = Path(__file__).parents[3] / "src/omniclaude/hooks/lib"
if str(_MODULE_DIR) not in sys.path:
    sys.path.insert(0, str(_MODULE_DIR))


# =============================================================================
# Command detection
# =============================================================================


@pytest.mark.unit
def test_detect_pytest() -> None:
    from test_offloader import detect_offloadable_command

    assert detect_offloadable_command("pytest tests/ -v") == "pytest"
    assert detect_offloadable_command("uv run pytest tests/ -m unit") == "pytest"
    assert detect_offloadable_command("python -m pytest") == "pytest"


@pytest.mark.unit
def test_detect_mypy() -> None:
    from test_offloader import detect_offloadable_command

    assert detect_offloadable_command("mypy src/ --strict") == "mypy"


@pytest.mark.unit
def test_detect_ruff() -> None:
    from test_offloader import detect_offloadable_command

    assert detect_offloadable_command("ruff check src/") == "ruff"
    assert detect_offloadable_command("ruff format src/") == "ruff"


@pytest.mark.unit
def test_detect_precommit() -> None:
    from test_offloader import detect_offloadable_command

    assert detect_offloadable_command("pre-commit run --all-files") == "pre-commit"


@pytest.mark.unit
def test_detect_non_offloadable() -> None:
    from test_offloader import detect_offloadable_command

    assert detect_offloadable_command("git status") is None
    assert detect_offloadable_command("ls -la") is None
    assert detect_offloadable_command("echo hello") is None


# =============================================================================
# Offload decision logic
# =============================================================================


@pytest.mark.unit
def test_offload_disabled_returns_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    from test_offloader import EnumOffloadResult, offload_command

    monkeypatch.delenv("OMNICLAUDE_TEST_OFFLOAD", raising=False)
    decision = offload_command("pytest tests/")
    assert decision.result == EnumOffloadResult.disabled


@pytest.mark.unit
def test_offload_non_offloadable_returns_direct() -> None:
    from test_offloader import EnumOffloadResult, offload_command

    decision = offload_command("git status")
    assert decision.result == EnumOffloadResult.direct


@pytest.mark.unit
def test_offload_enabled_no_target_falls_back(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When offloading is enabled but no target binary exists, fall back to direct."""
    import test_offloader

    monkeypatch.setenv("OMNICLAUDE_TEST_OFFLOAD", "true")

    # Mock _find_offload_target to return direct (no binaries)
    monkeypatch.setattr(
        test_offloader,
        "_find_offload_target",
        lambda: test_offloader.EnumOffloadTarget.direct,
    )

    # Mock _run_direct to avoid actually running
    def fake_run_direct(
        command: str, cmd_type: str
    ) -> test_offloader.ModelOffloadDecision:
        return test_offloader.ModelOffloadDecision(
            command=command,
            target=test_offloader.EnumOffloadTarget.direct,
            result=test_offloader.EnumOffloadResult.fallback_direct,
            summary=f"[{cmd_type}] 5 passed",
            exit_code=0,
        )

    monkeypatch.setattr(test_offloader, "_run_direct", fake_run_direct)

    decision = test_offloader.offload_command("pytest tests/")
    assert decision.result == test_offloader.EnumOffloadResult.fallback_direct


@pytest.mark.unit
def test_offload_enabled_with_gemini(monkeypatch: pytest.MonkeyPatch) -> None:
    """When Gemini is available, route to it."""
    import test_offloader

    monkeypatch.setenv("OMNICLAUDE_TEST_OFFLOAD", "true")
    monkeypatch.setattr(
        test_offloader,
        "_find_offload_target",
        lambda: test_offloader.EnumOffloadTarget.gemini,
    )

    class FakeResult:
        stdout = "All 5 tests passed"
        stderr = ""
        returncode = 0

    monkeypatch.setattr(
        test_offloader.subprocess,
        "run",
        lambda *a, **kw: FakeResult(),
    )

    decision = test_offloader.offload_command("pytest tests/")
    assert decision.result == test_offloader.EnumOffloadResult.offloaded
    assert decision.target == test_offloader.EnumOffloadTarget.gemini
    assert "5 tests passed" in decision.summary


# =============================================================================
# Error handling
# =============================================================================


@pytest.mark.unit
def test_offload_preserves_exit_code(monkeypatch: pytest.MonkeyPatch) -> None:
    """Exit codes from offloaded commands must be preserved."""
    import test_offloader

    monkeypatch.setenv("OMNICLAUDE_TEST_OFFLOAD", "true")
    monkeypatch.setattr(
        test_offloader,
        "_find_offload_target",
        lambda: test_offloader.EnumOffloadTarget.gemini,
    )

    class FakeResult:
        stdout = "2 tests failed"
        stderr = "AssertionError in test_foo"
        returncode = 1

    monkeypatch.setattr(
        test_offloader.subprocess,
        "run",
        lambda *a, **kw: FakeResult(),
    )

    decision = test_offloader.offload_command("pytest tests/")
    assert decision.exit_code == 1
    assert decision.stderr == "AssertionError in test_foo"


@pytest.mark.unit
def test_offload_captures_stderr(monkeypatch: pytest.MonkeyPatch) -> None:
    """stderr from offloaded commands must be captured, not swallowed."""
    import test_offloader

    monkeypatch.setenv("OMNICLAUDE_TEST_OFFLOAD", "true")
    monkeypatch.setattr(
        test_offloader,
        "_find_offload_target",
        lambda: test_offloader.EnumOffloadTarget.codex,
    )

    class FakeResult:
        stdout = "Error found"
        stderr = "CRITICAL: module not found"
        returncode = 2

    monkeypatch.setattr(
        test_offloader.subprocess,
        "run",
        lambda *a, **kw: FakeResult(),
    )

    decision = test_offloader.offload_command("mypy src/")
    assert "CRITICAL" in decision.stderr
    assert decision.exit_code == 2


@pytest.mark.unit
def test_offload_gemini_not_found_falls_back(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """FileNotFoundError from gemini binary must fall back to direct."""
    import test_offloader

    monkeypatch.setenv("OMNICLAUDE_TEST_OFFLOAD", "true")
    monkeypatch.setattr(
        test_offloader,
        "_find_offload_target",
        lambda: test_offloader.EnumOffloadTarget.gemini,
    )

    def raise_not_found(*args: object, **kwargs: object) -> None:
        raise FileNotFoundError("gemini")

    monkeypatch.setattr(test_offloader.subprocess, "run", raise_not_found)

    # Mock _run_direct to avoid actually running
    def fake_run_direct(
        command: str, cmd_type: str
    ) -> test_offloader.ModelOffloadDecision:
        return test_offloader.ModelOffloadDecision(
            command=command,
            target=test_offloader.EnumOffloadTarget.direct,
            result=test_offloader.EnumOffloadResult.fallback_direct,
            summary=f"[{cmd_type}] fallback",
            exit_code=0,
        )

    monkeypatch.setattr(test_offloader, "_run_direct", fake_run_direct)

    decision = test_offloader.offload_command("ruff check src/")
    assert decision.result == test_offloader.EnumOffloadResult.fallback_direct


# =============================================================================
# Summary extraction
# =============================================================================


@pytest.mark.unit
def test_summarize_pytest_output() -> None:
    from test_offloader import _summarize_test_output

    output = (
        "tests/test_foo.py::test_a PASSED\n"
        "tests/test_foo.py::test_b PASSED\n"
        "====== 2 passed in 0.5s ======"
    )
    summary = _summarize_test_output(output, 0, "pytest")
    assert "2 passed" in summary


@pytest.mark.unit
def test_summarize_mypy_output() -> None:
    from test_offloader import _summarize_test_output

    output = "src/foo.py:1: error\nFound 1 error in 1 file"
    summary = _summarize_test_output(output, 1, "mypy")
    assert "Found 1 error" in summary


@pytest.mark.unit
def test_summarize_empty_output() -> None:
    from test_offloader import _summarize_test_output

    summary = _summarize_test_output("", 0, "pytest")
    assert "PASS" in summary


# =============================================================================
# Model and enum structure
# =============================================================================


@pytest.mark.unit
def test_model_offload_decision_frozen() -> None:
    """ModelOffloadDecision must be frozen (immutable)."""
    from test_offloader import (
        EnumOffloadResult,
        EnumOffloadTarget,
        ModelOffloadDecision,
    )

    decision = ModelOffloadDecision(
        command="pytest tests/",
        target=EnumOffloadTarget.direct,
        result=EnumOffloadResult.direct,
    )
    with pytest.raises(Exception):
        decision.command = "changed"  # type: ignore[misc]


@pytest.mark.unit
def test_is_offload_enabled(monkeypatch: pytest.MonkeyPatch) -> None:
    from test_offloader import is_offload_enabled

    monkeypatch.delenv("OMNICLAUDE_TEST_OFFLOAD", raising=False)
    assert not is_offload_enabled()

    monkeypatch.setenv("OMNICLAUDE_TEST_OFFLOAD", "true")
    assert is_offload_enabled()

    monkeypatch.setenv("OMNICLAUDE_TEST_OFFLOAD", "1")
    assert is_offload_enabled()

    monkeypatch.setenv("OMNICLAUDE_TEST_OFFLOAD", "false")
    assert not is_offload_enabled()
