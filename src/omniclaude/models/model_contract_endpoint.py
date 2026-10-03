# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""A local LLM endpoint resolved from the bifrost routing contract (OMN-17103)."""

from __future__ import annotations

from typing import Final

from pydantic import BaseModel, ConfigDict, Field

#: Path suffix the OpenAI-compatible handlers append to a base URL.
OPENAI_CHAT_COMPLETIONS_SUFFIX: Final = "/v1/chat/completions"


class ModelContractEndpoint(BaseModel):
    """A local endpoint resolved from the routing contract.

    Attributes:
        backend_id: Contract backend the endpoint belongs to.
        url: COMPLETE chat endpoint URL, posted to verbatim.
        model_name: Model id sent in requests.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    backend_id: str = Field(min_length=1)
    url: str = Field(min_length=1)
    model_name: str = Field(min_length=1)

    @property
    def base_url(self) -> str | None:
        """The URL with the OpenAI chat suffix removed, or None.

        For handlers that append the suffix themselves. None when the contract's
        complete URL does not end in the OpenAI-compatible suffix.
        """
        return base_url_of(self.url)


def base_url_of(complete_url: str) -> str | None:
    """Strip the OpenAI chat suffix from a complete URL; None if it lacks it."""
    trimmed = complete_url.rstrip("/")
    if trimmed.endswith(OPENAI_CHAT_COMPLETIONS_SUFFIX):
        return trimmed[: -len(OPENAI_CHAT_COMPLETIONS_SUFFIX)]
    return None
