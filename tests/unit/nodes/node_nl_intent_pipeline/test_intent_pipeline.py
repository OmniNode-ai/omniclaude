# SPDX-License-Identifier: MIT
# Copyright (c) 2025 OmniNode Team
"""Unit tests for the NL Intent Pipeline (OMN-2501).

Test markers:
    @pytest.mark.unit  — all tests here

Coverage:
- R1: Parse raw NL into typed Intent object
  - Output is ModelIntentObject (frozen Pydantic)
  - Includes intent_type, entities, confidence, nl_input_hash
  - Low-confidence intents are flagged (not rejected)
  - Intent object is JSON/YAML serializable
- R2: Integration with OMN-2348 primitives
  - Service call succeeds and maps intent_class to EnumIntentType
  - Service unavailable falls back to keyword classification
"""

from __future__ import annotations

import json
import uuid
from unittest.mock import MagicMock, patch

import pytest

from omniclaude.nodes.node_nl_intent_pipeline.enums.enum_intent_type import (
    EnumIntentType,
)
from omniclaude.nodes.node_nl_intent_pipeline.enums.enum_resolution_path import (
    EnumResolutionPath,
)
from omniclaude.nodes.node_nl_intent_pipeline.handler_nl_intent_default import (
    HandlerNlIntentDefault,
    _extract_entities,
    _keyword_classify,
)
from omniclaude.nodes.node_nl_intent_pipeline.models.model_extracted_entity import (
    ModelExtractedEntity,
)
from omniclaude.nodes.node_nl_intent_pipeline.models.model_intent_object import (
    LOW_CONFIDENCE_THRESHOLD,
    ModelIntentObject,
)
from omniclaude.nodes.node_nl_intent_pipeline.models.model_nl_parse_request import (
    ModelNlParseRequest,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _request(raw_nl: str, **kwargs: object) -> ModelNlParseRequest:
    defaults: dict[str, object] = {
        "raw_nl": raw_nl,
        "correlation_id": uuid.uuid4(),
    }
    defaults.update(kwargs)
    return ModelNlParseRequest(**defaults)  # type: ignore[arg-type]


def _handler() -> HandlerNlIntentDefault:
    return HandlerNlIntentDefault()


# ---------------------------------------------------------------------------
# R1: Model structure & validation
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestModelIntentObject:
    """ModelIntentObject construction and validation."""

    def test_build_produces_frozen_pydantic_model(self) -> None:
        intent = ModelIntentObject.build(
            intent_id="test-123",
            nl_input="implement a new feature for login",
            intent_type=EnumIntentType.FEATURE,
            confidence=0.85,
        )
        assert isinstance(intent, ModelIntentObject)
        # Frozen: mutation raises
        with pytest.raises(Exception):
            intent.intent_id = "changed"  # type: ignore[misc]

    def test_build_sets_derived_fields(self) -> None:
        nl = "fix the authentication security bug"
        intent = ModelIntentObject.build(
            intent_id="id-1",
            nl_input=nl,
            intent_type=EnumIntentType.BUG_FIX,
            confidence=0.9,
        )
        assert intent.nl_input_hash == ModelIntentObject.hash_nl_input(nl)
        assert intent.raw_nl_length == len(nl)
        assert intent.is_low_confidence is False

    def test_low_confidence_flag_is_set_when_below_threshold(self) -> None:
        confidence = LOW_CONFIDENCE_THRESHOLD - 0.01
        intent = ModelIntentObject.build(
            intent_id="id-2",
            nl_input="do something",
            intent_type=EnumIntentType.GENERAL,
            confidence=confidence,
        )
        assert intent.is_low_confidence is True

    def test_low_confidence_flag_false_at_threshold(self) -> None:
        intent = ModelIntentObject.build(
            intent_id="id-3",
            nl_input="do something",
            intent_type=EnumIntentType.GENERAL,
            confidence=LOW_CONFIDENCE_THRESHOLD,
        )
        # Exactly at threshold is NOT low confidence
        assert intent.is_low_confidence is False

    def test_is_json_serializable(self) -> None:
        intent = ModelIntentObject.build(
            intent_id="id-4",
            nl_input="refactor the database layer",
            intent_type=EnumIntentType.REFACTOR,
            confidence=0.88,
        )
        as_json = intent.model_dump_json()
        parsed = json.loads(as_json)
        assert parsed["intent_type"] == "REFACTOR"
        assert "nl_input_hash" in parsed
        assert "confidence" in parsed

    def test_is_yaml_compatible(self) -> None:
        intent = ModelIntentObject.build(
            intent_id="id-5",
            nl_input="write unit tests for the parser",
            intent_type=EnumIntentType.TESTING,
            confidence=0.91,
        )
        as_dict = intent.model_dump()
        assert isinstance(as_dict, dict)
        assert as_dict["intent_type"] == "TESTING"

    def test_validator_rejects_inconsistent_low_confidence_flag(self) -> None:
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            ModelIntentObject(
                intent_id="bad",
                nl_input_hash="a" * 64,
                intent_type=EnumIntentType.GENERAL,
                confidence=0.9,  # high confidence
                is_low_confidence=True,  # inconsistent
            )

    def test_entities_are_tuple(self) -> None:
        entity = ModelExtractedEntity(
            entity_type="TICKET", value="OMN-2501", raw_span="OMN-2501"
        )
        intent = ModelIntentObject.build(
            intent_id="id-6",
            nl_input="implement OMN-2501",
            intent_type=EnumIntentType.CODE,
            confidence=0.8,
            entities=(entity,),
        )
        assert isinstance(intent.entities, tuple)
        assert intent.entities[0].value == "OMN-2501"

    def test_resolution_path_defaults_to_none(self) -> None:
        intent = ModelIntentObject.build(
            intent_id="id-7",
            nl_input="review the PR",
            intent_type=EnumIntentType.REVIEW,
            confidence=0.9,
        )
        assert intent.resolution_path == EnumResolutionPath.NONE


# ---------------------------------------------------------------------------
# R1: Keyword classification
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestKeywordClassification:
    """_keyword_classify covers all intent types."""

    def test_security_keyword(self) -> None:
        itype, conf = _keyword_classify("fix the security vulnerability in auth")
        assert itype == EnumIntentType.SECURITY
        assert conf > 0.5

    def test_bug_fix_keyword(self) -> None:
        itype, conf = _keyword_classify("fix the broken login flow")
        assert itype == EnumIntentType.BUG_FIX
        assert conf >= 0.5

    def test_refactor_keyword(self) -> None:
        itype, _conf = _keyword_classify("refactor the database module")
        assert itype == EnumIntentType.REFACTOR

    def test_testing_keyword(self) -> None:
        itype, _conf = _keyword_classify("write unit tests for the parser")
        assert itype == EnumIntentType.TESTING

    def test_documentation_keyword(self) -> None:
        itype, _conf = _keyword_classify("update the doc and readme")
        assert itype == EnumIntentType.DOCUMENTATION

    def test_epic_decomposition_keyword(self) -> None:
        itype, _conf = _keyword_classify("decompose this epic into sub-tickets")
        assert itype == EnumIntentType.EPIC_DECOMPOSITION

    def test_unknown_when_no_match(self) -> None:
        itype, conf = _keyword_classify("xyz abc 12345 qwerty")
        assert itype == EnumIntentType.UNKNOWN
        assert conf == 0.0

    def test_confidence_capped_at_1(self) -> None:
        text = " ".join(["security"] * 20)
        _, conf = _keyword_classify(text)
        assert conf <= 1.0


# ---------------------------------------------------------------------------
# R1: Entity extraction
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestEntityExtraction:
    """_extract_entities recognises tickets and known repos."""

    def test_ticket_reference_extracted(self) -> None:
        entities = _extract_entities("implement OMN-2501 and OMN-2502")
        tickets = [e for e in entities if e.entity_type == "TICKET"]
        assert len(tickets) == 2
        values = {e.value for e in tickets}
        assert "OMN-2501" in values
        assert "OMN-2502" in values

    def test_repo_reference_extracted(self) -> None:
        entities = _extract_entities("changes to omniclaude and omnibase-core")
        repos = [e for e in entities if e.entity_type == "REPOSITORY"]
        repo_values = {e.value for e in repos}
        assert "omniclaude" in repo_values
        assert "omnibase-core" in repo_values

    def test_no_entities_for_plain_text(self) -> None:
        entities = _extract_entities("do something please")
        assert entities == ()

    def test_entity_model_is_frozen(self) -> None:
        entity = ModelExtractedEntity(
            entity_type="TICKET", value="OMN-1", raw_span="OMN-1"
        )
        with pytest.raises(Exception):
            entity.value = "changed"  # type: ignore[misc]


# ---------------------------------------------------------------------------
# R1: Handler — keyword fallback path
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestHandlerNlIntentDefaultKeywordPath:
    """HandlerNlIntentDefault uses keyword fallback when service unavailable."""

    def test_parse_returns_intent_object(self) -> None:
        handler = _handler()
        result = handler.parse_intent(_request("fix the authentication bug"))
        assert isinstance(result, ModelIntentObject)

    def test_low_confidence_flagged_but_not_rejected(self) -> None:
        # An unknown NL string gets UNKNOWN type with 0.0 confidence -> low conf
        handler = _handler()
        result = handler.parse_intent(_request("asdfghjkl qwertyuiop zxcvbnm"))
        assert result.is_low_confidence is True
        # No exception raised — rejection is the ambiguity gate's job

    def test_confidence_in_range(self) -> None:
        handler = _handler()
        result = handler.parse_intent(_request("implement new feature for login"))
        assert 0.0 <= result.confidence <= 1.0

    def test_nl_input_hash_is_sha256(self) -> None:
        handler = _handler()
        nl = "write tests for the pipeline"
        result = handler.parse_intent(_request(nl))
        import hashlib

        expected = hashlib.sha256(nl.encode()).hexdigest()
        assert result.nl_input_hash == expected

    def test_resolution_path_inference_on_keyword_fallback(self) -> None:
        handler = _handler()
        result = handler.parse_intent(_request("refactor the auth module"))
        assert result.resolution_path == EnumResolutionPath.INFERENCE

    def test_raw_nl_length_recorded(self) -> None:
        nl = "implement OMN-2501 feature"
        handler = _handler()
        result = handler.parse_intent(_request(nl))
        assert result.raw_nl_length == len(nl)


# ---------------------------------------------------------------------------
# R1: Handler — forced intent type override
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestHandlerForcedIntentType:
    """force_intent_type bypasses classification."""

    def test_forced_type_used(self) -> None:
        handler = _handler()
        result = handler.parse_intent(
            _request("anything", force_intent_type="SECURITY")
        )
        assert result.intent_type == EnumIntentType.SECURITY
        assert result.confidence == 1.0

    def test_invalid_forced_type_maps_to_unknown(self) -> None:
        handler = _handler()
        result = handler.parse_intent(
            _request("anything", force_intent_type="DOES_NOT_EXIST")
        )
        assert result.intent_type == EnumIntentType.UNKNOWN


# ---------------------------------------------------------------------------
# R2: Integration with OMN-2348 service
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestHandlerServiceIntegration:
    """HandlerNlIntentDefault uses service response when available."""

    def test_service_response_maps_to_enum(self) -> None:
        handler = _handler()
        mock_response = MagicMock()
        mock_response.read.return_value = json.dumps(
            {"success": True, "intent_class": "SECURITY", "confidence": 0.94}
        ).encode("utf-8")
        mock_response.__enter__ = lambda s: s
        mock_response.__exit__ = MagicMock(return_value=False)

        with patch("urllib.request.urlopen", return_value=mock_response):
            result = handler.parse_intent(
                _request("fix authentication", correlation_id=uuid.uuid4()),
                classification_url="http://mock-service/api/v1/intent/classify",
            )

        assert result.intent_type == EnumIntentType.SECURITY
        assert result.confidence == 0.94
        # Service call does not add INFERENCE resolution path
        assert result.resolution_path == EnumResolutionPath.NONE

    def test_service_unavailable_falls_back_to_keyword(self) -> None:
        handler = _handler()
        with patch(
            "urllib.request.urlopen",
            side_effect=OSError("connection refused"),
        ):
            result = handler.parse_intent(
                _request("refactor the module"),
                classification_url="http://bad-host/classify",
            )

        # Falls back to keyword; refactor matches
        assert result.intent_type == EnumIntentType.REFACTOR
        # Keyword fallback uses INFERENCE resolution path
        assert result.resolution_path == EnumResolutionPath.INFERENCE

    def test_no_service_url_skips_call(self) -> None:
        """When no service is configured, no HTTP call is made."""
        handler = _handler()
        with patch("urllib.request.urlopen") as mock_open:
            import os

            env_backup = {
                "OMNICLAUDE_INTENT_API_URL": os.environ.pop(
                    "OMNICLAUDE_INTENT_API_URL", None
                ),
                "INTELLIGENCE_SERVICE_URL": os.environ.pop(
                    "INTELLIGENCE_SERVICE_URL", None
                ),
            }
            try:
                result = handler.parse_intent(_request("write tests"))
            finally:
                for k, v in env_backup.items():
                    if v is not None:
                        os.environ[k] = v

        mock_open.assert_not_called()
        assert isinstance(result, ModelIntentObject)
