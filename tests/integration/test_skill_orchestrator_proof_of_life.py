# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Phase 1 Task 5 (OMN-10209): proof-of-life end-to-end dispatch round trip.

Demonstrates one complete skill-backing-node lifecycle:
  foreground subprocess → omnimarket node CLI → ModelDispatchRecord persisted →
  typed result returned with proposed_agent_spawn_args.

The test invokes ``node_dispatch_worker`` (the canonical Phase 1 skill-backing
node, persistence wired in OMN-10208) via ``python -m`` subprocess, sets
``ONEX_STATE_DIR`` so the lazy-import persistence path activates, and asserts
the dispatch record YAML is written and validates against
``ModelDispatchRecord``.

Marked ``integration``: skipped by default in CI (``-m "not integration"``).
Live evidence captured at
``omni_home/docs/tracking/2026-04-27-skills-to-market-proof-of-life-evidence.md``.

Live infra precondition: omninode-runtime + Redpanda on the .201 GPU host
(see ~/.omnibase/.env). The node_dispatch_worker handler does not emit Kafka
itself, but the round-trip verifies the full skill-backing-node
compile-then-persist contract.
"""

from __future__ import annotations

import json
import os
import shutil
import socket
import subprocess
from pathlib import Path

import pytest
import yaml

_OMNI_HOME = os.environ.get("OMNI_HOME", "")
_OMNIMARKET_SRC = Path(_OMNI_HOME) / "omnimarket" / "src" if _OMNI_HOME else None
_OMNICLAUDE_SRC = Path(_OMNI_HOME) / "omniclaude" / "src" if _OMNI_HOME else None
_REDPANDA_HOST = "192.168.86.201"  # onex-allow-internal-ip
_REDPANDA_PORT = 19092


def _redpanda_reachable() -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(2.0)
        try:
            s.connect((_REDPANDA_HOST, _REDPANDA_PORT))
            return True
        except OSError:
            return False


@pytest.mark.integration
def test_node_dispatch_worker_proof_of_life(tmp_path: Path) -> None:
    """Round trip: node CLI → dispatch record YAML → ModelDispatchRecord validate.

    Five assertions, one per acceptance criterion in the Phase 1 plan:
      A1. node CLI exits 0
      A2. stdout is parseable JSON with non-empty proposed_agent_spawn_args
      A3. dispatch record file exists at $ONEX_STATE_DIR/dispatches/<name>.yaml
      A4. record content validates against ModelDispatchRecord
      A5. parent_session_id matches the foreground-supplied correlation_id
    """
    if not _OMNI_HOME:
        pytest.skip("OMNI_HOME unset — proof-of-life requires canonical clones")
    if _OMNIMARKET_SRC is None or not _OMNIMARKET_SRC.is_dir():
        pytest.skip("omnimarket source not found at $OMNI_HOME/omnimarket/src")
    if _OMNICLAUDE_SRC is None or not _OMNICLAUDE_SRC.is_dir():
        pytest.skip("omniclaude source not found at $OMNI_HOME/omniclaude/src")
    if not _redpanda_reachable():
        pytest.skip(
            f"Redpanda unreachable at {_REDPANDA_HOST}:{_REDPANDA_PORT} "
            "(live infra precondition)"
        )
    if shutil.which("uv") is None:
        pytest.skip("uv not found on PATH (required to invoke the node CLI)")

    correlation_id = "proof-of-life-omn-10209-pytest"
    env = os.environ.copy()
    env["ONEX_STATE_DIR"] = str(tmp_path)
    env["ONEX_PARENT_SESSION_ID"] = correlation_id
    env["PYTHONPATH"] = os.pathsep.join([str(_OMNIMARKET_SRC), str(_OMNICLAUDE_SRC)])
    env.pop("KAFKA_BOOTSTRAP_SERVERS", None)

    result = subprocess.run(
        [
            "uv",
            "run",
            "python",
            "-m",
            "omnimarket.nodes.node_dispatch_worker",
            "--name",
            "pytest-proof-of-life-worker",
            "--team",
            "Omninode",
            "--role",
            "fixer",
            "--scope",
            "Phase 1 proof-of-life pytest",
            "--targets",
            "OMN-10209",
            "omnimarket#436",
            "--tasks-dir",
            str(tmp_path / "tasks"),
        ],
        capture_output=True,
        text=True,
        timeout=120,
        cwd=str(Path(_OMNI_HOME) / "omniclaude"),
        env=env,
        check=False,
    )

    # A1
    assert result.returncode == 0, (
        f"node CLI failed:\nSTDOUT: {result.stdout}\nSTDERR: {result.stderr}"
    )

    # A2
    payload = json.loads(result.stdout)
    spawn_args = payload.get("proposed_agent_spawn_args", {})
    assert spawn_args.get("name") == "pytest-proof-of-life-worker"
    assert spawn_args.get("team_name") == "Omninode"
    assert spawn_args.get("subagent_type") == "general-purpose"

    # A3
    record_path = tmp_path / "dispatches" / "pytest-proof-of-life-worker.yaml"
    assert record_path.is_file(), f"dispatch record not at {record_path}"

    # A4
    from omniclaude.hooks.model_dispatch_record import ModelDispatchRecord

    record = ModelDispatchRecord.model_validate(yaml.safe_load(record_path.read_text()))

    # A5
    assert record.parent_session_id == correlation_id
    assert record.dispatcher == "node_dispatch_worker"
    assert record.ticket == "OMN-10209"
    assert len(record.prompt_digest) >= 8
