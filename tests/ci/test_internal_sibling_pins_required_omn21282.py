# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""OMN-21282 AC2: internal-sibling-pins runs as a required context.

The check runs as the ``internal-sibling-pins`` job of ci.yml, which feeds
``Quality Gate``, a REQUIRED row of .github/required-checks.yaml. It reports on
every event (no ``paths:`` filter, ``if: always()``), and Quality Gate reads its
result with no skip allowance, so a refusal or a skip fails the required context.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

pytestmark = pytest.mark.unit

_ROOT = Path(__file__).resolve().parents[2]
_JOB = "internal-sibling-pins"


def _ci() -> dict:
    return yaml.safe_load((_ROOT / ".github/workflows/ci.yml").read_text())


def test_job_runs_the_handler_on_every_event() -> None:
    job = _ci()["jobs"][_JOB]
    assert job["if"] == "always()"
    run = "\n".join(str(s.get("run", "")) for s in job["steps"])
    assert "omniclaude.handlers.handler_internal_sibling_pins" in run
    assert "--needs-tags" in run and "--dev-tags" in run
    assert "HEAD^1:uv.lock" in run
    assert "continue-on-error" not in job


def test_quality_gate_reads_the_result_with_no_skip_allowance() -> None:
    gate = _ci()["jobs"]["quality-gate"]
    assert _JOB in gate["needs"]
    script = "\n".join(str(s.get("run", "")) for s in gate["steps"])
    assert f'"{_JOB}=${{{{ needs.{_JOB}.result }}}}"' in script
    skip_policy = script[script.index('case "$NAME" in') :]
    assert _JOB not in skip_policy.split("esac", 1)[0]


def test_quality_gate_is_a_required_context() -> None:
    manifest = yaml.safe_load((_ROOT / ".github/required-checks.yaml").read_text())
    rows = {row["name"]: row for row in manifest["gates"]}
    assert rows["Quality Gate"]["mode"] == "REQUIRED"
    assert rows["Quality Gate"]["job_path"] == ["quality-gate"]
