"""Unit tests for omniclaude.trace.failure_signature.

Tests cover:
- normalize_failure_output() strips timestamps, PIDs, paths, memory addresses
- compute_failure_signature() produces deterministic fingerprints
- Same failure from different runs produces same fingerprint
- Different failures produce different fingerprints
- FailureSignature model validates correctly
- Primary signal extraction
"""

from __future__ import annotations

from pydantic import ValidationError

from omniclaude.trace.change_frame import FailureType
from omniclaude.trace.failure_signature import (
    FailureSignature,
    _derive_signature_id,
    _extract_primary_signal,
    compute_failure_signature,
    normalize_failure_output,
)

# ---------------------------------------------------------------------------
# normalize_failure_output tests
# ---------------------------------------------------------------------------


class TestNormalizeFailureOutput:
    def test_strips_iso_timestamp(self) -> None:
        """ISO-8601 timestamps must be stripped."""
        raw = "FAILED at 2026-02-19T14:22:31Z — AssertionError"
        normalized = normalize_failure_output(raw, "/repo")
        assert "2026-02-19" not in normalized
        assert "14:22:31" not in normalized
        assert "AssertionError" in normalized

    def test_strips_iso_timestamp_with_microseconds(self) -> None:
        """ISO-8601 timestamps with microseconds must be stripped."""
        raw = "2026-02-19T14:22:31.123456Z test failed"
        normalized = normalize_failure_output(raw, "/repo")
        assert "2026" not in normalized
        assert "test failed" in normalized

    def test_strips_pid(self) -> None:
        """PID references must be stripped."""
        raw = "Process pid=12345 exited with code 1"
        normalized = normalize_failure_output(raw, "/repo")
        assert "12345" not in normalized
        assert "exited with code 1" in normalized

    def test_strips_pid_uppercase(self) -> None:
        """PID in uppercase format must be stripped."""
        raw = "Process PID: 9876 crashed"
        normalized = normalize_failure_output(raw, "/repo")
        assert "9876" not in normalized

    def test_strips_memory_address(self) -> None:
        """Memory addresses (0x...) must be stripped."""
        raw = "Object at 0xdeadbeef1234abcd raised AttributeError"
        normalized = normalize_failure_output(raw, "/repo")
        assert "0xdeadbeef1234abcd" not in normalized
        assert "AttributeError" in normalized

    def test_strips_absolute_path(self) -> None:
        """Absolute paths with repo_root prefix must be stripped."""
        raw = "Error in /home/user/myproject/src/router.py line 42"
        normalized = normalize_failure_output(raw, "/home/user/myproject")
        assert "/home/user/myproject" not in normalized
        assert "src/router.py" in normalized

    def test_strips_absolute_path_without_trailing_slash(self) -> None:
        """Absolute paths work even when repo_root has no trailing slash."""
        raw = "Error in /home/user/myproject/src/foo.py"
        normalized = normalize_failure_output(raw, "/home/user/myproject/")
        assert "/home/user/myproject" not in normalized

    def test_empty_repo_root_no_crash(self) -> None:
        """Empty repo_root should not cause errors."""
        raw = "Some error output"
        normalized = normalize_failure_output(raw, "")
        assert normalized == raw  # No path stripping when repo_root is empty

    def test_non_volatile_content_preserved(self) -> None:
        """Error messages, exception types, test names must be preserved."""
        raw = "FAILED tests/test_router.py::TestRouter::test_intent - AssertionError"
        normalized = normalize_failure_output(raw, "/repo")
        assert "FAILED" in normalized
        assert "tests/test_router.py" in normalized
        assert "TestRouter" in normalized
        assert "test_intent" in normalized
        assert "AssertionError" in normalized

    def test_multiple_timestamps_all_stripped(self) -> None:
        """Multiple timestamps in one output are all stripped."""
        raw = "Started 2026-02-19T10:00:00Z, failed at 2026-02-19T10:05:30Z"
        normalized = normalize_failure_output(raw, "/repo")
        assert "2026-02-19" not in normalized

    def test_multiple_pids_all_stripped(self) -> None:
        """Multiple PID references are all stripped."""
        raw = "Worker pid=1234 spawned child pid=5678"
        normalized = normalize_failure_output(raw, "/repo")
        assert "1234" not in normalized
        assert "5678" not in normalized


