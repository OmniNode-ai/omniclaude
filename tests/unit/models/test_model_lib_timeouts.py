# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Timeout values reach the lib and effect modules from the lib timeouts contract (OMN-21729)."""

from __future__ import annotations

import inspect
from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

from omniclaude.coverage.models import ModelCoverageCache
from omniclaude.lib.core.result_cache import ResultCache
from omniclaude.models.model_lib_timeouts import ModelLibTimeouts, lib_timeouts
from omniclaude.verification.self_check import run_self_check

_CONTRACT = (
    Path(__file__).resolve().parents[3]
    / "src"
    / "omniclaude"
    / "contracts"
    / "contract_omniclaude_lib_timeouts.yaml"
)

pytestmark = pytest.mark.unit


def _section() -> dict[str, object]:
    return yaml.safe_load(_CONTRACT.read_text(encoding="utf-8"))["lib"]


def test_lib_timeouts_equal_contract_section() -> None:
    assert lib_timeouts().model_dump() == _section()


def test_missing_value_fails_validation(tmp_path: Path) -> None:
    section = dict(_section())
    del section["self_check_seconds"]
    path = tmp_path / "contract.yaml"
    path.write_text(yaml.safe_dump({"lib": section}), encoding="utf-8")
    with pytest.raises(ValidationError):
        ModelLibTimeouts.from_contract(path)


def test_non_positive_value_fails_validation(tmp_path: Path) -> None:
    section = dict(_section())
    section["git_probe_seconds"] = 0
    path = tmp_path / "contract.yaml"
    path.write_text(yaml.safe_dump({"lib": section}), encoding="utf-8")
    with pytest.raises(ValidationError):
        ModelLibTimeouts.from_contract(path)


def test_result_cache_default_ttl_comes_from_contract() -> None:
    assert ResultCache().default_ttl == lib_timeouts().cache_ttl_seconds


def test_result_cache_accepts_injected_ttl() -> None:
    assert ResultCache(default_ttl_seconds=7).default_ttl == 7


def test_self_check_timeout_default_comes_from_contract() -> None:
    default = inspect.signature(run_self_check).parameters["timeout"].default
    assert default == lib_timeouts().self_check_seconds


def test_injected_ttl_and_timeout_have_no_literal_default() -> None:
    assert (
        inspect.signature(ModelCoverageCache.is_expired)
        .parameters["ttl_seconds"]
        .default
        is inspect.Parameter.empty
    )
