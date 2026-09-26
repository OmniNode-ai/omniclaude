# SPDX-FileCopyrightText: 2026 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Focused tests for the typed package-only deploy-gate adapter."""

from __future__ import annotations

import base64
import importlib.util
import sys
from pathlib import Path
from types import ModuleType

import pytest
from omnibase_core.models.ticket import (
    ModelPackageOnlyDeployBinding,
    ModelPackageOnlyManifestEntry,
    ModelTicketContract,
    compute_package_only_manifest_sha256,
)

pytestmark = pytest.mark.unit

_ACTION_DIR = (
    Path(__file__).resolve().parents[2] / ".github" / "actions" / "deploy-gate"
)
_MODULE = _ACTION_DIR / "package_only_deploy_gate.py"
_REPOSITORY = "OmniNode-ai/omnibase_core"
_BASE = "a" * 40
_HEAD = "b" * 40
_DIFF_BASE = "c" * 40
_OLD_BLOB = "d" * 40
_NEW_BLOB = "e" * 40


def _load_module() -> ModuleType:
    sys.path.insert(0, str(_ACTION_DIR))
    spec = importlib.util.spec_from_file_location("package_only_deploy_gate", _MODULE)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


adapter = _load_module()


def _blob(content: bytes) -> dict[str, str]:
    return {
        "encoding": "base64",
        "content": base64.b64encode(content).decode("ascii"),
    }


def _api_get(endpoint: str) -> object:
    pr_endpoint = f"repos/{_REPOSITORY}/pulls/123"
    if endpoint == pr_endpoint:
        return {
            "base": {"sha": _BASE, "repo": {"full_name": _REPOSITORY}},
            "head": {"sha": _HEAD},
            "changed_files": 1,
        }
    if endpoint == f"{pr_endpoint}/files?per_page=100&page=1":
        return [
            {
                "filename": "src/omnibase_core/runtime/dispatch_state.py",
                "status": "modified",
                "sha": _NEW_BLOB,
            }
        ]
    if endpoint == f"repos/{_REPOSITORY}/compare/{_BASE}...{_HEAD}":
        return {"merge_base_commit": {"sha": _DIFF_BASE}}
    if endpoint == f"repos/{_REPOSITORY}/git/trees/{_DIFF_BASE}?recursive=1":
        return {
            "truncated": False,
            "tree": [
                {
                    "path": "src/omnibase_core/runtime/dispatch_state.py",
                    "mode": "100644",
                    "type": "blob",
                    "sha": _OLD_BLOB,
                }
            ],
        }
    if endpoint == f"repos/{_REPOSITORY}/git/trees/{_HEAD}?recursive=1":
        return {
            "truncated": False,
            "tree": [
                {
                    "path": "src/omnibase_core/runtime/dispatch_state.py",
                    "mode": "100644",
                    "type": "blob",
                    "sha": _NEW_BLOB,
                }
            ],
        }
    if endpoint == f"repos/{_REPOSITORY}/git/blobs/{_OLD_BLOB}":
        return _blob(b"old\n")
    if endpoint == f"repos/{_REPOSITORY}/git/blobs/{_NEW_BLOB}":
        return _blob(b"new\n")
    raise AssertionError(endpoint)


def _entry() -> ModelPackageOnlyManifestEntry:
    return ModelPackageOnlyManifestEntry(
        filename="src/omnibase_core/runtime/dispatch_state.py",
        status="modified",
        previous_filename=None,
        blob_sha=_NEW_BLOB,
        old_mode="100644",
        new_mode="100644",
        old_object_type="blob",
        new_object_type="blob",
        is_binary=False,
        is_submodule=False,
    )


def _contract(ticket_id: str = "OMN-18156") -> ModelTicketContract:
    entries = (_entry(),)
    binding = ModelPackageOnlyDeployBinding(
        repository=_REPOSITORY,
        base_sha=_BASE,
        head_sha=_HEAD,
        diff_base_sha=_DIFF_BASE,
        policy_id="omnibase-core-package-only",
        policy_version="1.0.0",
        manifest_sha256=compute_package_only_manifest_sha256(entries),
        changed_files=entries,
    )
    return ModelTicketContract(
        ticket_id=ticket_id,
        title="Package-only classification",
        proof_class="code-only",
        package_only_deploy_binding=binding,
    )


