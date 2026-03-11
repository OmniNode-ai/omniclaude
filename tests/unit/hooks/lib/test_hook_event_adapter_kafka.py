# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Tests for hook_event_adapter.py confluent-kafka migration (OMN-4620).

Verifies:
- No stderr warning on import when confluent-kafka is installed
- KAFKA_AVAILABLE=True when confluent-kafka is available
- Silent degradation (KAFKA_AVAILABLE=False, no stderr spam) when confluent_kafka absent
"""

import importlib
import sys

import pytest

_ADAPTER_PATH = "plugins/onex/hooks/lib"


def _reload_adapter() -> object:
    for mod in list(sys.modules.keys()):
        if "hook_event_adapter" in mod:
            del sys.modules[mod]
    if _ADAPTER_PATH not in sys.path:
        sys.path.insert(0, _ADAPTER_PATH)
    return importlib.import_module("hook_event_adapter")


@pytest.mark.unit
def test_no_kafka_python_warning_on_import(capsys: pytest.CaptureFixture[str]) -> None:
    """hook_event_adapter should not print kafka-python warning when confluent-kafka is present."""
    _reload_adapter()
    captured = capsys.readouterr()
    assert "kafka-python not installed" not in captured.err


@pytest.mark.unit
def test_kafka_available_true_when_confluent_kafka_installed() -> None:
    """KAFKA_AVAILABLE should be True when confluent-kafka is in the venv."""
    adapter_mod = _reload_adapter()
    assert adapter_mod.KAFKA_AVAILABLE is True  # type: ignore[attr-defined]


@pytest.mark.unit
def test_kafka_available_false_when_confluent_kafka_missing(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """When confluent_kafka is absent, KAFKA_AVAILABLE=False and no stderr spam."""
    with pytest.MonkeyPatch().context() as mp:
        mp.setitem(sys.modules, "confluent_kafka", None)  # type: ignore[arg-type]
        adapter_mod = _reload_adapter()
    captured = capsys.readouterr()
    assert adapter_mod.KAFKA_AVAILABLE is False  # type: ignore[attr-defined]
    # No warning blast — silent degradation is the contract
    assert "kafka-python" not in captured.err
    assert "WARNING" not in captured.err