# ---------------------------------------------------------------------------
# compute_failure_signature tests — determinism
# ---------------------------------------------------------------------------


class TestComputeFailureSignatureDeterminism:
    """The core property: same failure => same fingerprint."""

    REPO_ROOT = "/home/user/myproject"
    REPRO_CMD = "uv run pytest tests/test_router.py::TestRouter::test_intent -v"
    SUSPECTED_FILES = ["src/router.py"]

    BASE_OUTPUT = """
FAILED tests/test_router.py::TestRouter::test_intent - AssertionError: Expected 200, got 404
AssertionError: Expected 200, got 404
""".strip()

    def test_same_output_same_fingerprint(self) -> None:
        """Identical raw output must produce identical fingerprint."""
        sig1 = compute_failure_signature(
            failure_type=FailureType.TEST_FAIL,
            raw_output=self.BASE_OUTPUT,
            repo_root=self.REPO_ROOT,
            repro_command=self.REPRO_CMD,
            suspected_files=self.SUSPECTED_FILES,
        )
        sig2 = compute_failure_signature(
            failure_type=FailureType.TEST_FAIL,
            raw_output=self.BASE_OUTPUT,
            repo_root=self.REPO_ROOT,
            repro_command=self.REPRO_CMD,
            suspected_files=self.SUSPECTED_FILES,
        )
        assert sig1.fingerprint == sig2.fingerprint
        assert sig1.signature_id == sig2.signature_id

    def test_timestamp_difference_same_fingerprint(self) -> None:
        """Same failure from different runs (different timestamps) must produce same fingerprint."""
        output_run1 = f"2026-02-19T14:22:31Z {self.BASE_OUTPUT}"
        output_run2 = f"2026-02-20T09:15:00Z {self.BASE_OUTPUT}"

        sig1 = compute_failure_signature(
            failure_type=FailureType.TEST_FAIL,
            raw_output=output_run1,
            repo_root=self.REPO_ROOT,
            repro_command=self.REPRO_CMD,
            suspected_files=self.SUSPECTED_FILES,
        )
        sig2 = compute_failure_signature(
            failure_type=FailureType.TEST_FAIL,
            raw_output=output_run2,
            repo_root=self.REPO_ROOT,
            repro_command=self.REPRO_CMD,
            suspected_files=self.SUSPECTED_FILES,
        )
        assert sig1.fingerprint == sig2.fingerprint

    def test_pid_difference_same_fingerprint(self) -> None:
        """Same failure with different PIDs must produce same fingerprint."""
        output_run1 = f"pid=11111 {self.BASE_OUTPUT}"
        output_run2 = f"pid=99999 {self.BASE_OUTPUT}"

        sig1 = compute_failure_signature(
            failure_type=FailureType.TEST_FAIL,
            raw_output=output_run1,
            repo_root=self.REPO_ROOT,
            repro_command=self.REPRO_CMD,
            suspected_files=self.SUSPECTED_FILES,
        )
        sig2 = compute_failure_signature(
            failure_type=FailureType.TEST_FAIL,
            raw_output=output_run2,
            repo_root=self.REPO_ROOT,
            repro_command=self.REPRO_CMD,
            suspected_files=self.SUSPECTED_FILES,
        )
        assert sig1.fingerprint == sig2.fingerprint

    def test_path_difference_same_fingerprint(self) -> None:
        """Same failure from different repo root paths must produce same fingerprint."""
        output_user1 = f"/home/alice/myproject/tests/test_router.py {self.BASE_OUTPUT}"
        output_user2 = f"/home/bob/myproject/tests/test_router.py {self.BASE_OUTPUT}"

        sig1 = compute_failure_signature(
            failure_type=FailureType.TEST_FAIL,
            raw_output=output_user1,
            repo_root="/home/alice/myproject",
            repro_command=self.REPRO_CMD,
            suspected_files=self.SUSPECTED_FILES,
        )
        sig2 = compute_failure_signature(
            failure_type=FailureType.TEST_FAIL,
            raw_output=output_user2,
            repo_root="/home/bob/myproject",
            repro_command=self.REPRO_CMD,
            suspected_files=self.SUSPECTED_FILES,
        )
        assert sig1.fingerprint == sig2.fingerprint

    def test_memory_address_difference_same_fingerprint(self) -> None:
        """Same failure with different memory addresses must produce same fingerprint."""
        output_run1 = f"0xdeadbeef1234 {self.BASE_OUTPUT}"
        output_run2 = f"0xcafebabe5678 {self.BASE_OUTPUT}"

        sig1 = compute_failure_signature(
            failure_type=FailureType.TEST_FAIL,
            raw_output=output_run1,
            repo_root=self.REPO_ROOT,
            repro_command=self.REPRO_CMD,
            suspected_files=self.SUSPECTED_FILES,
        )
        sig2 = compute_failure_signature(
            failure_type=FailureType.TEST_FAIL,
            raw_output=output_run2,
            repo_root=self.REPO_ROOT,
            repro_command=self.REPRO_CMD,
            suspected_files=self.SUSPECTED_FILES,
        )
        assert sig1.fingerprint == sig2.fingerprint


