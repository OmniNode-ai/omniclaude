# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""A wire topic a contract declares (OMN-21416)."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class ModelContractTopic(BaseModel):
    """A wire topic a contract declares.

    It is not a ``TopicBase`` member, and ``FanOutRule`` reads only
    ``topic_base.value``, so a contract-declared fan-out rule carries this
    model in ``topic_base``.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    value: str = Field(min_length=1)
