# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Protocol-level tests for the PostToolUse output suppressor (OMN-13095).

These tests pin the HOOK PROTOCOL, not the internal transform (the prior
test suite validated a data transform that never reached the model —
plan Problem 4). What is asserted here:

- The exact root-level ``hookSpecificOutput`` JSON contract on stdout for
  the suppress case (shape pinned by the OMN-13090 probe: object form
  ``{stdout, stderr, interrupted, isImage}``; a shape regression fails
  open + invisibly in the CLI, so this test is the only tripwire).
- Passthrough emits NOTHING (empty stdout) for: non-Bash, unmatched,
  small, error, interrupted, and receipt-mode payloads.
- Capture-before-suppress: artifact write failure (store unavailable OR
  write error) means passthrough; event-emission failure after a
  successful write still suppresses.
- Replay: recorded hook payload fixtures (probe-shaped) run through the
  real CLI entrypoint as a subprocess.

Fixtures live in ``tests/fixtures/hooks/post_tool_use/`` and mirror the
live PostToolUse stdin shape captured by the OMN-13090 probe.
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

# Add hooks lib to path for direct import
_REPO_ROOT = Path(__file__).parents[3]
_HOOKS_LIB = _REPO_ROOT / "plugins/onex/hooks/lib"
if str(_HOOKS_LIB) not in sys.path:
    sys.path.insert(0, str(_HOOKS_LIB))

_FIXTURES = _REPO_ROOT / "tests/fixtures/hooks/post_tool_use"
_SUPPRESSOR = _HOOKS_LIB / "skill_output_suppressor.py"

_PASSTHROUGH_FIXTURES = [
    "non_bash_read.json",
    "bash_git_status_small.json",
    "bash_onex_node_small.json",
    "bash_pytest_error_large.json",
    "bash_onex_interrupted_large.json",
    "bash_onex_receipt_large.json",
]


def _load_fixture(name: str) -> dict:
    return json.loads((_FIXTURES / name).read_text())


class _FakeRef:
    def __init__(self, ref: str) -> None:
        self.ref = ref


class _FakeStore:
    """In-memory stand-in matching the ArtifactStore write_blob signature."""

    def __init__(self) -> None:
        self.writes: list[dict] = []

    def write_blob(
        self,
        data: bytes,
        *,
        media_type: str,
        artifact_kind: str,
        source_system: str,
        scope_ref: str | None,
        correlation_id: str | None,
    ) -> _FakeRef:
        self.writes.append(
            {
                "data": data,
                "media_type": media_type,
                "artifact_kind": artifact_kind,
                "source_system": source_system,
                "scope_ref": scope_ref,
                "correlation_id": correlation_id,
            }
        )
        return _FakeRef(f"sha256:{hashlib.sha256(data).hexdigest()}")


@pytest.fixture
def captured_events(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, dict]]:
    """Intercept emit_client_wrapper.emit_event; record (event_type, payload)."""
    import emit_client_wrapper

    events: list[tuple[str, dict]] = []

    def _fake_emit(event_type: str, payload: dict, timeout_ms: int = 0) -> bool:
        events.append((event_type, payload))
        return True

    monkeypatch.setattr(emit_client_wrapper, "emit_event", _fake_emit)
    return events


# =============================================================================
# Suppress case: exact protocol envelope
# =============================================================================


