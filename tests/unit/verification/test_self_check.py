# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Unit tests for self-check (A) runner."""

from __future__ import annotations

import pytest
import yaml

from omniclaude.verification.self_check import (
    EnumCheckType,
    ModelMechanicalCheck,
    ModelTaskContract,
    run_self_check,
)


@pytest.mark.unit
class TestSelfCheckAllPass:
    """Self-check returns PASS when all mechanical checks succeed."""

    def test_single_check_passes(self, tmp_path: object) -> None:
        output_file = tmp_path / "output.txt"  # type: ignore[operator]
        output_file.write_text("done")
        contract = ModelTaskContract(
            task_id="task-1",
            definition_of_done=[
                ModelMechanicalCheck(
                    criterion="File exists",
                    check=f"test -f {output_file}",
                    check_type=EnumCheckType.COMMAND_EXIT_0,
                )
            ],
        )
        result = run_self_check(contract, working_dir=str(tmp_path))

        assert result.passed is True
        assert len(result.checks) == 1
        assert result.checks[0].status == "PASS"
        assert result.checks[0].exit_code == 0
        assert result.task_id == "task-1"
        assert result.contract_fingerprint != ""
        assert result.timestamp != ""
        assert result.working_directory == str(tmp_path)
        assert result.total_duration_seconds >= 0.0

    def test_multiple_checks_all_pass(self, tmp_path: object) -> None:
        (tmp_path / "a.txt").write_text("a")  # type: ignore[operator]
        (tmp_path / "b.txt").write_text("b")  # type: ignore[operator]
        contract = ModelTaskContract(
            task_id="task-multi",
            definition_of_done=[
                ModelMechanicalCheck(
                    criterion="File a exists",
                    check=f"test -f {tmp_path}/a.txt",  # type: ignore[operator]
                ),
                ModelMechanicalCheck(
                    criterion="File b exists",
                    check=f"test -f {tmp_path}/b.txt",  # type: ignore[operator]
                ),
            ],
        )
        result = run_self_check(contract, working_dir=str(tmp_path))

        assert result.passed is True
        assert len(result.checks) == 2
        assert all(c.status == "PASS" for c in result.checks)


@pytest.mark.unit
class TestSelfCheckPartialFail:
    """Self-check returns FAIL when any check fails."""

    def test_missing_file_fails(self, tmp_path: object) -> None:
        contract = ModelTaskContract(
            task_id="task-2",
            definition_of_done=[
                ModelMechanicalCheck(
                    criterion="File exists",
                    check=f"test -f {tmp_path}/missing.txt",  # type: ignore[operator]
                    check_type=EnumCheckType.COMMAND_EXIT_0,
                )
            ],
        )
        result = run_self_check(contract, working_dir=str(tmp_path))

        assert result.passed is False
        assert result.checks[0].status == "FAIL"
        assert result.checks[0].exit_code == 1

    def test_mixed_pass_fail(self, tmp_path: object) -> None:
        (tmp_path / "exists.txt").write_text("yes")  # type: ignore[operator]
        contract = ModelTaskContract(
            task_id="task-mixed",
            definition_of_done=[
                ModelMechanicalCheck(
                    criterion="Existing file",
                    check=f"test -f {tmp_path}/exists.txt",  # type: ignore[operator]
                ),
                ModelMechanicalCheck(
                    criterion="Missing file",
                    check=f"test -f {tmp_path}/nope.txt",  # type: ignore[operator]
                ),
            ],
        )
        result = run_self_check(contract, working_dir=str(tmp_path))

        assert result.passed is False
        assert result.checks[0].status == "PASS"
        assert result.checks[1].status == "FAIL"


@pytest.mark.unit
class TestSelfCheckTimeout:
    """Self-check handles timeouts gracefully."""

    def test_timeout_produces_fail(self, tmp_path: object) -> None:
        contract = ModelTaskContract(
            task_id="task-timeout",
            definition_of_done=[
                ModelMechanicalCheck(
                    criterion="Slow command",
                    check="sleep 10",
                )
            ],
        )
        result = run_self_check(contract, working_dir=str(tmp_path), timeout=1)

        assert result.passed is False
        assert result.checks[0].status == "FAIL"
        assert result.checks[0].exit_code is None
        assert "Timeout" in result.checks[0].stderr


@pytest.mark.unit
class TestSelfCheckEvidence:
    """Evidence metadata is correctly populated."""

    def test_to_yaml_roundtrip(self, tmp_path: object) -> None:
        (tmp_path / "f.txt").write_text("ok")  # type: ignore[operator]
        contract = ModelTaskContract(
            task_id="task-yaml",
            definition_of_done=[
                ModelMechanicalCheck(
                    criterion="Check",
                    check=f"test -f {tmp_path}/f.txt",  # type: ignore[operator]
                )
            ],
        )
        result = run_self_check(contract, working_dir=str(tmp_path))
        yaml_str = result.to_yaml()

        parsed = yaml.safe_load(yaml_str)
        assert parsed["task_id"] == "task-yaml"
        assert parsed["passed"] is True
        assert len(parsed["checks"]) == 1
        assert parsed["checks"][0]["status"] == "PASS"
        assert "timestamp" in parsed
        assert "contract_fingerprint" in parsed
        assert "working_directory" in parsed

    def test_stdout_stderr_captured(self, tmp_path: object) -> None:
        contract = ModelTaskContract(
            task_id="task-output",
            definition_of_done=[
                ModelMechanicalCheck(
                    criterion="Echo test",
                    check="echo hello",
                )
            ],
        )
        result = run_self_check(contract, working_dir=str(tmp_path))

        assert result.passed is True
        assert "hello" in result.checks[0].stdout


@pytest.mark.unit
class TestModelTaskContract:
    """Contract model behavior."""

    def test_contract_is_frozen(self) -> None:
        contract = ModelTaskContract(
            task_id="task-frozen",
            definition_of_done=[],
        )
        with pytest.raises(Exception):
            contract.task_id = "modified"  # type: ignore[misc]

    def test_yaml_roundtrip(self) -> None:
        contract = ModelTaskContract(
            task_id="task-rt",
            parent_ticket="OMN-7028",
            repo="omniclaude",
            requirements=["Implement self-check"],
            definition_of_done=[
                ModelMechanicalCheck(
                    criterion="Tests pass",
                    check="uv run pytest -m unit -q",
                    check_type=EnumCheckType.COMMAND_EXIT_0,
                )
            ],
        )
        yaml_str = contract.to_yaml()
        loaded = ModelTaskContract.from_yaml(yaml_str)
        assert loaded.task_id == contract.task_id
        assert loaded.parent_ticket == "OMN-7028"
        assert len(loaded.definition_of_done) == 1

    def test_fingerprint_deterministic(self) -> None:
        contract = ModelTaskContract(
            task_id="task-fp",
            requirements=["req1"],
            definition_of_done=[ModelMechanicalCheck(criterion="c1", check="true")],
        )
        assert contract.fingerprint == contract.fingerprint
        assert len(contract.fingerprint) == 16

    def test_empty_definition_of_done(self) -> None:
        contract = ModelTaskContract(
            task_id="task-empty",
            definition_of_done=[],
        )
        result = run_self_check(contract)
        assert result.passed is True
        assert len(result.checks) == 0
