# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Today's provider key formats stay with Claude (OMN-23413).

Every prompt can now go to a delegated model, so the gate is what keeps a
pasted key on the user's machine. Read 2026-11-14: an Anthropic key
(sk-ant-api03-...) passed as not sensitive, because the sk- pattern allowed no
hyphen after the prefix. Failure modes:

  K1  a hyphenated sk- key (Anthropic, OpenAI project, OpenRouter) is not caught.
  K2  a GitHub fine-grained or OAuth/app token is not caught.
  K3  a Google API key is not caught.
  K4  ordinary prose with "sk-" or a short id is flagged (over-blocking control).
  K5  a key written directly before or after a CJK character is not caught.
  K6  a stateless GitHub App installation token (ghs_<app id>_<JWT>, about 520
      characters with underscores and dots) is not caught.
  K7  a hyphenated name that starts with sk- (a branch, a CSS class) is flagged.

Fake keys are assembled at run time so no scanner reads a credential here.
"""

from __future__ import annotations

import pytest

from omniclaude.delegation.sensitivity_gate import SensitivityGate

pytestmark = pytest.mark.unit

_BODY = "Ab1Cd2Ef3Gh4Ij5Kl6Mn7Op8Qr9St0UvWx"


@pytest.mark.parametrize(
    "key",
    [
        "sk-" + "ant-api03-" + _BODY + "-" + _BODY,  # Anthropic
        "sk-" + "proj-" + _BODY + "_" + _BODY,  # OpenAI project key
        "sk-" + "or-v1-" + _BODY + _BODY,  # OpenRouter
        "sk-" + _BODY,  # classic, still caught
    ],
)
def test_hyphenated_sk_keys_are_sensitive(key: str) -> None:
    """K1."""
    assert SensitivityGate().check(f"use this key: {key}").is_sensitive


@pytest.mark.parametrize(
    "token",
    [
        "github_pat_" + "11ABCDEFG0" + _BODY + _BODY,
        "gho_" + _BODY + "ab",
        "ghs_" + _BODY + "ab",
        "ghu_" + _BODY + "ab",
        "ghr_" + _BODY + "ab",
    ],
)
def test_github_tokens_are_sensitive(token: str) -> None:
    """K2."""
    assert SensitivityGate().check(f"token {token} here").is_sensitive


def test_a_google_api_key_is_sensitive() -> None:
    """K3."""
    key = "AIza" + "Sy" + _BODY[:33]
    assert SensitivityGate().check(f"maps key {key}").is_sensitive


@pytest.mark.parametrize(
    "text",
    [
        "what does the sk-learn package do?",
        "explain the difference between TCP and UDP",
        "rename task-123 to task-124",
        "please rebase sk-add-user-profile-endpoint onto main",  # K7
        "the .sk-skeleton-loading-animation class flickers",  # K7
        "call ghs_installation_token_lookup_helper_function first",  # K6 control
        "我们在讨论网络第123章456节7890页",  # K5 control: CJK with digits
    ],
)
def test_ordinary_prose_is_not_sensitive(text: str) -> None:
    """K4, and the K5-K7 over-blocking controls."""
    assert not SensitivityGate().check(text).is_sensitive


_CJK_KEYS = [
    "sk-" + "ant-api03-" + _BODY + "-" + _BODY,
    "sk-" + "proj-" + _BODY + "_" + _BODY,
    "ghp_" + _BODY + "ab",
    "github_pat_" + "11ABCDEFG0" + _BODY + _BODY,
    "AKIA" + "ABCDEFGHIJ012345",
    "AIza" + "Sy" + _BODY[:33],
    "xoxb-" + "AbCdEfGhIjKl-" + _BODY,
]


@pytest.mark.parametrize("key", _CJK_KEYS)
@pytest.mark.parametrize(
    "template", ["我的密钥是{key}", "密钥{key}的", "鍵は{key}です"]
)
def test_a_key_next_to_cjk_text_is_sensitive(key: str, template: str) -> None:
    """K5."""
    assert SensitivityGate().check(template.format(key=key)).is_sensitive


def _stateless_installation_token() -> str:
    # ghs_<app id>_<JWT>: a JWT header, payload and signature, joined by dots.
    header = "eyJ" + "hbGciOiJSUzI1NiIsInR5cCI6IkpXVCJ9"
    payload = "eyJ" + (_BODY * 9)[:300]
    signature = ("Zx9_" + _BODY + "-") * 5
    return "ghs_" + "1234567" + "_" + ".".join((header, payload, signature))


@pytest.mark.parametrize(
    "template",
    [
        "the workflow printed GITHUB_TOKEN={token}",
        "export GH_TOKEN={token}",
        "token {token} here",
    ],
)
def test_a_stateless_github_app_token_is_sensitive(template: str) -> None:
    """K6."""
    token = _stateless_installation_token()
    assert len(token) > 500
    assert SensitivityGate().check(template.format(token=token)).is_sensitive


@pytest.mark.parametrize(
    "key",
    [
        "sk-" + "ant-api03-" + _BODY + "-" + _BODY,
        "sk-" + "proj-" + _BODY + "-" + _BODY,
        "sk-" + "svcacct-" + _BODY + "_" + _BODY,
        "sk-" + "or-v1-" + _BODY + _BODY,
        "sk-" + _BODY,
    ],
)
def test_real_sk_keys_still_match_after_tightening(key: str) -> None:
    """K7 positive control: tightening sk- keeps every real key format."""
    assert SensitivityGate().check(f"rebase onto {key} please").is_sensitive