@pytest.mark.unit
def test_suppress_emits_exact_hook_specific_output_contract(
    captured_events: list[tuple[str, dict]],
) -> None:
    """The suppress emission is EXACTLY the probe-pinned envelope."""
    from skill_output_suppressor import process_hook_payload

    store = _FakeStore()
    payload = _load_fixture("bash_onex_node_large.json")
    emission = process_hook_payload(payload, store_factory=lambda: store)

    assert emission, "suppress-eligible fixture must produce an emission"
    parsed = json.loads(emission)

    # Root level: hookSpecificOutput and NOTHING else (no tool_info echo).
    assert set(parsed.keys()) == {"hookSpecificOutput"}
    hso = parsed["hookSpecificOutput"]
    assert set(hso.keys()) == {"hookEventName", "updatedToolOutput"}
    assert hso["hookEventName"] == "PostToolUse"

    # updatedToolOutput: the OBJECT form. String form is schema-rejected by
    # the CLI (probe verdict 1) — a regression here fails open + invisible.
    uto = hso["updatedToolOutput"]
    assert set(uto.keys()) == {"stdout", "stderr", "interrupted", "isImage"}
    assert isinstance(uto["stdout"], str)
    assert uto["stderr"] == ""
    assert uto["interrupted"] is False
    assert uto["isImage"] is False


@pytest.mark.unit
def test_suppress_summary_carries_artifact_ref_and_tail(
    captured_events: list[tuple[str, dict]],
) -> None:
    from skill_output_suppressor import process_hook_payload

    store = _FakeStore()
    payload = _load_fixture("bash_onex_node_large.json")
    original = payload["tool_response"]["stdout"]
    emission = process_hook_payload(payload, store_factory=lambda: store)

    summary = json.loads(emission)["hookSpecificOutput"]["updatedToolOutput"]["stdout"]
    expected_ref = f"sha256:{hashlib.sha256(original.encode('utf-8')).hexdigest()}"
    assert expected_ref in summary
    assert "output suppressed by hook backstop" in summary
    # Tail keeps the terminal result lines visible.
    assert "status=success handler=handler_delegate_skill" in summary
    # The replacement is materially smaller than the original.
    assert len(summary) < len(original)
    # Full bytes were captured BEFORE suppression.
    assert store.writes and store.writes[0]["data"] == original.encode("utf-8")


@pytest.mark.unit
def test_build_replacement_output_shape_is_pinned() -> None:
    from skill_output_suppressor import build_replacement_output

    assert build_replacement_output("SUMMARY") == {
        "hookSpecificOutput": {
            "hookEventName": "PostToolUse",
            "updatedToolOutput": {
                "stdout": "SUMMARY",
                "stderr": "",
                "interrupted": False,
                "isImage": False,
            },
        }
    }


# =============================================================================
# Passthrough cases: empty stdout, never the tool_info dict
# =============================================================================


@pytest.mark.unit
@pytest.mark.parametrize("fixture_name", _PASSTHROUGH_FIXTURES)
def test_passthrough_emits_nothing(fixture_name: str) -> None:
    from skill_output_suppressor import process_hook_payload

    store = _FakeStore()
    emission = process_hook_payload(
        _load_fixture(fixture_name), store_factory=lambda: store
    )
    assert emission == ""
    assert store.writes == [], "passthrough must not write artifacts"


@pytest.mark.unit
def test_receipt_passthrough_regardless_of_size() -> None:
    """Layer A idempotence: a ModelSkillResult payload is never rewritten."""
    from skill_output_suppressor import is_receipt_output, process_hook_payload

    payload = _load_fixture("bash_onex_receipt_large.json")
    stdout = payload["tool_response"]["stdout"]
    assert len(stdout) > 4000, "fixture must be over every threshold"
    assert is_receipt_output(stdout)
    assert process_hook_payload(payload, store_factory=_FakeStore) == ""


@pytest.mark.unit
def test_error_exit_code_never_suppressed() -> None:
    from skill_output_suppressor import EnumSuppressionDecision, evaluate_payload

    payload = _load_fixture("bash_pytest_error_large.json")
    evaluation = evaluate_payload(payload)
    assert evaluation.decision == EnumSuppressionDecision.passthrough_error


@pytest.mark.unit
def test_interrupted_never_suppressed() -> None:
    from skill_output_suppressor import EnumSuppressionDecision, evaluate_payload

    payload = _load_fixture("bash_onex_interrupted_large.json")
    evaluation = evaluate_payload(payload)
    assert evaluation.decision == EnumSuppressionDecision.passthrough_error


