# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""The /onex:demo dispatcher reads its response topics from topics.yaml (OMN-21623)."""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType

import pytest

_DEMO_DIR = Path(__file__).resolve().parents[2] / "plugins" / "onex" / "skills" / "demo"
_TOPICS_PY = _DEMO_DIR / "_lib" / "topics.py"


def _load_topics_module() -> ModuleType:
    spec = importlib.util.spec_from_file_location("demo_topics_omn21623", _TOPICS_PY)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.unit
def test_response_topics_come_from_the_manifest() -> None:
    module = _load_topics_module()
    assert (
        module.TOPIC_DEMO_FANOUT_SKILL_RESPONSE
        == "onex.evt.omnibase-infra.demo-fanout-skill.v1"
    )
    assert (
        module.TOPIC_DEMO_COST_SKILL_RESPONSE
        == "onex.evt.omnibase-infra.demo-cost-skill.v1"
    )
    assert (
        module.TOPIC_DEMO_RENDER_SKILL_RESPONSE
        == "onex.evt.omnibase-infra.demo-render-skill.v1"
    )


@pytest.mark.unit
def test_manifest_missing_a_topic_fails_the_import(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    lib = tmp_path / "_lib"
    lib.mkdir()
    (lib / "topics.py").write_text(_TOPICS_PY.read_text(encoding="utf-8"))
    (tmp_path / "topics.yaml").write_text(
        "response_topics:\n  fanout: a\n  cost: b\n", encoding="utf-8"
    )
    spec = importlib.util.spec_from_file_location(
        "demo_topics_incomplete_omn21623", lib / "topics.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    with pytest.raises(KeyError, match="render"):
        spec.loader.exec_module(module)


@pytest.mark.unit
def test_module_source_holds_no_topic_literal() -> None:
    source = _TOPICS_PY.read_text(encoding="utf-8")
    assert '"onex.' not in source
    assert "'onex." not in source
