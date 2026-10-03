# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""semantic_check resolves its LLM endpoint from the routing contract (OMN-17103).

It once read ``LLM_DEEPSEEK_R1_URL`` and fell back to a literal localhost host.
The endpoint is now the contract's local reasoning backend, and an unconfigured
endpoint degrades to a no-shift result rather than reaching a guessed host.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from plugins.onex.skills._lib.decision_store import semantic_check as sc

_CHAT_URL = "http://lab-host:8000/v1/chat/completions"


def _decision() -> SimpleNamespace:
    return SimpleNamespace(
        decision_type="DESIGN_PATTERN",
        scope_domain="api",
        scope_layer="runtime",
        scope_services=["svc"],
    )


@pytest.mark.unit
def test_endpoint_is_the_contract_reasoning_backend(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("BIFROST_LOCAL_CODER_ENDPOINT_URL", _CHAT_URL)
    monkeypatch.setenv("LLM_CODER_MODEL_NAME", "contract-model")
    monkeypatch.setenv("LLM_DEEPSEEK_R1_URL", "http://retired:8101")
    assert sc._resolve_semantic_endpoint() == (_CHAT_URL, "contract-model")


@pytest.mark.unit
def test_unconfigured_endpoint_degrades_to_no_shift(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("BIFROST_LOCAL_CODER_ENDPOINT_URL", raising=False)
    monkeypatch.setenv("LLM_DEEPSEEK_R1_URL", "http://retired:8101")
    result = asyncio.run(
        sc.semantic_check_async(
            _decision(), _decision(), 0.8, "HIGH", "summary a", "summary b"
        )
    )
    assert result["severity_shift"] == 0
    assert result["error"] == "endpoint_unconfigured"
