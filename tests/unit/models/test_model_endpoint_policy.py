# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""ModelEndpointPolicy loads the contract, and the OMN-21798 slice holds no URL literal."""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest
from pydantic import ValidationError

from omniclaude.models.model_endpoint_policy import ModelEndpointPolicy

pytestmark = pytest.mark.unit

_ROOT = Path(__file__).resolve().parents[3]
_SLICE = ("scripts/worktree_auto_prune.py",)
_SCHEME = re.compile(r"[a-z][a-z0-9+.-]*://\S+", re.IGNORECASE)


def _scheme_literals(source: str) -> list[str]:
    return [
        node.value
        for node in ast.walk(ast.parse(source))
        if isinstance(node, ast.Constant)
        and isinstance(node.value, str)
        and _SCHEME.match(node.value)
    ]


def test_every_field_loads_from_the_contract(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("LINEAR_GRAPHQL_URL", raising=False)
    policy = ModelEndpointPolicy.from_contract()
    assert policy.linear_graphql_url.startswith("https://")
    assert policy.github_web_base.startswith("https://")
    assert policy.github_ssh_base.startswith("ssh://")
    assert policy.omninode_github_org_base.startswith(policy.github_web_base)


def test_overlay_variable_wins_and_empty_counts_as_unset(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LINEAR_GRAPHQL_URL", "https://linear.test/graphql")
    assert (
        ModelEndpointPolicy.from_contract().linear_graphql_url
        == "https://linear.test/graphql"
    )
    monkeypatch.setenv("LINEAR_GRAPHQL_URL", "")
    assert ModelEndpointPolicy.from_contract().linear_graphql_url.startswith("https://")


def test_a_field_the_contract_omits_fails_to_load(tmp_path: Path) -> None:
    contract = tmp_path / "contract.yaml"
    contract.write_text('endpoints:\n  github_web_base: "x"\n', encoding="utf-8")
    with pytest.raises(ValidationError):
        ModelEndpointPolicy.from_contract(contract)


def test_a_contract_without_endpoints_fails_to_load(tmp_path: Path) -> None:
    contract = tmp_path / "contract.yaml"
    contract.write_text("other: 1\n", encoding="utf-8")
    with pytest.raises(ValueError, match="endpoints"):
        ModelEndpointPolicy.from_contract(contract)


def test_slice_files_hold_no_url_literal() -> None:
    offenders = {
        rel: found
        for rel in _SLICE
        if (found := _scheme_literals((_ROOT / rel).read_text(encoding="utf-8")))
    }
    assert offenders == {}


def test_scan_sees_a_planted_literal() -> None:
    assert _scheme_literals('URL = "http://localhost:1"\nOK = "plain"') == [
        "http://localhost:1"
    ]
