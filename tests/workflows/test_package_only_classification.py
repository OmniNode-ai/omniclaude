# SPDX-FileCopyrightText: 2026 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Focused tests for the fail-closed Core package-only deploy classifier."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

import pytest
from omnibase_core.models.ticket import (
    ModelPackageOnlyDeployBinding,
    ModelPackageOnlyManifestEntry,
    compute_package_only_manifest_sha256,
)

pytestmark = pytest.mark.unit

_HANDLER = (
    Path(__file__).resolve().parents[2]
    / ".github"
    / "actions"
    / "deploy-gate"
    / "package_only_classification.py"
)


def _load_handler() -> ModuleType:
    sys.path.insert(0, str(_HANDLER.parent))
    spec = importlib.util.spec_from_file_location(
        "package_only_classification", _HANDLER
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


handler = _load_handler()


def _entry(filename: str, **overrides: object) -> ModelPackageOnlyManifestEntry:
    values: dict[str, object] = {
        "filename": filename,
        "status": "modified",
        "previous_filename": None,
        "blob_sha": "a" * 40,
        "old_mode": "100644",
        "new_mode": "100644",
        "old_object_type": "blob",
        "new_object_type": "blob",
        "is_binary": False,
        "is_submodule": False,
    }
    values.update(overrides)
    return ModelPackageOnlyManifestEntry.model_validate(values)


def _binding(
    entries: tuple[ModelPackageOnlyManifestEntry, ...],
) -> ModelPackageOnlyDeployBinding:
    return ModelPackageOnlyDeployBinding(
        repository=handler.CORE_REPOSITORY,
        base_sha="b" * 40,
        head_sha="c" * 40,
        diff_base_sha="a" * 40,
        policy_id=handler.POLICY_ID,
        policy_version=handler.POLICY_VERSION,
        manifest_sha256=compute_package_only_manifest_sha256(entries),
        changed_files=entries,
    )


def _classify(
    entries: tuple[ModelPackageOnlyManifestEntry, ...], **overrides: object
) -> object:
    values = {
        "evidence_ticket": "OMN-18156",
        "contract_ticket_id": "OMN-18156",
        "proof_class": "code-only",
        "binding": _binding(entries),
        "repository": handler.CORE_REPOSITORY,
        "base_sha": "b" * 40,
        "head_sha": "c" * 40,
        "diff_base_sha": "a" * 40,
        "live_manifest": entries,
        "manifest_hasher": compute_package_only_manifest_sha256,
    }
    values.update(overrides)
    return handler.classify_package_only_change(**values)


def test_accepts_exact_core_library_manifest() -> None:
    result = _classify(
        (
            _entry("src/omnibase_core/runtime/dispatch_state.py"),
            _entry("tests/unit/runtime/test_dispatch_state.py"),
        )
    )

    assert result.accepted
    assert "not deployment or activation" in result.message


def test_accepts_the_same_typed_manifest_in_canonicalized_order() -> None:
    entries = (
        _entry("src/omnibase_core/runtime/dispatch_state.py"),
        _entry("tests/unit/runtime/test_dispatch_state.py"),
    )

    result = _classify(entries, binding=_binding(tuple(reversed(entries))))

    assert result.accepted


@pytest.mark.parametrize(
    "entry",
    [
        _entry("docker/Dockerfile.runtime"),
        _entry("k8s/deployment.yaml"),
        _entry("contracts/runtime/event_bus_wiring_effect.yaml"),
        _entry("contracts/runtime/unreviewed_effect.yaml"),
        _entry("src/omnibase_core/contracts/runtime/event_bus_wiring_effect.yaml"),
        _entry("src/omnibase_core/contracts/runtime_data/event_bus_wiring_effect.yaml"),
        _entry(".mcp.json"),
    ],
)
def test_deployment_or_unknown_paths_are_not_package_only(
    entry: ModelPackageOnlyManifestEntry,
) -> None:
    result = _classify((entry,))

    assert not result.accepted


def test_content_checked_dev_tool_path_requires_the_immutable_raw_manifest() -> None:
    entry = _entry(".mcp.json")

    result = _classify((entry,))

    assert not result.accepted
    assert "immutable raw manifest" in result.message


def test_invalid_binding_never_falls_back_to_generic_ticket_evidence() -> None:
    result = _classify(
        (_entry("src/omnibase_core/runtime/dispatch_state.py"),),
        contract_ticket_id="OMN-17523",
    )

    assert not result.accepted
    assert "Evidence-Ticket" in result.message


def test_head_manifest_and_rename_invariants_fail_closed() -> None:
    entry = _entry("src/omnibase_core/runtime/dispatch_state.py")
    stale = _classify((entry,), head_sha="d" * 40)
    stale_diff_base = _classify((entry,), diff_base_sha="e" * 40)
    mismatched = _classify(
        (entry,),
        binding=_binding((_entry("src/omnibase_core/runtime/other.py"),)),
    )
    missing_rename = _entry(
        "src/omnibase_core/runtime/new.py",
        status="renamed",
        previous_filename="src/omnibase_core/runtime/old.py",
    )
    duplicate = _classify((entry,), live_manifest=(entry, entry))

    assert not stale.accepted
    assert not stale_diff_base.accepted
    assert not mismatched.accepted
    assert _classify((missing_rename,)).accepted
    assert not duplicate.accepted


def test_non_core_repository_never_receives_core_exemption() -> None:
    result = _classify(
        (_entry("src/omnibase_core/runtime/dispatch_state.py"),),
        repository="OmniNode-ai/omnimarket",
    )

    assert not result.accepted
