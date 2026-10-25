# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Named, typed callback inputs to the Done-flip hook runner."""

from __future__ import annotations

from typing import TypedDict

from omniclaude.nodes.node_linear_effect.protocols.protocol_done_receipt_policy import (
    ProtocolPRFetcher,
    ProtocolRepoEvidenceProbe,
)


class ModelDoneGuardReaders(TypedDict, total=False):
    """Optional reader overrides; omitted readers use the decider's defaults."""

    repo_evidence_probe: ProtocolRepoEvidenceProbe
    pr_fetcher: ProtocolPRFetcher
