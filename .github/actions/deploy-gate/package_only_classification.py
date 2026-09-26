# SPDX-FileCopyrightText: 2026 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Fail-closed Core package-only classification for the deploy gate."""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol

from package_only_content_policy import validate_package_only_content

if TYPE_CHECKING:
    from pr_manifest_snapshot import ModelPullManifestEntry

CORE_REPOSITORY = "OmniNode-ai/omnibase_core"
POLICY_ID = "omnibase-core-package-only"
POLICY_VERSION = "1.0.0"
_SHA_RE = re.compile(r"^[0-9a-f]{40}$")
_ALLOWED_STATUSES = frozenset(
    {"added", "modified", "removed", "renamed", "copied", "changed", "unchanged"}
)
_RUNTIME_RESOLVED_CONTRACT_PATHS = frozenset(
    {
        "contracts/runtime/event_bus_wiring_effect.yaml",
        "src/omnibase_core/contracts/runtime/event_bus_wiring_effect.yaml",
        "src/omnibase_core/contracts/runtime_data/event_bus_wiring_effect.yaml",
    }
)
_STATIC_NONRUNTIME_PATHS = frozenset(
    {
        ".github/workflows/ci.yml",
        ".github/workflows/receipt-gate.yml",
        ".pre-commit-config.yaml",
        ".secrets.baseline",
        ".yaml-validation-allowlist.yaml",
        "architecture-handshakes/validator-requirements.yaml",
    }
)
_STATIC_NONRUNTIME_PREFIXES = (
    "scripts/ci/",
    "scripts/validation/",
    "scripts/validate_no_env_fallbacks.py",
    "examples/demo/handlers/support_assistant/",
)


class ProtocolPackageOnlyManifestEntry(Protocol):
    filename: str
    status: object
    previous_filename: str | None
    blob_sha: str | None
    old_mode: str | None
    new_mode: str | None
    old_object_type: str | None
    new_object_type: str | None
    is_binary: bool
    is_submodule: bool


class ProtocolPackageOnlyDeployBinding(Protocol):
    repository: str
    base_sha: str
    head_sha: str
    diff_base_sha: str
    policy_id: str
    policy_version: str
    manifest_sha256: str
    changed_files: Sequence[ProtocolPackageOnlyManifestEntry]


@dataclass(frozen=True)
class PackageOnlyClassificationResult:
    accepted: bool
    message: str


def _safe_relative_path(path: str) -> bool:
    parts = path.split("/")
    return bool(
        path
        and "\x00" not in path
        and not path.startswith("/")
        and all(part not in {"", ".", ".."} for part in parts)
    )


def _entry_key(entry: ProtocolPackageOnlyManifestEntry) -> tuple[object, ...]:
    return (
        entry.filename,
        _status_value(entry.status),
        entry.previous_filename,
        entry.blob_sha,
        entry.old_mode,
        entry.new_mode,
        entry.old_object_type,
        entry.new_object_type,
        entry.is_binary,
        entry.is_submodule,
    )


def _status_value(status: object) -> str:
    """Read either the shared enum value or a raw GitHub status string."""

    value = getattr(status, "value", status)
    return value if isinstance(value, str) else ""


def _validate_manifest_entry(entry: ProtocolPackageOnlyManifestEntry) -> str | None:
    status = _status_value(entry.status)
    if status not in _ALLOWED_STATUSES:
        return f"unknown GitHub file status {status!r}"
    if not _safe_relative_path(entry.filename):
        return f"unsafe filename {entry.filename!r}"
    if status in {"renamed", "copied"}:
        if entry.previous_filename is None or not _safe_relative_path(
            entry.previous_filename
        ):
            return f"{status} entry {entry.filename!r} lacks a safe previous filename"
    elif entry.previous_filename is not None:
        return f"{status} entry {entry.filename!r} unexpectedly has previous filename"
    if entry.is_binary or entry.is_submodule:
        return f"non-text or submodule entry {entry.filename!r}"
    if entry.blob_sha is None or not _SHA_RE.fullmatch(entry.blob_sha):
        return f"entry {entry.filename!r} lacks a full blob SHA"
    if status == "added":
        if entry.old_mode is not None or entry.old_object_type is not None:
            return f"added entry {entry.filename!r} has unexpected prior metadata"
        if entry.new_mode is None or entry.new_object_type != "blob":
            return f"added entry {entry.filename!r} lacks new blob metadata"
    elif status == "removed":
        if entry.old_mode is None or entry.old_object_type != "blob":
            return f"removed entry {entry.filename!r} lacks prior blob metadata"
        if entry.new_mode is not None or entry.new_object_type is not None:
            return f"removed entry {entry.filename!r} has unexpected head metadata"
    elif (
        entry.old_mode is None
        or entry.new_mode is None
        or entry.old_object_type != "blob"
        or entry.new_object_type != "blob"
    ):
        return f"entry {entry.filename!r} is not a regular blob transition"
    return None


def _is_deployment_artifact(path: str) -> bool:
    if path in _RUNTIME_RESOLVED_CONTRACT_PATHS or path.startswith(
        (
            "contracts/runtime/",
            "src/omnibase_core/contracts/runtime/",
            "src/omnibase_core/contracts/runtime_data/",
        )
    ):
        return True
    parts = path.split("/")
    filename = parts[-1]
    if filename.startswith("Dockerfile") or filename in {
        "docker-compose.yml",
        "docker-compose.yaml",
        "compose.yml",
        "compose.yaml",
    }:
        return True
    if parts[0] in {"docker", "k8s", "kubernetes", "helm", "terraform", "ansible"}:
        return True
    if parts[0] in {"deploy", "deployment", "infra"}:
        return True
    return False


