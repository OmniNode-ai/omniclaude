# SPDX-FileCopyrightText: 2026 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Typed adapter from an immutable PR manifest to the package-only classifier."""

from __future__ import annotations

from collections.abc import Callable
from typing import Protocol

from package_only_classification import (
    PackageOnlyClassificationResult,
    ProtocolPackageOnlyDeployBinding,
    ProtocolPackageOnlyManifestEntry,
    classify_package_only_change,
)
from pr_manifest_snapshot import (
    PrManifestResolutionError,
    enrich_pull_manifest,
    resolve_pull_manifest,
)


class ProtocolTypedTicketContract(Protocol):
    """The shared Core ticket contract surface consumed by this adapter."""

    ticket_id: str
    proof_class: object
    package_only_deploy_binding: ProtocolPackageOnlyDeployBinding | None


class ProtocolManifestEntryModel(Protocol):
    """Factory supplied by the trusted shared Core model package."""

    @classmethod
    def model_validate(
        cls, value: dict[str, object]
    ) -> ProtocolPackageOnlyManifestEntry: ...


def validate_core_package_only_binding(
    *,
    evidence_ticket: str,
    contract: ProtocolTypedTicketContract,
    repository: str,
    pr_number: int,
    event_head_sha: str,
    api_get: Callable[[str], object],
    manifest_entry_model: type[ProtocolManifestEntryModel],
    manifest_hasher: Callable[[tuple[ProtocolPackageOnlyManifestEntry, ...]], str],
) -> PackageOnlyClassificationResult:
    """Validate a typed central binding against immutable live GitHub objects.

    The caller must provide a parsed shared Core contract and the shared Core
    entry model/hash helper from a separately trusted immutable source. This
    adapter never accepts a raw caller-supplied binding or schema.
    """

    binding = contract.package_only_deploy_binding
    if binding is None:
        return PackageOnlyClassificationResult(
            False, "Core code-only contract lacks a package-only deploy binding"
        )
    try:
        snapshot = resolve_pull_manifest(
            repository=repository,
            pr_number=pr_number,
            event_head_sha=event_head_sha,
            api_get=api_get,
        )
        raw_entries = enrich_pull_manifest(
            repository=repository,
            snapshot=snapshot,
            api_get=api_get,
        )
        live_manifest = tuple(
            manifest_entry_model.model_validate(entry.as_core_payload())
            for entry in raw_entries
        )
    except (PrManifestResolutionError, ValueError) as exc:
        return PackageOnlyClassificationResult(
            False, f"package-only live manifest resolution failed: {exc}"
        )
    return classify_package_only_change(
        evidence_ticket=evidence_ticket,
        contract_ticket_id=contract.ticket_id,
        proof_class=contract.proof_class,
        binding=binding,
        repository=repository,
        base_sha=snapshot.base_sha,
        head_sha=snapshot.head_sha,
        diff_base_sha=snapshot.diff_base_sha,
        live_manifest=live_manifest,
        manifest_hasher=manifest_hasher,
        raw_manifest=raw_entries,
        api_get=api_get,
    )