# ---------------------------------------------------------------------------
# compute_failure_signature tests — different failures => different fingerprints
# ---------------------------------------------------------------------------


class TestComputeFailureSignatureDifferentFailures:
    """Different failures must produce different fingerprints."""

    REPO_ROOT = "/repo"
    REPRO_CMD = "pytest"

    def test_different_exception_different_fingerprint(self) -> None:
        """AssertionError vs TypeError must produce different fingerprints."""
        sig1 = compute_failure_signature(
            failure_type=FailureType.TEST_FAIL,
            raw_output="AssertionError: Expected 200, got 404",
            repo_root=self.REPO_ROOT,
            repro_command=self.REPRO_CMD,
            suspected_files=[],
        )
        sig2 = compute_failure_signature(
            failure_type=FailureType.TEST_FAIL,
            raw_output="TypeError: 'NoneType' object is not callable",
            repo_root=self.REPO_ROOT,
            repro_command=self.REPRO_CMD,
            suspected_files=[],
        )
        assert sig1.fingerprint != sig2.fingerprint

    def test_different_test_name_different_fingerprint(self) -> None:
        """Same exception in different tests must produce different fingerprints."""
        sig1 = compute_failure_signature(
            failure_type=FailureType.TEST_FAIL,
            raw_output="FAILED test_router.py::test_intent AssertionError",
            repo_root=self.REPO_ROOT,
            repro_command=self.REPRO_CMD,
            suspected_files=[],
        )
        sig2 = compute_failure_signature(
            failure_type=FailureType.TEST_FAIL,
            raw_output="FAILED test_models.py::test_validation AssertionError",
            repo_root=self.REPO_ROOT,
            repro_command=self.REPRO_CMD,
            suspected_files=[],
        )
        assert sig1.fingerprint != sig2.fingerprint

    def test_different_failure_type_different_fingerprint(self) -> None:
        """Type error vs test failure must produce different fingerprints."""
        sig1 = compute_failure_signature(
            failure_type=FailureType.TEST_FAIL,
            raw_output="error: test failed",
            repo_root=self.REPO_ROOT,
            repro_command=self.REPRO_CMD,
            suspected_files=[],
        )
        sig2 = compute_failure_signature(
            failure_type=FailureType.TYPE_FAIL,
            raw_output="error: type mismatch",
            repo_root=self.REPO_ROOT,
            repro_command=self.REPRO_CMD,
            suspected_files=[],
        )
        assert sig1.fingerprint != sig2.fingerprint


# ---------------------------------------------------------------------------
# FailureSignature model tests
# ---------------------------------------------------------------------------


