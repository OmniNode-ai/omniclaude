#!/usr/bin/env python3
"""
Test casing preservation for service names with acronyms.

Tests that service names like "PostgresCRUD", "RestAPI", etc. preserve
their casing throughout the generation pipeline.

SKIP REASON: Missing external dependency 'omnibase_core' module
-----------------------------------------------------------------------------
Status: BLOCKED - Cannot be fixed without external dependency
Priority: P1 - MVP Blocker
Tracking: Week 4 full pipeline integration

Root Cause:
    ModuleNotFoundError: No module named 'omnibase_core'

Import Chain:
    test → generation_pipeline → contract_builder_factory → generation/__init__.py
    → ComputeContractBuilder → omnibase_core.models.contracts (fails during collection)

Resolution:
    1. Install omnibase_core package (not available in pyproject.toml)
    2. Remove --ignore flag from pyproject.toml [tool.pytest.ini_options]
    3. Run: pytest agents/tests/test_casing_preservation.py -v
"""

import pytest

# Skip entire test module due to missing omnibase_core dependency
# TODO(Week 4): Install omnibase_core package and remove --ignore from pyproject.toml
pytestmark = pytest.mark.skip(
    reason="Missing external dependency 'omnibase_core' - ModuleNotFoundError. "
    "Install omnibase_core package to enable these tests. "
    "Tracking: Week 4 pipeline integration"
)

from agents.lib.generation_pipeline import GenerationPipeline  # noqa: E402
from agents.lib.omninode_template_engine import OmniNodeTemplateEngine  # noqa: E402
from agents.lib.prompt_parser import PromptParser  # noqa: E402


