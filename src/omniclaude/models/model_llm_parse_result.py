# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""The typed result of reading one LLM reply (OMN-26353).

Three classification call sites used to turn an unparsable reply into ``None``
(or, in the quorum, into a made-up 0.5 vote), so a caller could not tell an
unparsable reply from no answer. Each site now returns this model and each
caller branches on ``status``.

Model ownership: PRIVATE to omniclaude.
"""

from __future__ import annotations

from typing import Self

from pydantic import BaseModel, ConfigDict, Field

from omniclaude.enums.enum_llm_parse_status import EnumLlmParseStatus

#: Cap on the reply text kept for the caller's log line and reasoning.
_RAW_REPLY_LIMIT = 200


class ModelLlmParseResult[ParsedT](BaseModel):
    """One LLM reply, read: the answer, or why there is none."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    status: EnumLlmParseStatus = Field(description="How the reply was read.")
    value: ParsedT | None = Field(
        default=None, description="The parsed answer; set only when PARSED."
    )
    raw_reply: str = Field(
        default="", description="The reply text, capped, kept for diagnosis."
    )
    reason: str = Field(
        default="", description="Why the reply holds no answer; empty when PARSED."
    )

    @property
    def is_parsed(self) -> bool:
        """True when the reply held a usable answer."""
        return self.status is EnumLlmParseStatus.PARSED

    @classmethod
    def parsed(cls, value: ParsedT, raw_reply: str = "") -> Self:
        """A reply that held a usable answer."""
        return cls(
            status=EnumLlmParseStatus.PARSED,
            value=value,
            raw_reply=raw_reply[:_RAW_REPLY_LIMIT],
        )

    @classmethod
    def unparsable(cls, raw_reply: str, reason: str) -> Self:
        """The endpoint replied, but the reply holds no usable answer."""
        return cls(
            status=EnumLlmParseStatus.UNPARSABLE,
            raw_reply=raw_reply[:_RAW_REPLY_LIMIT],
            reason=reason,
        )

    @classmethod
    def unavailable(cls, reason: str) -> Self:
        """No reply was read from the endpoint."""
        return cls(status=EnumLlmParseStatus.UNAVAILABLE, reason=reason)


__all__ = ["ModelLlmParseResult"]
