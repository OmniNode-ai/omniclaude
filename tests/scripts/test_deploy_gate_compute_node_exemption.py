# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""Regression tests for the pure-COMPUTE node deploy-gate exemption (OMN-15065).

Ticket: OMN-15065. Live instance: omnimarket#1881 (OMN-14977) and #1882
(OMN-14978) — both pure def-B COMPUTE nodes (zero bus topics, no I/O, not a
running service) blocked by deploy-gate with no honest way to satisfy it: the
gate demanded a dod_evidence check_value containing 'docker exec', 'rpk topic
produce', or 'deploy', which such a node can only satisfy by fabricating
evidence (nothing is ever deployed for it to probe).

THE PROOF STANDARD THIS FILE MUST MEET
---------------------------------------
A test that only proves "a pure-compute node with no event_bus is exempt"
would be vacuous if the exemption were actually a blanket "skip anything
under nodes/" bypass — that would silently defeat the gate for genuinely
deployable nodes too. Every exemption-pass test in this file is therefore
paired with a same-shape node that is NOT exempt (bus-wired, wrong
archetype, or unreadable contract) and must assert the gate still fires for
it. The event_bus-wired compute node case (mirroring the real
node_advanced_features_resolve_compute in omnimarket) is the load-bearing
regression: it proves the exemption is contract-derived, not
node_type-alone.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

# The validator lives in the composite action directory.
ACTION_DIR = Path(__file__).parent.parent.parent / ".github" / "actions" / "deploy-gate"
sys.path.insert(0, str(ACTION_DIR))

from validate_pr_deploy_required import (  # noqa: E402
    find_runtime_paths,
    validate_pr_deploy_gate,
)

pytestmark = pytest.mark.unit


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


_PURE_COMPUTE_CONTRACT = """\
name: "node_worker_memory_admission_compute"
node_type: "COMPUTE_GENERIC"
descriptor:
  node_archetype: compute
  purity: pure
metadata:
  transport_type: inmemory
"""

_BUS_WIRED_COMPUTE_CONTRACT = """\
name: "node_advanced_features_resolve_compute"
node_type: compute
descriptor:
  node_archetype: compute
event_bus:
  subscribe_topics:
    - onex.cmd.omnimarket.advanced-features-resolve-requested.v1
  publish_topics:
    - onex.evt.omnimarket.advanced-features-resolve-completed.v1
"""

_EFFECT_CONTRACT = """\
name: "node_ab_inference_effect"
node_type: effect
descriptor:
  node_archetype: effect
event_bus:
  subscribe_topics:
    - onex.cmd.omnimarket.ab-inference-requested.v1
  publish_topics:
    - onex.evt.omnimarket.ab-inference-completed.v1
metadata:
  transport_type: kafka
"""


# ---------------------------------------------------------------------------
# find_runtime_paths — pure-COMPUTE node is excluded from runtime hits
# ---------------------------------------------------------------------------