def _is_known_package_path(path: str, content_validated_paths: frozenset[str]) -> bool:
    return (
        path in content_validated_paths
        or path in _STATIC_NONRUNTIME_PATHS
        or path.startswith(_STATIC_NONRUNTIME_PREFIXES)
        or path.startswith("src/omnibase_core/")
        or path.startswith("tests/")
        or path.startswith("docs/")
        or path in {"README.md", "LICENSE", "NOTICE"}
    )


def classify_package_only_change(
    *,
    evidence_ticket: str,
    contract_ticket_id: str,
    proof_class: object,
    binding: ProtocolPackageOnlyDeployBinding,
    repository: str,
    base_sha: str,
    head_sha: str,
    diff_base_sha: str,
    live_manifest: Sequence[ProtocolPackageOnlyManifestEntry],
    manifest_hasher: Callable[[Sequence[ProtocolPackageOnlyManifestEntry]], str],
    raw_manifest: Sequence[ModelPullManifestEntry] | None = None,
    api_get: Callable[[str], object] | None = None,
) -> PackageOnlyClassificationResult:
    """Compare central binding to the immutable live PR manifest."""

    if repository != CORE_REPOSITORY:
        return PackageOnlyClassificationResult(
            False, f"package-only classification is restricted to {CORE_REPOSITORY}"
        )
    if contract_ticket_id != evidence_ticket:
        return PackageOnlyClassificationResult(
            False,
            "package-only binding ticket does not equal authoritative Evidence-Ticket",
        )
    if str(proof_class) != "code-only":
        return PackageOnlyClassificationResult(
            False, "package-only binding requires proof_class: code-only"
        )
    if binding.repository != CORE_REPOSITORY:
        return PackageOnlyClassificationResult(
            False, "package-only binding repository is not the approved Core repository"
        )
    if binding.base_sha != base_sha or binding.head_sha != head_sha:
        return PackageOnlyClassificationResult(
            False, "package-only binding base/head does not match live PR identity"
        )
    if binding.diff_base_sha != diff_base_sha:
        return PackageOnlyClassificationResult(
            False,
            "package-only binding diff base does not match the live PR comparison",
        )
    if binding.policy_id != POLICY_ID or binding.policy_version != POLICY_VERSION:
        return PackageOnlyClassificationResult(
            False, "package-only binding policy identity is unsupported"
        )
    if not live_manifest:
        return PackageOnlyClassificationResult(
            False, "package-only classification requires a non-empty complete manifest"
        )

    seen: set[tuple[object, ...]] = set()
    for entry in live_manifest:
        error = _validate_manifest_entry(entry)
        if error:
            return PackageOnlyClassificationResult(False, error)
        key = _entry_key(entry)
        if key in seen:
            return PackageOnlyClassificationResult(
                False, f"duplicate manifest entry for {entry.filename!r}"
            )
        seen.add(key)

    try:
        live_digest = manifest_hasher(live_manifest)
        bound_digest = manifest_hasher(binding.changed_files)
    except (TypeError, ValueError) as exc:
        return PackageOnlyClassificationResult(
            False, f"package-only manifest canonicalization failed: {exc}"
        )

    if (
        live_digest != binding.manifest_sha256
        or bound_digest != binding.manifest_sha256
    ):
        return PackageOnlyClassificationResult(
            False, "package-only binding manifest digest does not match live manifest"
        )
    if Counter(_entry_key(entry) for entry in binding.changed_files) != Counter(
        _entry_key(entry) for entry in live_manifest
    ):
        return PackageOnlyClassificationResult(
            False,
            "package-only binding manifest entries do not exactly match live manifest",
        )

    content_validated_paths = frozenset()
    content_sensitive_paths = {
        ".mcp.json",
        "pyproject.toml",
        "uv.lock",
        "examples/contracts/effect/kafka_produce.yaml",
        ".github/workflows/auto-merge.yml",
        *(_RUNTIME_RESOLVED_CONTRACT_PATHS),
    }
    if any(entry.filename in content_sensitive_paths for entry in live_manifest):
        if raw_manifest is None or api_get is None:
            return PackageOnlyClassificationResult(
                False,
                "package-only content-sensitive paths require immutable raw manifest data",
            )
        raw_keys = tuple(
            (entry.filename, entry.status, entry.blob_sha) for entry in raw_manifest
        )
        typed_keys = tuple(
            (entry.filename, _status_value(entry.status), entry.blob_sha)
            for entry in live_manifest
        )
        if raw_keys != typed_keys:
            return PackageOnlyClassificationResult(
                False, "raw and typed package-only manifests do not exactly match"
            )
        content_result = validate_package_only_content(
            entries=raw_manifest, repository=repository, api_get=api_get
        )
        if content_result.error is not None:
            return PackageOnlyClassificationResult(False, content_result.error)
        content_validated_paths = content_result.accepted_paths

    for entry in live_manifest:
        if (
            _is_deployment_artifact(entry.filename)
            and entry.filename not in content_validated_paths
        ):
            return PackageOnlyClassificationResult(
                False, f"deployment artifact {entry.filename!r} remains deploy-required"
            )
        if not _is_known_package_path(entry.filename, content_validated_paths):
            return PackageOnlyClassificationResult(
                False,
                f"unknown package-only path {entry.filename!r} is deploy-required",
            )

    return PackageOnlyClassificationResult(
        True,
        "package-only classification accepted; this proves code-only scope, not deployment or activation.",
    )