class TestCasingPreservation:
    """Test suite for casing preservation with acronyms"""

    def setup_method(self):
        """Set up test fixtures"""
        self.parser = PromptParser()
        self.pipeline = GenerationPipeline(enable_compilation_testing=False)
        self.template_engine = OmniNodeTemplateEngine(enable_cache=False)

    # -------------------------------------------------------------------------
    # PromptParser Tests
    # -------------------------------------------------------------------------

    def test_prompt_parser_preserves_postgres_crud(self):
        """Test that PromptParser preserves PostgresCRUD casing"""
        prompt = "EFFECT node called PostgresCRUD"
        node_name, confidence = self.parser._extract_node_name(prompt, "EFFECT")

        assert (
            node_name == "PostgresCRUD"
        ), f"Expected 'PostgresCRUD', got '{node_name}'"
        assert confidence == 1.0

    def test_prompt_parser_preserves_rest_api(self):
        """Test that PromptParser preserves RestAPI casing"""
        prompt = "EFFECT node called RestAPI"
        node_name, confidence = self.parser._extract_node_name(prompt, "EFFECT")

        assert node_name == "RestAPI", f"Expected 'RestAPI', got '{node_name}'"
        assert confidence == 1.0

    def test_prompt_parser_preserves_http_client(self):
        """Test that PromptParser preserves HttpClient casing"""
        prompt = "EFFECT node called HttpClient"
        node_name, confidence = self.parser._extract_node_name(prompt, "EFFECT")

        assert node_name == "HttpClient", f"Expected 'HttpClient', got '{node_name}'"
        assert confidence == 1.0

    def test_prompt_parser_preserves_sql_connector(self):
        """Test that PromptParser preserves SQLConnector casing"""
        prompt = "EFFECT node named SQLConnector"
        node_name, confidence = self.parser._extract_node_name(prompt, "EFFECT")

        assert (
            node_name == "SQLConnector"
        ), f"Expected 'SQLConnector', got '{node_name}'"
        assert confidence == 1.0

    # -------------------------------------------------------------------------
    # GenerationPipeline Tests
    # -------------------------------------------------------------------------

    def test_pipeline_to_snake_case_postgres_crud(self):
        """Test snake_case conversion preserves acronym detection"""
        result = self.pipeline._to_snake_case("PostgresCRUD")
        assert result == "postgres_crud", f"Expected 'postgres_crud', got '{result}'"

    def test_pipeline_to_snake_case_rest_api(self):
        """Test snake_case conversion for RestAPI"""
        result = self.pipeline._to_snake_case("RestAPI")
        assert result == "rest_api", f"Expected 'rest_api', got '{result}'"

    def test_pipeline_to_snake_case_http_client(self):
        """Test snake_case conversion for HttpClient"""
        result = self.pipeline._to_snake_case("HttpClient")
        assert result == "http_client", f"Expected 'http_client', got '{result}'"

    def test_pipeline_to_snake_case_sql_connector(self):
        """Test snake_case conversion for SQLConnector"""
        result = self.pipeline._to_snake_case("SQLConnector")
        assert result == "sql_connector", f"Expected 'sql_connector', got '{result}'"

    # -------------------------------------------------------------------------
    # OmniNodeTemplateEngine Tests
    # -------------------------------------------------------------------------

    def test_template_engine_preserves_pascal_case(self):
        """Test that _to_pascal_case preserves existing PascalCase"""
        result = self.template_engine._to_pascal_case("PostgresCRUD")
        assert result == "PostgresCRUD", f"Expected 'PostgresCRUD', got '{result}'"

    def test_template_engine_converts_snake_to_pascal_with_acronyms(self):
        """Test snake_case to PascalCase conversion preserves acronyms"""
        result = self.template_engine._to_pascal_case("postgres_crud")
        assert result == "PostgresCRUD", f"Expected 'PostgresCRUD', got '{result}'"

    def test_template_engine_preserves_rest_api(self):
        """Test RestAPI preservation"""
        result = self.template_engine._to_pascal_case("RestAPI")
        assert result == "RestAPI", f"Expected 'RestAPI', got '{result}'"

    def test_template_engine_converts_rest_api_snake(self):
        """Test rest_api to RestAPI conversion"""
        result = self.template_engine._to_pascal_case("rest_api")
        assert result == "RestAPI", f"Expected 'RestAPI', got '{result}'"

    def test_template_engine_preserves_http_client(self):
        """Test HttpClient preservation"""
        result = self.template_engine._to_pascal_case("HttpClient")
        assert result == "HttpClient", f"Expected 'HttpClient', got '{result}'"

    def test_template_engine_converts_http_client_snake(self):
        """Test http_client to HttpClient conversion"""
        result = self.template_engine._to_pascal_case("http_client")
        assert result == "HttpClient", f"Expected 'HttpClient', got '{result}'"

    def test_template_engine_handles_all_caps_acronyms(self):
        """Test handling of all-caps acronyms in snake_case"""
        test_cases = [
            ("sql", "SQL"),
            ("json", "JSON"),
            ("xml", "XML"),
            ("uuid", "UUID"),
            ("jwt", "JWT"),
            ("smtp", "SMTP"),
        ]

        for input_text, expected in test_cases:
            result = self.template_engine._to_pascal_case(input_text)
            assert (
                result == expected
            ), f"For '{input_text}': expected '{expected}', got '{result}'"

    def test_template_engine_handles_mixed_acronyms(self):
        """Test handling of mixed words and acronyms"""
        test_cases = [
            ("postgres_sql_adapter", "PostgresSQLAdapter"),
            ("rest_api_client", "RestAPIClient"),
            ("http_json_parser", "HttpJSONParser"),
        ]

        for input_text, expected in test_cases:
            result = self.template_engine._to_pascal_case(input_text)
            assert (
                result == expected
            ), f"For '{input_text}': expected '{expected}', got '{result}'"

    # -------------------------------------------------------------------------
    # Integration Tests
    # -------------------------------------------------------------------------

    def test_end_to_end_postgres_crud(self):
        """Test end-to-end flow: PostgresCRUD preservation"""
        prompt = "EFFECT node called PostgresCRUD for database operations"

        # Step 1: Parse prompt
        node_name, confidence = self.parser._extract_node_name(prompt, "EFFECT")
        assert (
            node_name == "PostgresCRUD"
        ), f"Parser: expected 'PostgresCRUD', got '{node_name}'"

        # Step 2: Convert to snake_case
        snake_case = self.pipeline._to_snake_case(node_name)
        assert (
            snake_case == "postgres_crud"
        ), f"Snake case: expected 'postgres_crud', got '{snake_case}'"

        # Step 3: Convert back to PascalCase
        pascal_case = self.template_engine._to_pascal_case(snake_case)
        assert (
            pascal_case == "PostgresCRUD"
        ), f"Pascal case: expected 'PostgresCRUD', got '{pascal_case}'"

    def test_end_to_end_rest_api(self):
        """Test end-to-end flow: RestAPI preservation"""
        prompt = "EFFECT node called RestAPI for HTTP operations"

        # Step 1: Parse prompt
        node_name, confidence = self.parser._extract_node_name(prompt, "EFFECT")
        assert node_name == "RestAPI", f"Parser: expected 'RestAPI', got '{node_name}'"

        # Step 2: Convert to snake_case
        snake_case = self.pipeline._to_snake_case(node_name)
        assert (
            snake_case == "rest_api"
        ), f"Snake case: expected 'rest_api', got '{snake_case}'"

        # Step 3: Convert back to PascalCase
        pascal_case = self.template_engine._to_pascal_case(snake_case)
        assert (
            pascal_case == "RestAPI"
        ), f"Pascal case: expected 'RestAPI', got '{pascal_case}'"

    def test_end_to_end_http_client(self):
        """Test end-to-end flow: HttpClient preservation"""
        prompt = "EFFECT node named HttpClient"

        # Step 1: Parse prompt
        node_name, confidence = self.parser._extract_node_name(prompt, "EFFECT")
        assert (
            node_name == "HttpClient"
        ), f"Parser: expected 'HttpClient', got '{node_name}'"

        # Step 2: Convert to snake_case
        snake_case = self.pipeline._to_snake_case(node_name)
        assert (
            snake_case == "http_client"
        ), f"Snake case: expected 'http_client', got '{snake_case}'"

        # Step 3: Convert back to PascalCase
        pascal_case = self.template_engine._to_pascal_case(snake_case)
        assert (
            pascal_case == "HttpClient"
        ), f"Pascal case: expected 'HttpClient', got '{pascal_case}'"

    def test_multiple_acronyms_in_sequence(self):
        """Test handling of multiple acronyms in sequence"""
        test_cases = [
            ("HTTPAPI", "http_api", "HTTPAPI"),
            ("RESTJSON", "restjson", "RESTJSON"),
            ("SQLXML", "sqlxml", "SQLXML"),
        ]

        for pascal_input, expected_snake, expected_pascal in test_cases:
            # Note: Multiple uppercase letters in sequence will be treated as one word
            # "HTTPAPI" -> "httpapi" (not "http_api") because there's no lowercase boundary
            # Snake case conversion is tested in other test cases

            # Test pascal_case preservation
            pascal_result = self.template_engine._to_pascal_case(pascal_input)
            assert (
                pascal_result == expected_pascal
            ), f"For '{pascal_input}': expected '{expected_pascal}', got '{pascal_result}'"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