# =============================================================================
# Capture-before-suppress: fail-closed for capture, open for visibility
# =============================================================================


@pytest.mark.unit
def test_store_unavailable_passes_through() -> None:
    from skill_output_suppressor import CaptureUnavailableError, process_hook_payload

    def _unavailable() -> object:
        raise CaptureUnavailableError("store not importable")

    payload = _load_fixture("bash_onex_node_large.json")
    assert process_hook_payload(payload, store_factory=_unavailable) == ""


@pytest.mark.unit
def test_artifact_write_failure_passes_through() -> None:
    from skill_output_suppressor import process_hook_payload

    class _BrokenStore:
        def write_blob(self, data: bytes, **kwargs: object) -> object:
            raise OSError("disk full")

    payload = _load_fixture("bash_onex_node_large.json")
    assert process_hook_payload(payload, store_factory=_BrokenStore) == ""


@pytest.mark.unit
def test_emission_failure_still_suppresses(monkeypatch: pytest.MonkeyPatch) -> None:
    """Artifact exists -> a daemon outage must never re-flood Claude."""
    import emit_client_wrapper
    from skill_output_suppressor import process_hook_payload

    monkeypatch.setattr(emit_client_wrapper, "emit_event", lambda *a, **k: False)
    payload = _load_fixture("bash_onex_node_large.json")
    emission = process_hook_payload(payload, store_factory=_FakeStore)
    assert emission
    assert "hookSpecificOutput" in json.loads(emission)


# =============================================================================
# Capture events
# =============================================================================


@pytest.mark.unit
def test_capture_events_carry_required_fields(
    captured_events: list[tuple[str, dict]],
) -> None:
    from skill_output_suppressor import process_hook_payload

    payload = _load_fixture("bash_onex_node_large.json")
    original = payload["tool_response"]["stdout"]
    emission = process_hook_payload(payload, store_factory=_FakeStore)
    assert emission

    by_type = dict(captured_events)
    assert set(by_type) == {"artifact.captured", "tool.output.captured"}

    expected_ref = f"sha256:{hashlib.sha256(original.encode('utf-8')).hexdigest()}"

    artifact = by_type["artifact.captured"]
    # Required fields per the OMN-13092 EventRegistration.
    for field in (
        "artifact_ref",
        "artifact_hash",
        "artifact_size_bytes",
        "artifact_kind",
        "source_system",
        "correlation_id",
    ):
        assert artifact.get(field) not in (None, ""), f"missing {field}"
    assert artifact["artifact_ref"] == expected_ref
    assert artifact["artifact_hash"] == expected_ref.removeprefix("sha256:")
    assert artifact["artifact_size_bytes"] == len(original.encode("utf-8"))

    tool = by_type["tool.output.captured"]
    for field in ("tool_name", "suppression_decision", "correlation_id"):
        assert tool.get(field) not in (None, ""), f"missing {field}"
    assert tool["tool_name"] == "Bash"
    assert tool["suppression_decision"] in ("suppressed_success", "suppressed_large")
    assert tool["artifact_ref"] == expected_ref
    # The pair is correlated.
    assert tool["correlation_id"] == artifact["correlation_id"]


@pytest.mark.unit
def test_decision_granularity_success_vs_large() -> None:
    from skill_output_suppressor import (
        LARGE_OUTPUT_THRESHOLD,
        SUPPRESSION_THRESHOLD,
        EnumSuppressionDecision,
        evaluate_payload,
    )

    def _payload(size: int) -> dict:
        payload = _load_fixture("bash_onex_node_large.json")
        payload["tool_response"]["stdout"] = "x" * size
        return payload

    mid = evaluate_payload(_payload(SUPPRESSION_THRESHOLD + 100))
    assert mid.decision == EnumSuppressionDecision.suppressed_success
    big = evaluate_payload(_payload(LARGE_OUTPUT_THRESHOLD + 100))
    assert big.decision == EnumSuppressionDecision.suppressed_large


