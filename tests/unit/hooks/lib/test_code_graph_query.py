# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Tests for code_graph_query.py CLI wrapper."""

import json
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

pytestmark = pytest.mark.unit

# Add hooks/lib to path for import
HOOKS_LIB = str(
    Path(__file__).resolve().parents[4] / "plugins" / "onex" / "hooks" / "lib"
)
if HOOKS_LIB not in sys.path:
    sys.path.insert(0, HOOKS_LIB)


class TestStructuralMode:
    """Test SQL-based structural queries for epic-level context."""

    def test_structural_returns_entities_on_success(self):
        from code_graph_query import query_structural

        entity_output = (
            "omniclaude|class|DispatchHandler|omniclaude.runtime.handler|handler\n"
            "omniclaude|protocol|BaseHandler|omniclaude.protocols.base|protocol"
        )
        rel_output = "omniclaude|implements|3"
        # _run_psql called 3 times: preflight, entity query, relationship query
        with patch(
            "code_graph_query._run_psql",
            side_effect=[
                (True, "1"),  # preflight
                (True, entity_output),  # entity query
                (True, rel_output),  # relationship query
            ],
        ):
            result = query_structural(repos=["omniclaude"])
        assert result["success"] is True
        assert result["mode"] == "structural"
        assert len(result["entities"]) == 2
        assert result["entities"][0]["entity_name"] == "DispatchHandler"
        assert len(result["relationships"]) == 1
        assert result["relationships"][0]["count"] == 3

    def test_structural_graceful_on_psql_failure(self):
        from code_graph_query import query_structural

        with patch("code_graph_query._run_psql", return_value=(False, "")):
            result = query_structural(repos=["omniclaude"])
        assert result["success"] is True
        assert result["status"] == "service_unavailable"
        assert result["entities"] == []

    def test_structural_rejects_unsafe_repo_names(self):
        from code_graph_query import query_structural

        result = query_structural(repos=["omniclaude; DROP TABLE"])
        assert result["status"] == "service_unavailable"
        assert "unsafe" in result.get("error", "").lower()


class TestSemanticMode:
    """Test Qdrant-based semantic queries for ticket-level context."""

    def test_semantic_returns_ranked_results(self):
        from code_graph_query import query_semantic

        mock_embedding = [0.1] * 4096
        mock_qdrant_response = {
            "result": [
                {
                    "score": 0.85,
                    "payload": {
                        "entity_name": "DispatchHandler",
                        "entity_type": "class",
                        "qualified_name": "omniclaude.runtime.handler.DispatchHandler",
                        "source_repo": "omniclaude",
                        "classification": "handler",
                    },
                },
            ]
        }
        with (
            patch("code_graph_query._get_embedding", return_value=mock_embedding),
            patch(
                "code_graph_query._search_qdrant",
                return_value=mock_qdrant_response,
            ),
        ):
            result = query_semantic(query="add dispatch handler", limit=10)
        assert result["success"] is True
        assert result["mode"] == "semantic"
        assert len(result["entities"]) == 1
        assert result["entities"][0]["entity_name"] == "DispatchHandler"

    def test_semantic_filters_by_repo_when_provided(self):
        from code_graph_query import query_semantic

        mock_embedding = [0.1] * 4096
        mock_qdrant_response = {
            "result": [
                {
                    "score": 0.9,
                    "payload": {
                        "entity_name": "A",
                        "source_repo": "omniclaude",
                        "entity_type": "class",
                        "qualified_name": "a",
                        "classification": "handler",
                    },
                },
                {
                    "score": 0.85,
                    "payload": {
                        "entity_name": "B",
                        "source_repo": "omniintelligence",
                        "entity_type": "class",
                        "qualified_name": "b",
                        "classification": "handler",
                    },
                },
            ]
        }
        with (
            patch("code_graph_query._get_embedding", return_value=mock_embedding),
            patch(
                "code_graph_query._search_qdrant",
                return_value=mock_qdrant_response,
            ),
        ):
            result = query_semantic(query="handler", repos=["omniclaude"], limit=10)
        assert len(result["entities"]) == 1
        assert result["entities"][0]["entity_name"] == "A"

    def test_semantic_graceful_on_qdrant_unavailable(self):
        from code_graph_query import query_semantic

        with patch(
            "code_graph_query._get_embedding",
            side_effect=Exception("connection refused"),
        ):
            result = query_semantic(query="anything", limit=10)
        assert result["success"] is True
        assert result["status"] == "service_unavailable"


class TestOutputContract:
    """Test that wrapper output always has stable interface fields."""

    def test_structural_always_has_required_fields(self):
        from code_graph_query import query_structural

        with patch("code_graph_query._run_psql", return_value=(False, "")):
            result = query_structural(repos=["omniclaude"])
        for field in ("success", "mode", "status", "entities"):
            assert field in result, f"Missing required field: {field}"
        assert isinstance(result["entities"], list)

    def test_semantic_always_has_required_fields(self):
        from code_graph_query import query_semantic

        with patch("code_graph_query._get_embedding", side_effect=Exception("down")):
            result = query_semantic(query="test", limit=5)
        for field in ("success", "mode", "status", "entities"):
            assert field in result, f"Missing required field: {field}"
        assert isinstance(result["entities"], list)


class TestCLIEntryPoint:
    """Test the stdin/stdout JSON contract."""

    def test_cli_structural_mode(self):
        script = Path(HOOKS_LIB) / "code_graph_query.py"
        if not script.exists():
            pytest.skip("Script not yet created")
        input_json = json.dumps({"mode": "structural", "repos": ["omniclaude"]})
        proc = subprocess.run(
            [sys.executable, str(script)],
            input=input_json,
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
        assert proc.returncode == 0
        output = json.loads(proc.stdout)
        assert "success" in output
        assert "mode" in output

    def test_cli_always_exits_zero(self):
        script = Path(HOOKS_LIB) / "code_graph_query.py"
        if not script.exists():
            pytest.skip("Script not yet created")
        input_json = json.dumps({"mode": "invalid"})
        proc = subprocess.run(
            [sys.executable, str(script)],
            input=input_json,
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
        assert proc.returncode == 0