def test_adapter_uses_typed_contract_and_immutable_git_objects() -> None:
    result = adapter.validate_core_package_only_binding(
        evidence_ticket="OMN-18156",
        contract=_contract(),
        repository=_REPOSITORY,
        pr_number=123,
        event_head_sha=_HEAD,
        api_get=_api_get,
        manifest_entry_model=ModelPackageOnlyManifestEntry,
        manifest_hasher=compute_package_only_manifest_sha256,
    )

    assert result.accepted


def test_adapter_rejects_a_binding_for_a_different_authoritative_ticket() -> None:
    result = adapter.validate_core_package_only_binding(
        evidence_ticket="OMN-18156",
        contract=_contract(ticket_id="OMN-17523"),
        repository=_REPOSITORY,
        pr_number=123,
        event_head_sha=_HEAD,
        api_get=_api_get,
        manifest_entry_model=ModelPackageOnlyManifestEntry,
        manifest_hasher=compute_package_only_manifest_sha256,
    )

    assert not result.accepted
    assert "Evidence-Ticket" in result.message


def test_adapter_fails_closed_when_the_git_object_manifest_is_incomplete() -> None:
    def incomplete_api_get(endpoint: str) -> object:
        if endpoint == f"repos/{_REPOSITORY}/git/trees/{_HEAD}?recursive=1":
            return {"truncated": False, "tree": []}
        return _api_get(endpoint)

    result = adapter.validate_core_package_only_binding(
        evidence_ticket="OMN-18156",
        contract=_contract(),
        repository=_REPOSITORY,
        pr_number=123,
        event_head_sha=_HEAD,
        api_get=incomplete_api_get,
        manifest_entry_model=ModelPackageOnlyManifestEntry,
        manifest_hasher=compute_package_only_manifest_sha256,
    )

    assert not result.accepted
    assert "live manifest resolution failed" in result.message


def test_adapter_binds_the_exact_project_root_dev_tool_change() -> None:
    old_blob, new_blob = "1" * 40, "2" * 40
    mcp_entry = ModelPackageOnlyManifestEntry(
        filename=".mcp.json",
        status="modified",
        previous_filename=None,
        blob_sha=new_blob,
        old_mode="100644",
        new_mode="100644",
        old_object_type="blob",
        new_object_type="blob",
        is_binary=False,
        is_submodule=False,
    )
    binding = ModelPackageOnlyDeployBinding(
        repository=_REPOSITORY,
        base_sha=_BASE,
        head_sha=_HEAD,
        diff_base_sha=_DIFF_BASE,
        policy_id="omnibase-core-package-only",
        policy_version="1.0.0",
        manifest_sha256=compute_package_only_manifest_sha256((mcp_entry,)),
        changed_files=(mcp_entry,),
    )
    contract = ModelTicketContract(
        ticket_id="OMN-18156",
        title="Package-only classification",
        proof_class="code-only",
        package_only_deploy_binding=binding,
    )
    old_mcp = '{"mcpServers":{"repowise":{"command":"repowise","args":["mcp","/tmp/core","--transport","stdio"]}}}'
    new_mcp = '{"mcpServers":{"repowise":{"command":"repowise","args":["mcp",".","--transport","stdio"]}}}'

    def api_get(endpoint: str) -> object:
        pull = f"repos/{_REPOSITORY}/pulls/123"
        if endpoint == pull:
            return {
                "base": {"sha": _BASE, "repo": {"full_name": _REPOSITORY}},
                "head": {"sha": _HEAD},
                "changed_files": 1,
            }
        if endpoint == f"{pull}/files?per_page=100&page=1":
            return [{"filename": ".mcp.json", "status": "modified", "sha": new_blob}]
        if endpoint == f"repos/{_REPOSITORY}/compare/{_BASE}...{_HEAD}":
            return {"merge_base_commit": {"sha": _DIFF_BASE}}
        if endpoint == f"repos/{_REPOSITORY}/git/trees/{_DIFF_BASE}?recursive=1":
            return {
                "truncated": False,
                "tree": [
                    {
                        "path": ".mcp.json",
                        "mode": "100644",
                        "type": "blob",
                        "sha": old_blob,
                    }
                ],
            }
        if endpoint == f"repos/{_REPOSITORY}/git/trees/{_HEAD}?recursive=1":
            return {
                "truncated": False,
                "tree": [
                    {
                        "path": ".mcp.json",
                        "mode": "100644",
                        "type": "blob",
                        "sha": new_blob,
                    }
                ],
            }
        if endpoint == f"repos/{_REPOSITORY}/git/blobs/{old_blob}":
            return _blob(old_mcp.encode())
        if endpoint == f"repos/{_REPOSITORY}/git/blobs/{new_blob}":
            return _blob(new_mcp.encode())
        raise AssertionError(endpoint)

    result = adapter.validate_core_package_only_binding(
        evidence_ticket="OMN-18156",
        contract=contract,
        repository=_REPOSITORY,
        pr_number=123,
        event_head_sha=_HEAD,
        api_get=api_get,
        manifest_entry_model=ModelPackageOnlyManifestEntry,
        manifest_hasher=compute_package_only_manifest_sha256,
    )

    assert result.accepted