class TestPureComputeNodeExempt:
    def test_contract_yaml_of_pure_compute_node_not_matched(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        rel = "src/omnimarket/nodes/node_worker_memory_admission_compute/contract.yaml"
        _write(tmp_path / rel, _PURE_COMPUTE_CONTRACT)
        monkeypatch.chdir(tmp_path)
        assert find_runtime_paths([rel]) == []

    def test_handler_and_model_files_of_pure_compute_node_not_matched(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        node_dir = "src/omnimarket/nodes/node_worker_memory_admission_compute"
        contract_rel = f"{node_dir}/contract.yaml"
        handler_rel = f"{node_dir}/handlers/handler_worker_memory_admission_compute.py"
        model_rel = f"{node_dir}/models/model_worker_memory_admission.py"
        _write(tmp_path / contract_rel, _PURE_COMPUTE_CONTRACT)
        _write(tmp_path / handler_rel, "class HandlerWorkerMemoryAdmission: ...\n")
        _write(tmp_path / model_rel, "class ModelMemoryAdmissionRequest: ...\n")
        monkeypatch.chdir(tmp_path)
        files = [contract_rel, handler_rel, model_rel]
        assert find_runtime_paths(files) == []

    def test_full_pipeline_pure_compute_node_passes_without_any_dod_evidence(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """End-to-end: validate_pr_deploy_gate PASSES with zero dod_evidence
        cited — the honest path for a node that deploys nothing."""
        rel = "src/omnimarket/nodes/node_worker_memory_admission_compute/contract.yaml"
        _write(tmp_path / rel, _PURE_COMPUTE_CONTRACT)
        monkeypatch.chdir(tmp_path)
        # contracts_dir has NO OMN-14977.yaml at all — proves no evidence is
        # required, not merely that some evidence elsewhere satisfies it.
        result = validate_pr_deploy_gate(
            changed_files=[rel],
            pr_body="Closes OMN-14977",
            contracts_dir=tmp_path / "nonexistent-contracts-dir",
        )
        assert result.passed
        assert result.skipped


# ---------------------------------------------------------------------------
# Load-bearing regression: a compute-archetype node that IS bus-wired stays
# gated. Proves the exemption is contract-derived, not a node_type=compute
# blanket bypass.
# ---------------------------------------------------------------------------


class TestBusWiredComputeNodeStillGated:
    def test_event_bus_wired_compute_node_still_matched(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        rel = (
            "src/omnimarket/nodes/node_advanced_features_resolve_compute/contract.yaml"
        )
        _write(tmp_path / rel, _BUS_WIRED_COMPUTE_CONTRACT)
        monkeypatch.chdir(tmp_path)
        assert find_runtime_paths([rel]) == [rel]

    def test_event_bus_wired_compute_node_fails_without_deploy_evidence(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        rel = (
            "src/omnimarket/nodes/node_advanced_features_resolve_compute/contract.yaml"
        )
        _write(tmp_path / rel, _BUS_WIRED_COMPUTE_CONTRACT)
        monkeypatch.chdir(tmp_path)
        result = validate_pr_deploy_gate(
            changed_files=[rel],
            pr_body="Closes OMN-9999",
            contracts_dir=tmp_path / "nonexistent-contracts-dir",
        )
        assert not result.passed
        assert "DEPLOY GATE FAILED" in result.message


# ---------------------------------------------------------------------------
# EFFECT nodes and other non-compute archetypes are never exempt.
# ---------------------------------------------------------------------------


class TestNonComputeArchetypeStillGated:
    def test_effect_node_still_matched(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        rel = "src/omnimarket/nodes/node_ab_inference_effect/contract.yaml"
        _write(tmp_path / rel, _EFFECT_CONTRACT)
        monkeypatch.chdir(tmp_path)
        assert find_runtime_paths([rel]) == [rel]


# ---------------------------------------------------------------------------
# Fail-closed cases: anything short of a clean, parseable, non-bus compute
# contract keeps the node gated.
# ---------------------------------------------------------------------------


class TestFailClosed:
    def test_missing_contract_file_still_gated(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """contract.yaml deleted/renamed in this PR diff — no contract to
        prove non-deployability from, so the handler stays gated."""
        node_dir = "src/omnimarket/nodes/node_deleted_contract_compute"
        handler_rel = f"{node_dir}/handlers/handler_deleted_contract.py"
        _write(tmp_path / handler_rel, "class HandlerDeletedContract: ...\n")
        monkeypatch.chdir(tmp_path)
        assert find_runtime_paths([handler_rel]) == [handler_rel]

    def test_unparsable_contract_yaml_still_gated(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        rel = "src/omnimarket/nodes/node_broken_yaml_compute/contract.yaml"
        _write(tmp_path / rel, "node_type: [unterminated\n")
        monkeypatch.chdir(tmp_path)
        assert find_runtime_paths([rel]) == [rel]

    def test_contract_missing_archetype_fields_still_gated(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        rel = "src/omnimarket/nodes/node_no_archetype_field/contract.yaml"
        _write(tmp_path / rel, "name: node_no_archetype_field\n")
        monkeypatch.chdir(tmp_path)
        assert find_runtime_paths([rel]) == [rel]

    def test_compute_node_with_kafka_transport_metadata_still_gated(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """node_type=compute with no event_bus section but a declared kafka
        transport in metadata (e.g. dispatched externally some other way)
        must NOT be exempted purely on the absence of event_bus."""
        rel = "src/omnimarket/nodes/node_compute_kafka_transport/contract.yaml"
        _write(
            tmp_path / rel,
            "node_type: compute\ndescriptor:\n  node_archetype: compute\n"
            "metadata:\n  transport_type: kafka\n",
        )
        monkeypatch.chdir(tmp_path)
        assert find_runtime_paths([rel]) == [rel]


if __name__ == "__main__":  # pragma: no cover
    sys.exit(pytest.main([__file__, "-v"]))
