# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""ModelEndpointDefaults reads every endpoint from the runtime contract (OMN-21743)."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

from omniclaude.models import model_endpoint_defaults
from omniclaude.models.model_endpoint_defaults import ModelEndpointDefaults

_CONTRACT = (
    Path(model_endpoint_defaults.__file__).resolve().parents[1]
    / "contracts"
    / "contract_omniclaude_runtime.yaml"
)


def _declared() -> dict[str, object]:
    document = yaml.safe_load(_CONTRACT.read_text(encoding="utf-8"))
    return dict(document["endpoints"])


def _write_contract(tmp_path: Path, section: dict[str, object] | None) -> Path:
    path = tmp_path / "contract.yaml"
    path.write_text(
        yaml.safe_dump({} if section is None else {"endpoints": section}),
        encoding="utf-8",
    )
    return path


@pytest.fixture(autouse=True)
def _clear_overlay_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ("INTELLIGENCE_SERVICE_URL", "OMNINODE_RUNTIME_HEALTH_URL"):
        monkeypatch.delenv(name, raising=False)


@pytest.mark.unit
def test_contract_values_reach_the_model() -> None:
    endpoints = ModelEndpointDefaults.from_contract()
    assert endpoints.valkey_default_url == "redis://onex-valkey:6379/0"
    assert endpoints.rag_base_url == "http://localhost:8181"
    assert endpoints.runtime_health_url == "http://localhost:8085/health"
    assert endpoints.intelligence_service_url == "http://localhost:8053"
    assert endpoints.github_https_url_prefix == "https://github.com/"
    assert endpoints.quirk_finding_schema_ref.startswith("registry://")
    assert set(endpoints.changelog_sources) == {
        "claude-code",
        "anthropic-sdk-python",
        "github-cli",
        "uv",
        "kafka-python",
    }


@pytest.mark.unit
def test_env_overlay_overrides_the_inline_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("INTELLIGENCE_SERVICE_URL", "http://intel.lane.invalid:7000")
    monkeypatch.setenv("OMNINODE_RUNTIME_HEALTH_URL", "http://127.0.0.1:9/health")
    endpoints = ModelEndpointDefaults.from_contract()
    assert endpoints.intelligence_service_url == "http://intel.lane.invalid:7000"
    assert endpoints.runtime_health_url == "http://127.0.0.1:9/health"


@pytest.mark.unit
def test_empty_overlay_counts_as_unset(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("INTELLIGENCE_SERVICE_URL", "")
    assert (
        ModelEndpointDefaults.from_contract().intelligence_service_url
        == "http://localhost:8053"
    )


@pytest.mark.unit
def test_missing_field_fails_to_load(tmp_path: Path) -> None:
    declared = _declared()
    del declared["rag_base_url"]
    with pytest.raises(ValidationError):
        ModelEndpointDefaults.from_contract(_write_contract(tmp_path, declared))


@pytest.mark.unit
def test_missing_section_fails_to_load(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="endpoints"):
        ModelEndpointDefaults.from_contract(_write_contract(tmp_path, None))


@pytest.mark.unit
def test_empty_changelog_sources_are_refused(tmp_path: Path) -> None:
    declared = _declared()
    declared["changelog_sources"] = {}
    with pytest.raises(ValidationError):
        ModelEndpointDefaults.from_contract(_write_contract(tmp_path, declared))