def test_adapter_enforces_atomic_runtime_comment_group_semantics() -> None:
    paths = tuple(
        sorted(
            {
                "contracts/runtime/event_bus_wiring_effect.yaml",
                "src/omnibase_core/contracts/runtime/event_bus_wiring_effect.yaml",
                "src/omnibase_core/contracts/runtime_data/event_bus_wiring_effect.yaml",
            }
        )
    )
    old_text = "kind: effect\n# TODO: Implement subscription handler registration in the runtime:\n"
    new_text = old_text.replace(
        "# TODO: Implement subscription handler registration in the runtime:",
        '# TODO: Implement subscription handler registration in the runtime:  # onex-allow-todo-marker OMN-18148 reason="ticketed Core registry and contract-validation work"',
    )
    old_shas = tuple(f"{index + 1:x}" * 40 for index in range(3))
    new_shas = tuple(f"{index + 4:x}" * 40 for index in range(3))
    entries = tuple(
        ModelPackageOnlyManifestEntry(
            filename=file_path,
            status="modified",
            previous_filename=None,
            blob_sha=new_sha,
            old_mode="100644",
            new_mode="100644",
            old_object_type="blob",
            new_object_type="blob",
            is_binary=False,
            is_submodule=False,
        )
        for file_path, new_sha in zip(paths, new_shas, strict=True)
    )
    binding = ModelPackageOnlyDeployBinding(
        repository=_REPOSITORY,
        base_sha=_BASE,
        head_sha=_HEAD,
        diff_base_sha=_DIFF_BASE,
        policy_id="omnibase-core-package-only",
        policy_version="1.0.0",
        manifest_sha256=compute_package_only_manifest_sha256(entries),
        changed_files=entries,
    )
    contract = ModelTicketContract(
        ticket_id="OMN-18156",
        title="Package-only classification",
        proof_class="code-only",
        package_only_deploy_binding=binding,
    )
    old_tree = [
        {"path": file_path, "mode": "100644", "type": "blob", "sha": old_sha}
        for file_path, old_sha in zip(paths, old_shas, strict=True)
    ]
    new_tree = [
        {"path": file_path, "mode": "100644", "type": "blob", "sha": new_sha}
        for file_path, new_sha in zip(paths, new_shas, strict=True)
    ]
    blobs = {**dict.fromkeys(old_shas, old_text), **dict.fromkeys(new_shas, new_text)}

    def api_get(endpoint: str) -> object:
        pull = f"repos/{_REPOSITORY}/pulls/123"
        if endpoint == pull:
            return {
                "base": {"sha": _BASE, "repo": {"full_name": _REPOSITORY}},
                "head": {"sha": _HEAD},
                "changed_files": 3,
            }
        if endpoint == f"{pull}/files?per_page=100&page=1":
            return [
                {"filename": path, "status": "modified", "sha": sha}
                for path, sha in zip(paths, new_shas, strict=True)
            ]
        if endpoint == f"repos/{_REPOSITORY}/compare/{_BASE}...{_HEAD}":
            return {"merge_base_commit": {"sha": _DIFF_BASE}}
        if endpoint == f"repos/{_REPOSITORY}/git/trees/{_DIFF_BASE}?recursive=1":
            return {"truncated": False, "tree": old_tree}
        if endpoint == f"repos/{_REPOSITORY}/git/trees/{_HEAD}?recursive=1":
            return {"truncated": False, "tree": new_tree}
        if endpoint.startswith(f"repos/{_REPOSITORY}/git/blobs/"):
            return _blob(blobs[endpoint.rsplit("/", maxsplit=1)[-1]].encode())
        raise AssertionError(endpoint)

    result = adapter.validate_core_package_only_binding(
        evidence_ticket="OMN-18156",
        contract=contract,
        repository=_REPOSITORY,
        pr_number=123,
        event_head_sha=_HEAD,
        api_get=api_get,
        manifest_entry_model=ModelPackageOnlyManifestEntry,
        manifest_hasher=compute_package_only_manifest_sha256,
    )

    assert result.accepted

    partial_entries = entries[:2]
    partial_binding = ModelPackageOnlyDeployBinding(
        repository=_REPOSITORY,
        base_sha=_BASE,
        head_sha=_HEAD,
        diff_base_sha=_DIFF_BASE,
        policy_id="omnibase-core-package-only",
        policy_version="1.0.0",
        manifest_sha256=compute_package_only_manifest_sha256(partial_entries),
        changed_files=partial_entries,
    )
    partial_contract = ModelTicketContract(
        ticket_id="OMN-18156",
        title="Package-only classification",
        proof_class="code-only",
        package_only_deploy_binding=partial_binding,
    )

    def partial_api_get(endpoint: str) -> object:
        pull = f"repos/{_REPOSITORY}/pulls/123"
        if endpoint == pull:
            return {
                "base": {"sha": _BASE, "repo": {"full_name": _REPOSITORY}},
                "head": {"sha": _HEAD},
                "changed_files": 2,
            }
        if endpoint == f"{pull}/files?per_page=100&page=1":
            return [
                {"filename": path, "status": "modified", "sha": sha}
                for path, sha in zip(paths[:2], new_shas[:2], strict=True)
            ]
        if endpoint == f"repos/{_REPOSITORY}/compare/{_BASE}...{_HEAD}":
            return {"merge_base_commit": {"sha": _DIFF_BASE}}
        if endpoint == f"repos/{_REPOSITORY}/git/trees/{_DIFF_BASE}?recursive=1":
            return {"truncated": False, "tree": old_tree[:2]}
        if endpoint == f"repos/{_REPOSITORY}/git/trees/{_HEAD}?recursive=1":
            return {"truncated": False, "tree": new_tree[:2]}
        if endpoint.startswith(f"repos/{_REPOSITORY}/git/blobs/"):
            return _blob(blobs[endpoint.rsplit("/", maxsplit=1)[-1]].encode())
        raise AssertionError(endpoint)

    partial_result = adapter.validate_core_package_only_binding(
        evidence_ticket="OMN-18156",
        contract=partial_contract,
        repository=_REPOSITORY,
        pr_number=123,
        event_head_sha=_HEAD,
        api_get=partial_api_get,
        manifest_entry_model=ModelPackageOnlyManifestEntry,
        manifest_hasher=compute_package_only_manifest_sha256,
    )

    assert not partial_result.accepted
    assert "complete group" in partial_result.message
