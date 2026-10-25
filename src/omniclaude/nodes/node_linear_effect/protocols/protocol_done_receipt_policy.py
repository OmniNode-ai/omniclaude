# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Structural boundaries for the standard-library-only Done receipt policy."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Protocol


class ProtocolContractRead(Protocol):
    """A contract read from a fixed repository revision."""

    @property
    def status(self) -> str: ...

    @property
    def text(self) -> str: ...

    @property
    def error(self) -> str: ...


class ProtocolContractReadStatuses(Protocol):
    """The successful contract-read status supplied by the plugin."""

    FOUND: str


class ProtocolReceiptOutcomes(Protocol):
    """The refusal outcome supplied by the plugin."""

    REFUSED: str


class ProtocolReceiptVerdict(Protocol):
    """A repository receipt verdict."""

    @property
    def outcome(self) -> str: ...

    @property
    def detail(self) -> str: ...


class ProtocolReceiptItem(Protocol):
    """The normalized criterion bindings of one evidence entry."""

    @property
    def item_id(self) -> str: ...

    @property
    def binds(self) -> frozenset[str]: ...

    @property
    def check_types(self) -> frozenset[str]: ...


class ProtocolReceiptEvidence(Protocol):
    """Plugin factories and binding readers, injected to avoid import cycles."""

    ContractReadStatus: ProtocolContractReadStatuses
    RepoEvidenceOutcome: ProtocolReceiptOutcomes

    RepoEvidenceVerdict: Callable[[str, str], ProtocolReceiptVerdict]
    EvidenceItem: Callable[[str, frozenset[str], frozenset[str]], ProtocolReceiptItem]

    def _retired_pairs(
        self, contract: Mapping[str, object]
    ) -> set[tuple[str, str]]: ...

    def _items(self, contract: Mapping[str, object]) -> list[Mapping[str, object]]: ...

    def canonical_ac_label(self, text: str) -> str: ...


class ProtocolDoneDecision(Protocol):
    """The only decision fields the hook runner consumes."""

    @property
    def allowed(self) -> bool: ...

    @property
    def reason(self) -> str: ...


class ProtocolReceiptPRRef(Protocol):
    """Identity of a cited pull request."""

    @property
    def repo(self) -> str | None: ...

    @property
    def number(self) -> int: ...


class ProtocolReceiptPR(Protocol):
    """Pull request state used by the receipt probe."""

    @property
    def ref(self) -> ProtocolReceiptPRRef: ...

    @property
    def state(self) -> str: ...

    @property
    def head_sha(self) -> str: ...

    @property
    def merge_commit_sha(self) -> str: ...

    @property
    def merged_at(self) -> str: ...

    @property
    def error(self) -> str | None: ...


class ProtocolRepoEvidenceProbe(Protocol):
    """Evaluate criterion receipts for the cited merged pull requests."""

    def __call__(
        self, ticket_id: str, descriptions: list[str], merged: list[ProtocolReceiptPR]
    ) -> ProtocolReceiptVerdict | None: ...


class ProtocolPRFetcher(Protocol):
    """Read the state of one cited pull request."""

    def __call__(self, ref: ProtocolReceiptPRRef) -> ProtocolReceiptPR: ...


class ProtocolDoneDecider(Protocol):
    """The hook decision and its injectable receipt/state readers."""

    def __call__(
        self,
        call: dict[str, object],
        *,
        repo_evidence_probe: ProtocolRepoEvidenceProbe | None = None,
        pr_fetcher: ProtocolPRFetcher = ...,
    ) -> ProtocolDoneDecision: ...
