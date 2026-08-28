# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""pytest entrypoint for the CR-thread-gate jq filter suite — OMN-16823.

The filters in ``scripts/check-unresolved-threads.sh`` decide whether the
required ``gate / CodeRabbit Thread Check`` context can ever go green. Two
separate defects (OMN-15532, OMN-16823) made that context unsatisfiable by
construction, so the suite that pins them is executed here as well as from the
pre-commit hook and the CI ``quality`` job — running it under pytest puts it in
the default local test run instead of leaving it to an opt-in shell invocation.

This module executes the real script's real filters against fixtures; it does
not re-implement them. The named assertions below are the OMN-16823 positive
case (the verbatim omnibase_core#1604 concession) and its permanent negative
controls, so a regression that silently drops a control fails here even if the
shell suite's own exit code were to be loosened.
"""

from __future__ import annotations

import pathlib
import shutil
import subprocess

import pytest

pytestmark = pytest.mark.unit

_SUITE = pathlib.Path(__file__).parent / "test_check_unresolved_threads.sh"

# Substrings of the PASS lines that must be present. Each names a distinct
# guarantee; losing any one of them silently is the failure mode this pins.
_REQUIRED_ASSERTIONS = (
    # OMN-16823 positive case.
    "Case K blocking=0",
    "Case K concession ack names class=agreement_deferral",
    # OMN-16823 permanent negative controls.
    "Case L blocking=1",
    "Case M blocking=1",
    "Case N blocking=1",
    "Case O blocking=1",
    "Case P blocking=1",
    "Case Q blocking=1",
    "Case R blocking=1",
    # No auto-resolution: pr_review_bot stays the sole resolver.
    "no thread-resolution mutation present in the gate script",
    # Pre-OMN-16823 guarantees that must not regress.
    "Case E blocking=1",
    "Case G SECRET_BLOCKING_JQ=1",
)


@pytest.mark.skipif(shutil.which("jq") is None, reason="jq not installed")
def test_cr_thread_gate_filter_suite_passes() -> None:
    result = subprocess.run(
        ["bash", str(_SUITE)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, (
        f"CR-thread-gate filter suite failed (exit {result.returncode}).\n"
        f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    )
    assert "ALL TESTS PASSED" in result.stdout

    missing = [a for a in _REQUIRED_ASSERTIONS if a not in result.stdout]
    assert not missing, (
        "CR-thread-gate filter suite no longer asserts: "
        f"{missing}. These are the OMN-16823 positive case and its permanent "
        "negative controls — do not delete them; a widened concession match "
        "without them makes the gate vacuous."
    )