class TestFailureSignatureModel:
    def test_happy_path(self) -> None:
        """FailureSignature can be constructed with all required fields."""
        sig = FailureSignature(
            signature_id="abc123def456789a",
            failure_type=FailureType.TEST_FAIL,
            primary_signal="AssertionError in test_router",
            fingerprint="a" * 64,
            repro_command="pytest tests/",
            suspected_files=["src/router.py"],
        )
        assert sig.signature_id == "abc123def456789a"
        assert sig.failure_type == FailureType.TEST_FAIL

    def test_empty_signature_id_raises(self) -> None:
        """Empty signature_id must raise ValidationError."""
        with pytest.raises(ValidationError):
            FailureSignature(
                signature_id="  ",
                failure_type=FailureType.TEST_FAIL,
                primary_signal="signal",
                fingerprint="a" * 64,
                repro_command="cmd",
            )

    def test_frozen_mutation_raises(self) -> None:
        """Mutating a frozen FailureSignature must raise."""
        sig = FailureSignature(
            signature_id="abc123",
            failure_type=FailureType.LINT_FAIL,
            primary_signal="signal",
            fingerprint="a" * 64,
            repro_command="ruff check",
        )
        with pytest.raises((ValidationError, TypeError)):
            sig.signature_id = "new-id"  # type: ignore[misc]

    def test_serialization_round_trip(self) -> None:
        """FailureSignature must survive model_dump/model_validate round-trip."""
        sig = FailureSignature(
            signature_id="abc123def456",
            failure_type=FailureType.BUILD_FAIL,
            primary_signal="Build failed",
            fingerprint="b" * 64,
            repro_command="make build",
            suspected_files=["Makefile"],
        )
        data = sig.model_dump()
        sig2 = FailureSignature.model_validate(data)
        assert sig == sig2

    def test_signature_id_length(self) -> None:
        """signature_id from compute must be 16 chars."""
        sig = compute_failure_signature(
            failure_type=FailureType.TEST_FAIL,
            raw_output="FAILED test_foo.py - AssertionError",
            repo_root="/repo",
            repro_command="pytest",
            suspected_files=[],
        )
        assert len(sig.signature_id) == 16

    def test_fingerprint_is_sha256_hex(self) -> None:
        """fingerprint must be 64-char hex string (SHA-256)."""
        sig = compute_failure_signature(
            failure_type=FailureType.TEST_FAIL,
            raw_output="FAILED test_foo.py - AssertionError",
            repo_root="/repo",
            repro_command="pytest",
            suspected_files=[],
        )
        assert len(sig.fingerprint) == 64
        assert all(c in "0123456789abcdef" for c in sig.fingerprint)


# ---------------------------------------------------------------------------
# Helper function tests
# ---------------------------------------------------------------------------


class TestExtractPrimarySignal:
    def test_first_meaningful_line(self) -> None:
        """First non-empty, non-separator line is returned."""
        output = "\n\n===\nAssertionError: Expected 200\nmore lines..."
        signal = _extract_primary_signal(output)
        assert signal == "AssertionError: Expected 200"

    def test_truncates_to_200_chars(self) -> None:
        """Primary signal is truncated to 200 chars."""
        long_line = "E" * 300
        signal = _extract_primary_signal(long_line)
        assert len(signal) <= 200

    def test_empty_output_fallback(self) -> None:
        """Empty output returns fallback message."""
        signal = _extract_primary_signal("")
        assert signal == "unknown failure"

    def test_only_separators_fallback(self) -> None:
        """Output with only separators returns fallback."""
        signal = _extract_primary_signal("===\n---\n***")
        assert signal == "unknown failure"


class TestDeriveSignatureId:
    def test_first_16_chars(self) -> None:
        """signature_id is first 16 chars of fingerprint."""
        fp = "a" * 64
        sig_id = _derive_signature_id(fp)
        assert sig_id == "a" * 16

    def test_different_fingerprints_different_ids(self) -> None:
        """Different fingerprints produce different signature IDs."""
        fp1 = "abc" + "0" * 61
        fp2 = "def" + "0" * 61
        assert _derive_signature_id(fp1) != _derive_signature_id(fp2)


class TestEmptyRawOutputRaises:
    def test_empty_output_raises_value_error(self) -> None:
        """Empty raw_output must raise ValueError."""
        with pytest.raises(ValueError, match="must not be empty"):
            compute_failure_signature(
                failure_type=FailureType.TEST_FAIL,
                raw_output="",
                repo_root="/repo",
                repro_command="pytest",
                suspected_files=[],
            )

    def test_whitespace_only_output_raises(self) -> None:
        """Whitespace-only raw_output must raise ValueError."""
        with pytest.raises(ValueError, match="must not be empty"):
            compute_failure_signature(
                failure_type=FailureType.TEST_FAIL,
                raw_output="   \n  ",
                repo_root="/repo",
                repro_command="pytest",
                suspected_files=[],
            )


# Need to import pytest for the validation error test
import pytest  # noqa: E402