# =============================================================================
# Pattern coverage (F11)
# =============================================================================


@pytest.mark.unit
@pytest.mark.parametrize(
    "command",
    [
        "uv run onex run node_merge_sweep",
        "uv run onex node node_delegate_skill_orchestrator --timeout 300",
        "onex node node_gap_compute",
        "uv run onex run-node node_compliance_sweep --input payload.json",
        'cd "$ONEX_REGISTRY_ROOT/omnimarket" && uv run onex run node_session_orchestrator',
    ],
)
def test_onex_dispatch_commands_match(command: str) -> None:
    from skill_output_suppressor import detect_command_type

    assert detect_command_type(command) == "onex-dispatch"


@pytest.mark.unit
def test_legacy_tool_patterns_kept() -> None:
    from skill_output_suppressor import detect_command_type

    assert detect_command_type("uv run pytest tests/ -v") == "pytest"
    assert detect_command_type("mypy src/ --strict") == "mypy"
    assert detect_command_type("ruff check src/") == "ruff"
    assert detect_command_type("pre-commit run --all-files") == "pre-commit"
    assert detect_command_type("docker logs container") == "docker-logs"
    assert detect_command_type("bandit -r src/") == "bandit"
    assert detect_command_type("pyright src/") == "pyright"


@pytest.mark.unit
def test_non_dispatch_commands_do_not_match() -> None:
    from skill_output_suppressor import detect_command_type

    assert detect_command_type("git status") is None
    assert detect_command_type("ls -la") is None
    assert detect_command_type("onex hooks list") is None
    assert detect_command_type("uv run onex delegate 'do a thing'") is None


# =============================================================================
# Receipt sniff
# =============================================================================


@pytest.mark.unit
def test_is_receipt_output_rejects_non_receipts() -> None:
    from skill_output_suppressor import is_receipt_output

    assert not is_receipt_output("plain RuntimeLocal INFO log line")
    assert not is_receipt_output('{"status": "success"}')  # missing identity keys
    assert not is_receipt_output('["schema_version", "result_model", "result"]')
    assert not is_receipt_output('INFO start\n{"schema_version": 1}')  # mixed = leaked
    assert not is_receipt_output("")


@pytest.mark.unit
def test_is_receipt_output_accepts_skill_result_envelope() -> None:
    from skill_output_suppressor import is_receipt_output

    receipt = json.dumps(
        {
            "schema_version": {"major": 1, "minor": 0, "patch": 0},
            "result_model": "omnimarket.models.ModelDelegateSkillResponse",
            "result": {"response": "hello"},
            "skill_name": "delegate",
        }
    )
    assert is_receipt_output(receipt)
    assert is_receipt_output(receipt + "\n")


# =============================================================================
# Replay: recorded fixtures through the real CLI entrypoint
# =============================================================================


def _run_suppressor_subprocess(stdin_text: str) -> subprocess.CompletedProcess[str]:
    env = {k: v for k, v in os.environ.items() if k != "ONEX_ARTIFACT_STORE_ROOT"}
    return subprocess.run(  # noqa: S603 - fixed argv, test-only
        [sys.executable, str(_SUPPRESSOR)],
        input=stdin_text,
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )


@pytest.mark.unit
@pytest.mark.parametrize("fixture_name", _PASSTHROUGH_FIXTURES)
def test_replay_passthrough_fixtures_emit_nothing(fixture_name: str) -> None:
    proc = _run_suppressor_subprocess((_FIXTURES / fixture_name).read_text())
    assert proc.returncode == 0
    assert proc.stdout == ""


