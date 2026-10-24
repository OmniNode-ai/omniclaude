# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""No workflow in this repository references a provider key secret (OMN-20974).

The team is its own customer: a team provider key reaches a model through the
tenant route, resolved by reference at the effect boundary, never from a
GitHub Actions secret. This ratchet scans ``.github/workflows`` for secret
references whose name is a provider's key. A secret for a non-provider service
(for example a ticket-system key) is not a provider key and is left alone.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

_ROOT = Path(__file__).resolve().parents[2]
_WORKFLOWS = _ROOT / ".github" / "workflows"

_PROVIDERS = (
    "ANTHROPIC",
    "COHERE",
    "DEEPSEEK",
    "FIREWORKS",
    "GEMINI",
    "GLM",
    "GROQ",
    "MISTRAL",
    "OPENAI",
    "OPENROUTER",
    "PERPLEXITY",
    "TOGETHER",
    "XAI",
    "ZAI",
)
_SECRET_REF = re.compile(
    r"secrets\s*\.\s*([A-Za-z0-9_]+)|secrets\s*\[\s*'([^']+)'\s*\]"
)
_PROVIDER_KEY_NAME = re.compile(
    rf"(?:^|_)(?:{'|'.join(_PROVIDERS)})(?:_|$)", re.IGNORECASE
)
_CREDENTIAL_WORD = re.compile(r"(?:KEY|TOKEN|SECRET)", re.IGNORECASE)


def provider_key_secrets(text: str) -> list[str]:
    """Names of the provider key secrets a workflow's text references."""
    found: list[str] = []
    for match in _SECRET_REF.finditer(text):
        name = match.group(1) or match.group(2)
        if _PROVIDER_KEY_NAME.search(name) and _CREDENTIAL_WORD.search(name):
            found.append(name)
    return found


def test_the_detector_flags_a_planted_provider_key_reference() -> None:
    """Positive control: the scan would catch the reference this ticket removed."""
    planted = (
        "env:\n"
        "  RUNG_EVAL_CLOUD_OPENROUTER_API_KEY: "
        "${{ secrets.RUNG_EVAL_CLOUD_OPENROUTER_API_KEY }}\n"
        "  OTHER: ${{ secrets['ANTHROPIC_API_KEY'] }}\n"
    )
    assert provider_key_secrets(planted) == [
        "RUNG_EVAL_CLOUD_OPENROUTER_API_KEY",
        "ANTHROPIC_API_KEY",
    ]


def test_the_detector_leaves_a_non_provider_secret_alone() -> None:
    clean = (
        "LINEAR_API_KEY: ${{ secrets.LINEAR_API_KEY }}\nT: ${{ secrets.GITHUB_TOKEN }}"
    )
    assert provider_key_secrets(clean) == []


def test_workflows_are_scanned() -> None:
    """Zero-hit control: the scan reads real files, so an empty result means clean."""
    assert sorted(
        (
            *_WORKFLOWS.glob("*.y*ml"),
            *_WORKFLOWS.parent.glob("actions/**/action.y*ml"),
        )
    ), "no workflow or action files found to scan"


def test_no_provider_key_in_workflows() -> None:
    offenders = {
        str(path.relative_to(_ROOT)): names
        for path in sorted(
            (
                *_WORKFLOWS.glob("*.y*ml"),
                *_WORKFLOWS.parent.glob("actions/**/action.y*ml"),
            )
        )
        if (names := provider_key_secrets(path.read_text(encoding="utf-8")))
    }
    assert offenders == {}, (
        "a workflow references a provider key secret; a team key is read by "
        f"reference through the tenant route, not from Actions: {offenders}"
    )
