# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""Tests for the contract-declared runtime timeouts (OMN-21623).

The trace frame assembler and the diagnostics and health-check tools take their
subprocess and HTTP timeouts from ``ModelRuntimeTimeouts``, which the runtime
contract's ``timeouts:`` section declares with the ``${env.VAR:default}`` overlay
convention.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import yaml
from pydantic import ValidationError

from omniclaude.handlers.trace.frame_assembler import (
    default_checks,
    get_current_branch,
    run_git_diff_patch,
)
from omniclaude.lib.utils import diagnostics
from omniclaude.lib.utils.health_checks import Phase4HealthChecker
from omniclaude.models.model_runtime_timeouts import ModelRuntimeTimeouts

pytestmark = pytest.mark.unit

_FIELD_NAMES = tuple(ModelRuntimeTimeouts.model_fields)


def _distinct_timeouts() -> ModelRuntimeTimeouts:
    """One distinct value per field so a call site reading the wrong field is caught."""
    return ModelRuntimeTimeouts.model_validate(
        {name: 100.0 + index for index, name in enumerate(_FIELD_NAMES)}
    )


def _write_contract(path: Path, section: object) -> Path:
    path.write_text(yaml.safe_dump({"timeouts": section}), encoding="utf-8")
    return path


class TestContractLoading:
    def test_contract_declares_every_field(self) -> None:
        loaded = ModelRuntimeTimeouts.from_contract()
        assert set(loaded.model_dump()) == set(_FIELD_NAMES)
        assert all(value > 0 for value in loaded.model_dump().values())

    def test_env_overlay_overrides_the_contract_default(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        baseline = ModelRuntimeTimeouts.from_contract()
        monkeypatch.setenv(
            "OMNICLAUDE_TIMEOUT_TRACE_GIT_DIFF_SECONDS",
            str(baseline.trace_git_diff_seconds + 7),
        )
        overlaid = ModelRuntimeTimeouts.from_contract()
        assert overlaid.trace_git_diff_seconds == baseline.trace_git_diff_seconds + 7
        assert (
            overlaid.trace_git_identity_seconds == baseline.trace_git_identity_seconds
        )

    def test_missing_field_fails_to_load(self, tmp_path: Path) -> None:
        values = dict.fromkeys(_FIELD_NAMES, 1)
        values.pop("trace_lint_check_seconds")
        contract = _write_contract(tmp_path / "contract.yaml", values)
        with pytest.raises(ValidationError, match="trace_lint_check_seconds"):
            ModelRuntimeTimeouts.from_contract(contract)

    def test_missing_section_fails_to_load(self, tmp_path: Path) -> None:
        contract = tmp_path / "contract.yaml"
        contract.write_text(yaml.safe_dump({"other": {}}), encoding="utf-8")
        with pytest.raises(ValueError, match="timeouts"):
            ModelRuntimeTimeouts.from_contract(contract)

    def test_non_positive_value_fails_to_load(self, tmp_path: Path) -> None:
        values = dict.fromkeys(_FIELD_NAMES, 1)
        values["diagnostics_http_seconds"] = 0
        contract = _write_contract(tmp_path / "contract.yaml", values)
        with pytest.raises(ValidationError, match="diagnostics_http_seconds"):
            ModelRuntimeTimeouts.from_contract(contract)


class TestTraceCallSites:
    def test_git_diff_uses_the_injected_timeout(self) -> None:
        timeouts = _distinct_timeouts()
        with patch(
            "omniclaude.handlers.trace.frame_assembler.subprocess.run"
        ) as mock_run:
            mock_run.return_value = MagicMock(stdout="", returncode=0)
            run_git_diff_patch("/repo", timeouts)
        seen = {call.kwargs["timeout"] for call in mock_run.call_args_list}
        assert seen == {timeouts.trace_git_diff_seconds}

    def test_identity_lookup_uses_the_injected_timeout(self) -> None:
        timeouts = _distinct_timeouts()
        with patch(
            "omniclaude.handlers.trace.frame_assembler.subprocess.run"
        ) as mock_run:
            mock_run.return_value = MagicMock(stdout="main\n", returncode=0)
            get_current_branch("/repo", timeouts)
        assert (
            mock_run.call_args.kwargs["timeout"] == timeouts.trace_git_identity_seconds
        )

    def test_default_checks_carry_the_injected_timeouts(self) -> None:
        timeouts = _distinct_timeouts()
        by_tool = {spec.command[2]: spec.timeout for spec in default_checks(timeouts)}
        assert by_tool == {
            "ruff": timeouts.trace_lint_check_seconds,
            "mypy": timeouts.trace_type_check_seconds,
            "pyright": timeouts.trace_type_check_seconds,
        }


class TestToolCallSites:
    def test_service_checks_use_the_injected_timeouts(self) -> None:
        timeouts = _distinct_timeouts()
        with patch("omniclaude.lib.utils.diagnostics.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(stdout="{}", stderr="", returncode=0)
            diagnostics.check_running_services(timeouts)
        seen = [call.kwargs["timeout"] for call in mock_run.call_args_list]
        assert seen.count(timeouts.diagnostics_curl_health_seconds) == 3
        assert seen.count(timeouts.diagnostics_docker_seconds) == 3
        assert len(seen) == 6

    def test_network_check_uses_the_injected_timeout(self) -> None:
        timeouts = _distinct_timeouts()
        with patch("omniclaude.lib.utils.diagnostics.requests.get") as mock_get:
            mock_get.return_value = MagicMock(status_code=200)
            diagnostics.check_network_connectivity(timeouts)
        assert {call.kwargs["timeout"] for call in mock_get.call_args_list} == {
            timeouts.diagnostics_http_seconds
        }

    def test_health_checker_uses_the_injected_timeouts(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("ONEX_STATE_DIR", str(tmp_path))
        timeouts = _distinct_timeouts()
        checker = Phase4HealthChecker(base_url="http://health.test", timeouts=timeouts)
        ok = MagicMock(
            status_code=200, headers={"content-type": "text/plain"}, text="ok"
        )
        with (
            patch(
                "omniclaude.lib.utils.health_checks.requests.get", return_value=ok
            ) as get,
            patch(
                "omniclaude.lib.utils.health_checks.requests.post", return_value=ok
            ) as post,
        ):
            checker.check_intelligence_service()
            checker.check_database_connectivity()
            checker.check_lineage_endpoint()
            checker.check_feedback_endpoint()
        assert [call.kwargs["timeout"] for call in get.call_args_list] == [
            timeouts.health_check_base_seconds,
            timeouts.health_check_pattern_seconds,
        ]
        assert [call.kwargs["timeout"] for call in post.call_args_list] == [
            timeouts.health_check_post_seconds,
            timeouts.health_check_post_seconds,
        ]


class TestReplayAndCoverageCallSites:
    def test_replay_helpers_use_the_injected_timeouts(self, tmp_path: Path) -> None:
        from omniclaude.trace.replay_engine import (
            _apply_patch,
            _checkout_commit,
            _clone_repo_to_tempdir,
        )

        timeouts = _distinct_timeouts()
        with patch("omniclaude.trace.replay_engine.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0)
            _clone_repo_to_tempdir("/repo", "/tmpdir", timeouts)
            _checkout_commit("abc123", str(tmp_path), timeouts)
            _apply_patch("diff", str(tmp_path), timeouts)
        assert [call.kwargs["timeout"] for call in mock_run.call_args_list] == [
            timeouts.replay_clone_seconds,
            timeouts.replay_checkout_seconds,
            timeouts.replay_apply_seconds,
        ]

    def test_coverage_scanner_reads_timeouts_from_the_injected_model(
        self, tmp_path: Path
    ) -> None:
        from omniclaude.coverage.scanner import CoverageScanner

        timeouts = _distinct_timeouts()
        scanner = object.__new__(CoverageScanner)
        scanner._limits = timeouts
        with patch("omniclaude.coverage.scanner.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=1, stdout="", stderr="")
            scanner._get_recently_changed_files(tmp_path)
        assert mock_run.call_args.kwargs["timeout"] == timeouts.coverage_git_log_seconds