@pytest.mark.unit
def test_replay_suppress_fixture_without_store_passes_through() -> None:
    """Default store factory fail-closed pin.

    With the current core pin the store module is not importable; once the
    pin advances past OMN-13093 the stripped ONEX_ARTIFACT_STORE_ROOT makes
    the store constructor raise. Either way: capture unavailable -> NO
    suppression -> empty stdout. This pins the fail-closed default across
    both pin generations.
    """
    proc = _run_suppressor_subprocess(
        (_FIXTURES / "bash_onex_node_large.json").read_text()
    )
    assert proc.returncode == 0
    assert proc.stdout == ""


@pytest.mark.unit
def test_replay_malformed_stdin_is_silent_and_exits_zero() -> None:
    proc = _run_suppressor_subprocess("this is not json {")
    assert proc.returncode == 0
    assert proc.stdout == ""


@pytest.mark.unit
def test_real_artifact_store_roundtrip(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    captured_events: list[tuple[str, dict]],
) -> None:
    """End-to-end with the real omnibase_core store when importable.

    Skipped until the omniclaude core pin advances past OMN-13093; activates
    automatically on pin bump (no code change).
    """
    artifact_store = pytest.importorskip("omnibase_core.artifacts.artifact_store")
    from skill_output_suppressor import process_hook_payload

    monkeypatch.setenv("ONEX_ARTIFACT_STORE_ROOT", str(tmp_path))
    payload = _load_fixture("bash_onex_node_large.json")
    original = payload["tool_response"]["stdout"]

    emission = process_hook_payload(payload)
    assert emission

    expected_hex = hashlib.sha256(original.encode("utf-8")).hexdigest()
    summary = json.loads(emission)["hookSpecificOutput"]["updatedToolOutput"]["stdout"]
    assert f"sha256:{expected_hex}" in summary

    # Artifact is retrievable and hash-verified by the real store.
    from omnibase_core.models.artifacts.model_artifact_ref import ModelArtifactRef

    store = artifact_store.ArtifactStore()
    blob = store.read_blob(ModelArtifactRef(ref=f"sha256:{expected_hex}"))
    assert blob == original.encode("utf-8")


# =============================================================================
# Registration + single-emitter guard
# =============================================================================


@pytest.mark.unit
def test_hook_script_exists_and_is_executable() -> None:
    hook = _REPO_ROOT / "plugins/onex/hooks/scripts/post_tool_use_output_suppressor.sh"
    assert hook.exists(), f"Hook script not found: {hook}"
    assert os.access(hook, os.X_OK), "Hook script must be executable"


@pytest.mark.unit
def test_hook_registered_in_hooks_json() -> None:
    hooks_json = _REPO_ROOT / "plugins/onex/hooks/hooks.json"
    data = json.loads(hooks_json.read_text())
    found = any(
        "post_tool_use_output_suppressor.sh" in h["hooks"][0]["command"]
        for h in data["hooks"]["PostToolUse"]
    )
    assert found, (
        "post_tool_use_output_suppressor.sh not registered in hooks.json PostToolUse"
    )


@pytest.mark.unit
def test_suppressor_is_the_only_updated_tool_output_emitter() -> None:
    """Probe OMN-13090: LAST registered updatedToolOutput emitter wins.

    If any other hook on the Bash matcher ever emits the field after the
    suppressor in registration order, it silently overwrites the
    suppression. Guard: the string appears nowhere in the hooks tree except
    the suppressor module and its wrapper script.
    """
    allowed = {
        "skill_output_suppressor.py",
        "post_tool_use_output_suppressor.sh",
    }
    hooks_root = _REPO_ROOT / "plugins/onex/hooks"
    offenders = [
        path.name
        for pattern in ("*.py", "*.sh")
        for path in hooks_root.rglob(pattern)
        if "__pycache__" not in path.parts
        and "updatedToolOutput" in path.read_text(errors="ignore")
        and path.name not in allowed
    ]
    assert offenders == [], (
        f"unexpected updatedToolOutput emitters: {offenders} — the suppressor "
        "must remain the only emitter on the Bash matcher (OMN-13090 probe)"
    )
