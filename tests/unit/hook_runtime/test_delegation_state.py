"""Unit tests for hook runtime delegation state reducer. [OMN-5305]"""
import pytest

from omniclaude.hook_runtime.delegation_state import (
    DelegationConfig,
    DelegationState,
)


def default_config() -> DelegationConfig:
    """Return a default DelegationConfig for testing."""
    return DelegationConfig(
        bash_readonly_patterns=[
            r"^git\s+",
            r"^gh\s+pr\s+list",
            r"^gh\s+pr\s+view",
            r"^gh\s+pr\s+checks",
            r"^cat\s+",
            r"^ls\s+",
            r"^echo\s+",
        ],
        bash_compound_deny_patterns=[
            r"&&",
            r"\|\s*\w",
            r";\s*\w",
        ],
    )


@pytest.mark.unit
def test_classify_bash_readonly() -> None:
    state = DelegationState(config=default_config())
    result = state.classify_tool("Bash", {"command": "gh pr list"})
    assert result == "read"


@pytest.mark.unit
def test_classify_bash_compound_is_write() -> None:
    state = DelegationState(config=default_config())
    result = state.classify_tool("Bash", {"command": "gh pr list && echo done"})
    assert result == "write"


@pytest.mark.unit
def test_classify_non_bash_is_read() -> None:
    state = DelegationState(config=default_config())
    result = state.classify_tool("Read", {"file_path": "/some/file.py"})
    assert result == "read"


@pytest.mark.unit
def test_classify_write_tools() -> None:
    state = DelegationState(config=default_config())
    for tool in ("Write", "Edit", "NotebookEdit"):
        result = state.classify_tool(tool, {})
        assert result == "write", f"Expected 'write' for tool {tool!r}"


@pytest.mark.unit
def test_read_block_at_threshold() -> None:
    state = DelegationState(config=default_config())
    for _ in range(13):
        state.record_tool("session-1", "read")
    decision = state.check_thresholds("session-1")
    assert decision.decision == "block"


@pytest.mark.unit
def test_skill_loaded_tightens_thresholds() -> None:
    state = DelegationState(config=default_config())
    state.set_skill_loaded("session-1")
    for _ in range(4):
        state.record_tool("session-1", "read")
    decision = state.check_thresholds("session-1")
    # skill_loaded total_block_threshold is 4
    assert decision.decision == "block"


@pytest.mark.unit
def test_delegation_resets_counters() -> None:
    state = DelegationState(config=default_config())
    state.record_tool("session-1", "write")
    state.record_tool("session-1", "write")
    state.mark_delegated("session-1")
    decision = state.check_thresholds("session-1")
    assert decision.decision == "pass"


@pytest.mark.unit
def test_reset_session() -> None:
    state = DelegationState(config=default_config())
    state.record_tool("session-1", "write")
    state.set_skill_loaded("session-1")
    state.reset_session("session-1")
    counters = state.get_counters("session-1")
    assert counters == {"read": 0, "write": 0, "total": 0}


@pytest.mark.unit
def test_warn_before_block() -> None:
    state = DelegationState(config=default_config())
    for _ in range(4):
        state.record_tool("session-1", "write")
    decision = state.check_thresholds("session-1")
    # write_warn_threshold=3, write_block_threshold=5 → 4 writes = warn
    assert decision.decision == "warn"
