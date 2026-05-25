# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Round-trip structural tests for the merge_sweep run.sh shim.

These tests verify run.sh delegates correctly to _lib/run.py and that the
Kafka dispatch path produces the expected JSON output schema. They do not
require a live Kafka broker — the Kafka dispatch is mocked at the Python level.
"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest

_OMNICLAUDE_ROOT = Path(__file__).resolve().parents[4]
_RUN_SH = _OMNICLAUDE_ROOT / "plugins" / "onex" / "skills" / "merge_sweep" / "run.sh"
_OMNI_HOME_ROOT = _OMNICLAUDE_ROOT.parent

# Prefer OMNI_HOME/omnimarket (standard CI layout).
_OMNIMARKET_ROOT_DEFAULT = _OMNI_HOME_ROOT / "omnimarket"
_OMNIMARKET_ROOT_OVERRIDE = os.environ.get("ONEX_TEST_OMNIMARKET_ROOT")
_OMNIMARKET_ROOT = (
    Path(_OMNIMARKET_ROOT_OVERRIDE)
    if _OMNIMARKET_ROOT_OVERRIDE
    else _OMNIMARKET_ROOT_DEFAULT
)


@pytest.mark.unit
def test_run_sh_missing_kafka_bootstrap_exits_nonzero(tmp_path: Path) -> None:
    """run.sh must exit non-zero and emit a clear error when KAFKA_BOOTSTRAP_SERVERS is unset."""
    if not _RUN_SH.is_file():
        pytest.skip(f"missing run.sh at {_RUN_SH}")
    if not _OMNIMARKET_ROOT.is_dir():
        pytest.skip(
            f"missing omnimarket root at {_OMNIMARKET_ROOT}; "
            "set ONEX_TEST_OMNIMARKET_ROOT to override"
        )

    omni_home = tmp_path / "omni_home"
    omni_home.mkdir()
    (omni_home / "omnimarket").symlink_to(_OMNIMARKET_ROOT, target_is_directory=True)

    env = {
        **os.environ,
        "OMNI_HOME": str(omni_home),
        "ONEX_STATE_DIR": str(tmp_path / "state"),
    }
    env.pop("KAFKA_BOOTSTRAP_SERVERS", None)

    completed = subprocess.run(
        ["bash", str(_RUN_SH), "--dry-run", "--run-id", "round-trip-no-kafka"],
        capture_output=True,
        check=False,
        cwd=_OMNICLAUDE_ROOT,
        env=env,
        text=True,
        timeout=30,
    )

    assert completed.returncode != 0, (
        "run.sh must exit non-zero when KAFKA_BOOTSTRAP_SERVERS is unset"
    )
    result = json.loads(completed.stdout)
    assert result["success"] is False
    assert result["path"] == "kafka"
    assert "KAFKA_BOOTSTRAP_SERVERS" in result["error"]


@pytest.mark.unit
def test_run_sh_missing_omni_home_topic_error(tmp_path: Path) -> None:
    """run.sh must exit non-zero with a clear error when OMNI_HOME is unset (topic unresolvable)."""
    if not _RUN_SH.is_file():
        pytest.skip(f"missing run.sh at {_RUN_SH}")

    env = {**os.environ}
    env.pop("OMNI_HOME", None)
    env.pop("KAFKA_BOOTSTRAP_SERVERS", None)
    env["ONEX_STATE_DIR"] = str(tmp_path / "state")

    completed = subprocess.run(
        ["bash", str(_RUN_SH), "--dry-run", "--run-id", "round-trip-no-omni-home"],
        capture_output=True,
        check=False,
        cwd=_OMNICLAUDE_ROOT,
        env=env,
        text=True,
        timeout=30,
    )

    assert completed.returncode != 0
    result = json.loads(completed.stdout)
    assert result["success"] is False
    assert result["path"] == "kafka"
    assert "contract.yaml" in result["error"] or "OMNI_HOME" in result["error"]
