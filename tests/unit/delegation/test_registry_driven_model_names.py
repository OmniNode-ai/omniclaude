# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""Tests proving task_classifier and quorum derive model names from bifrost_delegation.yaml.

Motivation: OMN-11937
- task_classifier.py had `_DELEGATE_MODEL_NAME = "qwen2.5-14b"` hardcoded
- quorum.py had DEFAULT_MODELS with "qwen3-coder-30b" / "gemini-2.5-flash" hardcoded

Both must be derived from bifrost_delegation.yaml (the contract) so that
changing the YAML changes behavior without editing Python source.

TDD: tests written to FAIL on the old hardcoded values, pass after the fix.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

# ---------------------------------------------------------------------------
# Helpers: load bifrost_delegation.yaml
# ---------------------------------------------------------------------------

_BIFROST_YAML_PATH = (
    Path(__file__).parent.parent.parent.parent
    / "src"
    / "omniclaude"
    / "delegation"
    / "bifrost_delegation.yaml"
)


def _load_bifrost() -> dict:
    """Load bifrost_delegation.yaml as a plain dict."""
    assert _BIFROST_YAML_PATH.is_file(), (
        f"bifrost_delegation.yaml not found at {_BIFROST_YAML_PATH}"
    )
    with _BIFROST_YAML_PATH.open(encoding="utf-8") as f:
        return yaml.safe_load(f)


def _bifrost_backend_model_names() -> set[str]:
    """Return all model_name values from bifrost backends."""
    bifrost = _load_bifrost()
    return {b["model_name"] for b in bifrost.get("backends", [])}


def _bifrost_local_backend_model_names() -> set[str]:
    """Return model_name values for local-tier backends only."""
    bifrost = _load_bifrost()
    return {
        b["model_name"] for b in bifrost.get("backends", []) if b.get("tier") == "local"
    }


# ---------------------------------------------------------------------------
# Task 1: TaskClassifier._DELEGATE_MODEL_NAME must come from bifrost contract
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestTaskClassifierDelegateModelName:
    """TaskClassifier._DELEGATE_MODEL_NAME must not be a hardcoded string literal."""

    def test_delegate_model_name_exists_in_bifrost_backends(self) -> None:
        """The delegate model name must match a backend in bifrost_delegation.yaml.

        This test FAILS when _DELEGATE_MODEL_NAME = "qwen2.5-14b" is hardcoded
        and "qwen2.5-14b" is not a model_name in any bifrost backend.

        Fix: derive _DELEGATE_MODEL_NAME from bifrost_delegation.yaml by reading
        the model_name of the first local-tier code_generation backend.
        """
        from omniclaude.lib.task_classifier import TaskClassifier

        delegate_model = TaskClassifier._DELEGATE_MODEL_NAME
        bifrost_model_names = _bifrost_backend_model_names()

        assert delegate_model in bifrost_model_names, (
            f"TaskClassifier._DELEGATE_MODEL_NAME='{delegate_model}' is not a "
            f"model_name in bifrost_delegation.yaml backends: {sorted(bifrost_model_names)}. "
            "Fix: derive _DELEGATE_MODEL_NAME from the bifrost contract."
        )

    def test_delegate_model_is_a_local_backend(self) -> None:
        """The delegate model name should be a local-tier backend (zero API cost).

        Delegation to a local model is the cost-saving rationale. If the
        delegate model is not local, savings estimates are wrong.
        """
        from omniclaude.lib.task_classifier import TaskClassifier

        delegate_model = TaskClassifier._DELEGATE_MODEL_NAME
        local_models = _bifrost_local_backend_model_names()

        assert delegate_model in local_models, (
            f"TaskClassifier._DELEGATE_MODEL_NAME='{delegate_model}' is not in "
            f"local-tier bifrost backends: {sorted(local_models)}. "
            "The delegate model should be local to achieve zero marginal API cost."
        )

    def test_delegate_model_name_not_bare_qwen2_literal(self) -> None:
        """_DELEGATE_MODEL_NAME must not be the bare legacy 'qwen2.5-14b' string.

        The old value 'qwen2.5-14b' is an informal alias, not a canonical model_name
        from any contract. bifrost_delegation.yaml uses full model IDs like
        'cyankiwi/Qwen3-Coder-30B-A3B-Instruct-AWQ-4bit'.
        """
        from omniclaude.lib.task_classifier import TaskClassifier

        assert TaskClassifier._DELEGATE_MODEL_NAME != "qwen2.5-14b", (
            "TaskClassifier._DELEGATE_MODEL_NAME is still the legacy alias 'qwen2.5-14b'. "
            "Derive it from bifrost_delegation.yaml (canonical model_name field)."
        )


# ---------------------------------------------------------------------------
# Task 2: AIQuorum.DEFAULT_MODELS must come from bifrost contract
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestQuorumDefaultModels:
    """AIQuorum.DEFAULT_MODELS model names must come from bifrost_delegation.yaml."""

    def test_quorum_default_model_names_exist_in_bifrost(self) -> None:
        """Every model name in DEFAULT_MODELS must be in bifrost backends.

        This test FAILS when DEFAULT_MODELS contains "qwen3-coder-30b" (an
        informal name) that is not a model_name in bifrost_delegation.yaml.

        Fix: derive DEFAULT_MODELS from bifrost_delegation.yaml backends.
        """
        from omniclaude.lib.utils.consensus.quorum import AIQuorum

        bifrost_model_names = _bifrost_backend_model_names()
        for model_cfg in AIQuorum.DEFAULT_MODELS:
            assert model_cfg.name in bifrost_model_names, (
                f"AIQuorum.DEFAULT_MODELS contains '{model_cfg.name}' which is not "
                f"a model_name in bifrost_delegation.yaml: {sorted(bifrost_model_names)}. "
                "Fix: build DEFAULT_MODELS from the bifrost contract."
            )

    def test_quorum_has_at_least_one_local_model(self) -> None:
        """DEFAULT_MODELS must include at least one local backend.

        A quorum of only cloud models defeats the purpose of local-first routing.
        """
        from omniclaude.lib.utils.consensus.quorum import AIQuorum, ModelProvider

        local_models = [
            m
            for m in AIQuorum.DEFAULT_MODELS
            if m.provider == ModelProvider.OPENAI_COMPATIBLE
        ]
        assert local_models, (
            "AIQuorum.DEFAULT_MODELS has no OPENAI_COMPATIBLE (local) model. "
            "At least one local model is required for zero-cost quorum scoring."
        )
