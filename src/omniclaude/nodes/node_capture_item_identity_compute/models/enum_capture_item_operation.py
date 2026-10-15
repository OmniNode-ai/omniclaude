# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""The operations of node_capture_item_identity_compute."""

from __future__ import annotations

from enum import StrEnum


class EnumCaptureItemOperation(StrEnum):
    """What a ModelCaptureItemIdentityRequest asks for."""

    CONTENT_RECORD_ID = "content_record_id"
    CLAIM_EVENT_ID = "claim_event_id"
    NEXT_PRODUCER_SEQ = "next_producer_seq"
    HIGH_WATER = "high_water"


__all__ = ["EnumCaptureItemOperation"]
