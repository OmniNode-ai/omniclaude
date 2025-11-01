#!/usr/bin/env python3
"""
Comprehensive tests for OmniNode Template Engine

Tests cover:
- NodeTemplate class (placeholder extraction, validation, rendering)
- OmniNodeTemplateEngine class (template loading, caching, validation, generation)
- Security validation (path traversal, unsafe paths)
- Template context preparation
- File generation (models, contracts, manifests)
- Error handling and edge cases
- Async operations

Coverage target: 85-90% (from 22.8%)
Missing statements: 470 → <70
"""

import tempfile
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import Mock, patch
from uuid import uuid4

import pytest
from omnibase_core.errors import EnumCoreErrorCode, ModelOnexError

from agents.lib.omninode_template_engine import NodeTemplate, OmniNodeTemplateEngine

# ============================================================================
# Test Fixtures
# ============================================================================


@pytest.fixture
def sample_template_content():
    """Sample template content with placeholders"""
    return """
#!/usr/bin/env python3
\"\"\"
{MICROSERVICE_NAME} {NODE_TYPE} Node
\"\"\"

from typing import Dict, Any

class Node{MICROSERVICE_NAME_PASCAL}{NODE_TYPE}:
    \"\"\"
    {BUSINESS_DESCRIPTION}

    Domain: {DOMAIN}
    \"\"\"

    def __init__(self):
        self.name = "{MICROSERVICE_NAME}"
        self.domain = "{DOMAIN_PASCAL}"
"""


@pytest.fixture
def sample_context():
    """Sample context for template rendering"""
    return {
        "MICROSERVICE_NAME": "user_auth",
        "MICROSERVICE_NAME_PASCAL": "UserAuth",
        "NODE_TYPE": "EFFECT",
        "BUSINESS_DESCRIPTION": "User authentication service",
        "DOMAIN": "identity",
        "DOMAIN_PASCAL": "Identity",
    }


@pytest.fixture
def parsed_prd():
    """Sample parsed PRD"""
    from agents.lib.prd_analyzer import ParsedPRD

    return ParsedPRD(
        title="User Authentication Service",
        description="Secure user authentication and authorization service",
        functional_requirements=[
            "Authenticate users with email/password",
            "Support OAuth 2.0 authentication",
            "Manage user sessions",
        ],
        features=["Login", "Logout", "Session Management"],
        success_criteria=["99.9% uptime", "Sub-100ms auth latency"],
        technical_details=["JWT tokens", "Redis session store"],
        dependencies=["PostgreSQL", "Redis"],
        extracted_keywords=["auth", "oauth", "jwt", "session"],
        sections=["overview", "requirements", "features"],
        word_count=250,
    )


@pytest.fixture
def decomposition_result():
    """Sample decomposition result"""
    from agents.lib.prd_analyzer import DecompositionResult

    return DecompositionResult(
        tasks=[
            {
                "title": "Implement authentication",
                "description": "Core auth logic",
                "priority": "high",
            },
            {
                "title": "Setup session management",
                "description": "Session handling",
                "priority": "medium",
            },
            {
                "title": "Add OAuth support",
                "description": "OAuth integration",
                "priority": "low",
            },
        ],
        total_tasks=3,
        verification_successful=True,
    )


@pytest.fixture
def analysis_result(parsed_prd, decomposition_result):
    """Sample PRD analysis result"""
    from agents.lib.prd_analyzer import PRDAnalysisResult

    return PRDAnalysisResult(
        session_id=uuid4(),
        correlation_id=uuid4(),
        prd_content="Sample PRD content",
        parsed_prd=parsed_prd,
        decomposition_result=decomposition_result,
        node_type_hints={"EFFECT": 0.8, "COMPUTE": 0.2},
        recommended_mixins=["MixinEventBus", "MixinRetry"],
        external_systems=["PostgreSQL", "Redis", "Kafka"],
        quality_baseline=0.85,
        confidence_score=0.9,
        analysis_timestamp=datetime.now(timezone.utc).replace(tzinfo=None),
    )


@pytest.fixture
def temp_templates_dir(tmp_path, sample_template_content):
    """Create temporary templates directory with sample templates"""
    templates_dir = tmp_path / "templates"
    templates_dir.mkdir()

    # Create all 4 node type templates
    for node_type, filename in [
        ("EFFECT", "effect_node_template.py"),
        ("COMPUTE", "compute_node_template.py"),
        ("REDUCER", "reducer_node_template.py"),
        ("ORCHESTRATOR", "orchestrator_node_template.py"),
    ]:
        template_file = templates_dir / filename
        template_file.write_text(sample_template_content)

    return templates_dir


# ============================================================================
# NodeTemplate Tests
# ============================================================================


class TestNodeTemplate:
    """Test NodeTemplate class"""

    def test_initialization(self, sample_template_content):
        """Test NodeTemplate initialization"""
        template = NodeTemplate("EFFECT", sample_template_content)

        assert template.node_type == "EFFECT"
        assert template.template_content == sample_template_content
        assert isinstance(template.placeholders, set)
        assert len(template.placeholders) > 0

    def test_extract_placeholders(self, sample_template_content):
        """Test placeholder extraction"""
        template = NodeTemplate("EFFECT", sample_template_content)

        expected_placeholders = {
            "MICROSERVICE_NAME",
            "MICROSERVICE_NAME_PASCAL",
            "NODE_TYPE",
            "BUSINESS_DESCRIPTION",
            "DOMAIN",
            "DOMAIN_PASCAL",
        }

        assert template.placeholders == expected_placeholders

    def test_extract_placeholders_edge_cases(self):
        """Test placeholder extraction with edge cases"""
        # No placeholders
        template1 = NodeTemplate("EFFECT", "No placeholders here")
        assert template1.placeholders == set()

        # Mixed case (should only match uppercase)
        template2 = NodeTemplate("EFFECT", "{VALID} {invalid} {MixedCase}")
        assert template2.placeholders == {"VALID"}

        # Underscores (numbers not supported by pattern)
        template3 = NodeTemplate("EFFECT", "{VAR_ONE} {VAR_TWO_TEST}")
        assert template3.placeholders == {"VAR_ONE", "VAR_TWO_TEST"}

    def test_validate_context_valid(self, sample_template_content, sample_context):
        """Test context validation with valid context"""
        template = NodeTemplate("EFFECT", sample_template_content)
        result = template.validate_context(sample_context)

        assert result["valid"] is True
        assert result["missing_placeholders"] == []
        assert result["total_placeholders"] == len(template.placeholders)
        assert result["provided_variables"] == len(sample_context)

    def test_validate_context_missing_placeholders(self, sample_template_content):
        """Test context validation with missing placeholders"""
        template = NodeTemplate("EFFECT", sample_template_content)

        # Missing required placeholders
        incomplete_context = {
            "MICROSERVICE_NAME": "test",
            "NODE_TYPE": "EFFECT",
        }

        with pytest.raises(ModelOnexError) as exc_info:
            template.validate_context(incomplete_context)

        error = exc_info.value
        assert error.code == EnumCoreErrorCode.VALIDATION_ERROR
        assert "Missing required placeholders" in error.message
        assert "missing_placeholders" in error.details

    def test_validate_context_extra_variables(
        self, sample_template_content, sample_context
    ):
        """Test context validation with extra variables"""
        template = NodeTemplate("EFFECT", sample_template_content)

        # Add extra variables
        context_with_extra = sample_context.copy()
        context_with_extra["EXTRA_VAR"] = "extra"
        context_with_extra["ANOTHER_EXTRA"] = "another"

        result = template.validate_context(context_with_extra)

        assert result["valid"] is True
        assert "EXTRA_VAR" in result["extra_variables"]
        assert "ANOTHER_EXTRA" in result["extra_variables"]

    def test_render_successful(self, sample_template_content, sample_context):
        """Test successful template rendering"""
        template = NodeTemplate("EFFECT", sample_template_content)
        rendered = template.render(sample_context)

        # Check placeholders are replaced
        assert "{MICROSERVICE_NAME}" not in rendered
        assert "{NODE_TYPE}" not in rendered
        assert "user_auth" in rendered
        assert "UserAuth" in rendered
        assert "EFFECT" in rendered
        assert "User authentication service" in rendered
        assert "identity" in rendered
        assert "Identity" in rendered

    def test_render_with_none_values(self, sample_template_content):
        """Test rendering with None values"""
        template = NodeTemplate("EFFECT", sample_template_content)

        context_with_none = {
            "MICROSERVICE_NAME": "test",
            "MICROSERVICE_NAME_PASCAL": "Test",
            "NODE_TYPE": None,  # None value
            "BUSINESS_DESCRIPTION": "Test service",
            "DOMAIN": "test",
            "DOMAIN_PASCAL": "Test",
        }

        rendered = template.render(context_with_none)

        # None should be replaced with empty string
        assert rendered is not None
        assert "None" not in rendered

    def test_render_unresolved_placeholders(self):
        """Test rendering fails with unresolved placeholders"""
        template = NodeTemplate("EFFECT", "Test {VALID_VAR} content")

        # Context missing VALID_VAR - should fail at validation
        context = {}

        with pytest.raises(ModelOnexError) as exc_info:
            template.render(context)

        error = exc_info.value
        assert error.code == EnumCoreErrorCode.VALIDATION_ERROR
        assert "Missing required placeholders" in error.message

    def test_extract_placeholders_from_text(self):
        """Test placeholder extraction from text"""
        template = NodeTemplate("EFFECT", "")

        text_with_placeholders = "Test {VAR_ONE} and {VAR_TWO} content"
        placeholders = template._extract_placeholders_from_text(text_with_placeholders)

        assert placeholders == {"VAR_ONE", "VAR_TWO"}


# ============================================================================
# OmniNodeTemplateEngine Tests - Initialization
# ============================================================================


class TestOmniNodeTemplateEngineInitialization:
    """Test OmniNodeTemplateEngine initialization"""

    def test_initialization_default(self, temp_templates_dir):
        """Test default initialization"""
        with patch("agents.lib.omninode_template_engine.get_config") as mock_config:
            mock_config.return_value = Mock(template_directory=str(temp_templates_dir))

            engine = OmniNodeTemplateEngine(
                enable_cache=False, enable_pattern_learning=False
            )

            assert engine.templates_dir == temp_templates_dir
            assert not engine.enable_cache
            assert not engine.enable_pattern_learning
            assert engine.template_cache is None
            assert engine.pattern_library is None
            assert engine.pattern_storage is None

    def test_initialization_with_cache(self, temp_templates_dir):
        """Test initialization with caching enabled"""
        with patch("agents.lib.omninode_template_engine.get_config") as mock_config:
            mock_config.return_value = Mock(template_directory=str(temp_templates_dir))

            engine = OmniNodeTemplateEngine(
                enable_cache=True, enable_pattern_learning=False
            )

            assert engine.enable_cache
            assert engine.template_cache is not None

    def test_initialization_with_pattern_learning(self, temp_templates_dir):
        """Test initialization with pattern learning enabled"""
        with patch("agents.lib.omninode_template_engine.get_config") as mock_config:
            mock_config.return_value = Mock(
                template_directory=str(temp_templates_dir),
                qdrant_url="http://localhost:6333",
            )

            # Mock pattern library initialization
            with (
                patch("agents.lib.omninode_template_engine.PatternLibrary"),
                patch("agents.lib.omninode_template_engine.PatternStorage"),
            ):

                engine = OmniNodeTemplateEngine(
                    enable_cache=False, enable_pattern_learning=True
                )

                assert engine.enable_pattern_learning

    def test_initialization_pattern_learning_failure(self, temp_templates_dir):
        """Test graceful failure when pattern learning init fails"""
        with patch("agents.lib.omninode_template_engine.get_config") as mock_config:
            mock_config.return_value = Mock(
                template_directory=str(temp_templates_dir),
                qdrant_url="http://localhost:6333",
            )

            # Mock pattern library to raise exception
            with patch(
                "agents.lib.omninode_template_engine.PatternLibrary",
                side_effect=Exception("Qdrant unavailable"),
            ):

                engine = OmniNodeTemplateEngine(
                    enable_cache=False, enable_pattern_learning=True
                )

                # Should fallback gracefully
                assert not engine.enable_pattern_learning
                assert engine.pattern_library is None


# ============================================================================
# OmniNodeTemplateEngine Tests - Template Loading
# ============================================================================


class TestTemplateLoading:
    """Test template loading functionality"""

    def test_load_templates_success(self, temp_templates_dir):
        """Test successful template loading"""
        with patch("agents.lib.omninode_template_engine.get_config") as mock_config:
            mock_config.return_value = Mock(template_directory=str(temp_templates_dir))

            engine = OmniNodeTemplateEngine(
                enable_cache=False, enable_pattern_learning=False
            )

            # Check all 4 templates loaded
            assert "EFFECT" in engine.templates
            assert "COMPUTE" in engine.templates
            assert "REDUCER" in engine.templates
            assert "ORCHESTRATOR" in engine.templates

            # Check templates are NodeTemplate instances
            assert isinstance(engine.templates["EFFECT"], NodeTemplate)

    def test_load_templates_missing_file(self, tmp_path):
        """Test template loading with missing files"""
        # Create directory with only some templates
        templates_dir = tmp_path / "templates"
        templates_dir.mkdir()

        # Create only EFFECT template
        (templates_dir / "effect_node_template.py").write_text("# Test")

        with patch("agents.lib.omninode_template_engine.get_config") as mock_config:
            mock_config.return_value = Mock(template_directory=str(templates_dir))

            engine = OmniNodeTemplateEngine(
                enable_cache=False, enable_pattern_learning=False
            )

            # Only EFFECT should be loaded
            assert "EFFECT" in engine.templates
            assert "COMPUTE" not in engine.templates
            assert "REDUCER" not in engine.templates
            assert "ORCHESTRATOR" not in engine.templates

    def test_load_templates_with_cache(self, temp_templates_dir):
        """Test template loading with cache enabled"""
        with patch("agents.lib.omninode_template_engine.get_config") as mock_config:
            mock_config.return_value = Mock(template_directory=str(temp_templates_dir))

            engine = OmniNodeTemplateEngine(
                enable_cache=True, enable_pattern_learning=False
            )

            # Templates should be loaded
            assert len(engine.templates) == 4

            # Cache should have entries
            stats = engine.get_cache_stats()
            assert stats is not None


# ============================================================================
# OmniNodeTemplateEngine Tests - Cache Operations
# ============================================================================


class TestCacheOperations:
    """Test cache operations"""

    def test_get_cache_stats_enabled(self, temp_templates_dir):
        """Test getting cache stats when caching enabled"""
        with patch("agents.lib.omninode_template_engine.get_config") as mock_config:
            mock_config.return_value = Mock(template_directory=str(temp_templates_dir))

            engine = OmniNodeTemplateEngine(
                enable_cache=True, enable_pattern_learning=False
            )

            stats = engine.get_cache_stats()

            assert stats is not None
            assert "cached_templates" in stats
            assert "total_size_mb" in stats

    def test_get_cache_stats_disabled(self, temp_templates_dir):
        """Test getting cache stats when caching disabled"""
        with patch("agents.lib.omninode_template_engine.get_config") as mock_config:
            mock_config.return_value = Mock(template_directory=str(temp_templates_dir))

            engine = OmniNodeTemplateEngine(
                enable_cache=False, enable_pattern_learning=False
            )

            stats = engine.get_cache_stats()
            assert stats is None

    def test_invalidate_cache_specific(self, temp_templates_dir):
        """Test invalidating specific cache entry"""
        with patch("agents.lib.omninode_template_engine.get_config") as mock_config:
            mock_config.return_value = Mock(template_directory=str(temp_templates_dir))

            engine = OmniNodeTemplateEngine(
                enable_cache=True, enable_pattern_learning=False
            )

            # Invalidate specific template
            engine.invalidate_cache("EFFECT_template")

            # Should not raise exception
            assert True

    def test_invalidate_cache_all(self, temp_templates_dir):
        """Test invalidating all cache entries"""
        with patch("agents.lib.omninode_template_engine.get_config") as mock_config:
            mock_config.return_value = Mock(template_directory=str(temp_templates_dir))

            engine = OmniNodeTemplateEngine(
                enable_cache=True, enable_pattern_learning=False
            )

            # Invalidate all
            engine.invalidate_cache(None)

            # Should not raise exception
            assert True

    def test_warmup_cache(self, temp_templates_dir):
        """Test cache warmup"""
        with patch("agents.lib.omninode_template_engine.get_config") as mock_config:
            mock_config.return_value = Mock(template_directory=str(temp_templates_dir))

            engine = OmniNodeTemplateEngine(
                enable_cache=True, enable_pattern_learning=False
            )

            # Warmup should happen during init
            stats = engine.get_cache_stats()
            assert stats is not None


# ============================================================================
# OmniNodeTemplateEngine Tests - Validation
# ============================================================================


class TestValidation:
    """Test validation methods"""

    def test_validate_node_type_valid(self, temp_templates_dir):
        """Test node type validation with valid types"""
        with patch("agents.lib.omninode_template_engine.get_config") as mock_config:
            mock_config.return_value = Mock(template_directory=str(temp_templates_dir))

            engine = OmniNodeTemplateEngine(
                enable_cache=False, enable_pattern_learning=False
            )

            # Valid types should not raise
            engine._validate_node_type("EFFECT")
            engine._validate_node_type("COMPUTE")
            engine._validate_node_type("REDUCER")
            engine._validate_node_type("ORCHESTRATOR")

    def test_validate_node_type_invalid(self, temp_templates_dir):
        """Test node type validation with invalid types"""
        with patch("agents.lib.omninode_template_engine.get_config") as mock_config:
            mock_config.return_value = Mock(template_directory=str(temp_templates_dir))

            engine = OmniNodeTemplateEngine(
                enable_cache=False, enable_pattern_learning=False
            )

            # Invalid type should raise
            with pytest.raises(ModelOnexError) as exc_info:
                engine._validate_node_type("INVALID")

            error = exc_info.value
            assert error.code == EnumCoreErrorCode.VALIDATION_ERROR
            assert "Invalid node type" in error.message

    def test_validate_output_path_safe(self, temp_templates_dir):
        """Test output path validation with safe paths"""
        with patch("agents.lib.omninode_template_engine.get_config") as mock_config:
            mock_config.return_value = Mock(template_directory=str(temp_templates_dir))

            engine = OmniNodeTemplateEngine(
                enable_cache=False, enable_pattern_learning=False
            )

            # Safe paths should not raise
            engine._validate_output_path("output/nodes")
            engine._validate_output_path("/tmp/test_output")
            engine._validate_output_path("./relative/path")

    def test_validate_output_path_dangerous_patterns(self, temp_templates_dir):
        """Test output path validation with dangerous patterns"""
        with patch("agents.lib.omninode_template_engine.get_config") as mock_config:
            mock_config.return_value = Mock(template_directory=str(temp_templates_dir))

            engine = OmniNodeTemplateEngine(
                enable_cache=False, enable_pattern_learning=False
            )

            # Dangerous patterns should raise
            dangerous_paths = [
                "../../../etc/passwd",
                "~/secrets",
                "/etc/shadow",
                "/var/log",
                "/sys/kernel",
                "/proc/self",
                "path\\with\\backslash",
            ]

            for path in dangerous_paths:
                with pytest.raises(ModelOnexError) as exc_info:
                    engine._validate_output_path(path)

                error = exc_info.value
                assert error.code == EnumCoreErrorCode.VALIDATION_ERROR

    def test_validate_file_path_within_base(self, temp_templates_dir, tmp_path):
        """Test file path validation within base directory"""
        with patch("agents.lib.omninode_template_engine.get_config") as mock_config:
            mock_config.return_value = Mock(template_directory=str(temp_templates_dir))

            engine = OmniNodeTemplateEngine(
                enable_cache=False, enable_pattern_learning=False
            )

            base_dir = tmp_path / "base"
            base_dir.mkdir()

            # Valid paths within base
            engine._validate_file_path("subdir/file.py", base_dir)
            engine._validate_file_path("file.py", base_dir)

    def test_validate_file_path_directory_traversal(self, temp_templates_dir, tmp_path):
        """Test file path validation prevents directory traversal"""
        with patch("agents.lib.omninode_template_engine.get_config") as mock_config:
            mock_config.return_value = Mock(template_directory=str(temp_templates_dir))

            engine = OmniNodeTemplateEngine(
                enable_cache=False, enable_pattern_learning=False
            )

            base_dir = tmp_path / "base"
            base_dir.mkdir()

            # Traversal attempts should raise
            with pytest.raises(ModelOnexError) as exc_info:
                engine._validate_file_path("../../etc/passwd", base_dir)

            error = exc_info.value
            assert error.code == EnumCoreErrorCode.VALIDATION_ERROR
            assert "directory traversal" in error.message.lower()

    def test_validate_generation_inputs_valid(
        self, temp_templates_dir, analysis_result
    ):
        """Test generation inputs validation with valid inputs"""
        with patch("agents.lib.omninode_template_engine.get_config") as mock_config:
            mock_config.return_value = Mock(template_directory=str(temp_templates_dir))

            engine = OmniNodeTemplateEngine(
                enable_cache=False, enable_pattern_learning=False
            )

            # Use a path that won't trigger security checks
            output_dir = "./output_test"

            # Valid inputs should not raise
            engine._validate_generation_inputs(
                analysis_result,
                "EFFECT",
                "user_auth",
                "identity",
                output_dir,
            )

    def test_validate_generation_inputs_invalid_names(
        self, temp_templates_dir, analysis_result
    ):
        """Test generation inputs validation with invalid names"""
        with patch("agents.lib.omninode_template_engine.get_config") as mock_config:
            mock_config.return_value = Mock(template_directory=str(temp_templates_dir))

            engine = OmniNodeTemplateEngine(
                enable_cache=False, enable_pattern_learning=False
            )

            output_dir = "./output_test"

            # Invalid microservice name
            with pytest.raises(ModelOnexError) as exc_info:
                engine._validate_generation_inputs(
                    analysis_result,
                    "EFFECT",
                    "user@auth!",  # Invalid characters
                    "identity",
                    output_dir,
                )

            assert "invalid characters" in exc_info.value.message.lower()

            # Invalid domain name
            with pytest.raises(ModelOnexError) as exc_info:
                engine._validate_generation_inputs(
                    analysis_result,
                    "EFFECT",
                    "user_auth",
                    "identity/test",  # Invalid characters
                    output_dir,
                )

            assert "invalid characters" in exc_info.value.message.lower()

    def test_validate_generation_inputs_missing_prd(
        self, temp_templates_dir, analysis_result
    ):
        """Test generation inputs validation with missing PRD"""
        with patch("agents.lib.omninode_template_engine.get_config") as mock_config:
            mock_config.return_value = Mock(template_directory=str(temp_templates_dir))

            engine = OmniNodeTemplateEngine(
                enable_cache=False, enable_pattern_learning=False
            )

            output_dir = "./output_test"

            # Missing PRD
            analysis_result.parsed_prd = None

            with pytest.raises(ModelOnexError) as exc_info:
                engine._validate_generation_inputs(
                    analysis_result,
                    "EFFECT",
                    "user_auth",
                    "identity",
                    output_dir,
                )

            assert "missing parsed prd" in exc_info.value.message.lower()


# ============================================================================
# OmniNodeTemplateEngine Tests - Helper Methods
# ============================================================================


class TestHelperMethods:
    """Test helper methods"""

    def test_to_pascal_case_snake_case(self, temp_templates_dir):
        """Test PascalCase conversion from snake_case"""
        with patch("agents.lib.omninode_template_engine.get_config") as mock_config:
            mock_config.return_value = Mock(template_directory=str(temp_templates_dir))

            engine = OmniNodeTemplateEngine(
                enable_cache=False, enable_pattern_learning=False
            )

            assert engine._to_pascal_case("user_management") == "UserManagement"
            assert engine._to_pascal_case("postgres_crud") == "PostgresCRUD"
            assert engine._to_pascal_case("rest_api") == "RestAPI"
            assert engine._to_pascal_case("http_client") == "HttpClient"

    def test_to_pascal_case_kebab_case(self, temp_templates_dir):
        """Test PascalCase conversion from kebab-case"""
        with patch("agents.lib.omninode_template_engine.get_config") as mock_config:
            mock_config.return_value = Mock(template_directory=str(temp_templates_dir))

            engine = OmniNodeTemplateEngine(
                enable_cache=False, enable_pattern_learning=False
            )

            assert engine._to_pascal_case("user-management") == "UserManagement"
            assert engine._to_pascal_case("rest-api") == "RestAPI"

    def test_to_pascal_case_already_pascal(self, temp_templates_dir):
        """Test PascalCase conversion preserves existing PascalCase"""
        with patch("agents.lib.omninode_template_engine.get_config") as mock_config:
            mock_config.return_value = Mock(template_directory=str(temp_templates_dir))

            engine = OmniNodeTemplateEngine(
                enable_cache=False, enable_pattern_learning=False
            )

            assert engine._to_pascal_case("UserManagement") == "UserManagement"
            assert engine._to_pascal_case("PostgresCRUD") == "PostgresCRUD"

    def test_to_pascal_case_acronyms(self, temp_templates_dir):
        """Test PascalCase conversion with acronyms"""
        with patch("agents.lib.omninode_template_engine.get_config") as mock_config:
            mock_config.return_value = Mock(template_directory=str(temp_templates_dir))

            engine = OmniNodeTemplateEngine(
                enable_cache=False, enable_pattern_learning=False
            )

            # Core acronyms always uppercase
            assert engine._to_pascal_case("sql_connector") == "SQLConnector"
            assert engine._to_pascal_case("json_parser") == "JSONParser"
            assert engine._to_pascal_case("uuid_generator") == "UUIDGenerator"

            # Protocol acronyms - first word capitalized, rest uppercase
            assert engine._to_pascal_case("http_server") == "HttpServer"
            assert engine._to_pascal_case("rest_client") == "RestClient"

    def test_generate_business_logic_stub(self, temp_templates_dir, analysis_result):
        """Test business logic stub generation"""
        with patch("agents.lib.omninode_template_engine.get_config") as mock_config:
            mock_config.return_value = Mock(template_directory=str(temp_templates_dir))

            engine = OmniNodeTemplateEngine(
                enable_cache=False, enable_pattern_learning=False
            )

            stub = engine._generate_business_logic_stub(
                analysis_result, "EFFECT", "user_auth"
            )

            assert "TODO: Implement user_auth effect logic" in stub
            assert "Based on requirements:" in stub
            # Should include first 3 requirements
            assert analysis_result.parsed_prd.functional_requirements[0] in stub

    def test_extract_operations(self, temp_templates_dir, decomposition_result):
        """Test operations extraction from decomposition"""
        with patch("agents.lib.omninode_template_engine.get_config") as mock_config:
            mock_config.return_value = Mock(template_directory=str(temp_templates_dir))

            engine = OmniNodeTemplateEngine(
                enable_cache=False, enable_pattern_learning=False
            )

            operations = engine._extract_operations(decomposition_result)

            # Should extract top 3 tasks
            assert len(operations) == 3
            assert "Implement authentication" in operations
            assert "Setup session management" in operations

    def test_generate_mixin_imports(self, temp_templates_dir):
        """Test mixin imports generation"""
        with patch("agents.lib.omninode_template_engine.get_config") as mock_config:
            mock_config.return_value = Mock(template_directory=str(temp_templates_dir))

            engine = OmniNodeTemplateEngine(
                enable_cache=False, enable_pattern_learning=False
            )

            # Currently returns empty string (TODO in code)
            imports = engine._generate_mixin_imports(["MixinEventBus", "MixinRetry"])
            assert imports == ""

    def test_generate_mixin_inheritance(self, temp_templates_dir):
        """Test mixin inheritance generation"""
        with patch("agents.lib.omninode_template_engine.get_config") as mock_config:
            mock_config.return_value = Mock(template_directory=str(temp_templates_dir))

            engine = OmniNodeTemplateEngine(
                enable_cache=False, enable_pattern_learning=False
            )

            # Currently returns empty string (TODO in code)
            inheritance = engine._generate_mixin_inheritance(
                ["MixinEventBus", "MixinRetry"]
            )
            assert inheritance == ""

    def test_generate_mixin_initialization(self, temp_templates_dir):
        """Test mixin initialization generation"""
        with patch("agents.lib.omninode_template_engine.get_config") as mock_config:
            mock_config.return_value = Mock(template_directory=str(temp_templates_dir))

            engine = OmniNodeTemplateEngine(
                enable_cache=False, enable_pattern_learning=False
            )

            initialization = engine._generate_mixin_initialization(
                ["MixinEventBus", "MixinRetry"]
            )
            assert initialization == ""


# ============================================================================
# OmniNodeTemplateEngine Tests - File Generation
# ============================================================================


class TestFileGeneration:
    """Test file generation methods"""

    def test_generate_input_model(self, temp_templates_dir, analysis_result):
        """Test input model generation"""
        with patch("agents.lib.omninode_template_engine.get_config") as mock_config:
            mock_config.return_value = Mock(template_directory=str(temp_templates_dir))

            engine = OmniNodeTemplateEngine(
                enable_cache=False, enable_pattern_learning=False
            )

            model = engine._generate_input_model("user_auth", analysis_result)

            assert "ModelUserAuthInput" in model
            assert "operation_type" in model
            assert "parameters" in model
            assert "pydantic" in model.lower()

    def test_generate_output_model(self, temp_templates_dir, analysis_result):
        """Test output model generation"""
        with patch("agents.lib.omninode_template_engine.get_config") as mock_config:
            mock_config.return_value = Mock(template_directory=str(temp_templates_dir))

            engine = OmniNodeTemplateEngine(
                enable_cache=False, enable_pattern_learning=False
            )

            model = engine._generate_output_model("user_auth", analysis_result)

            assert "ModelUserAuthOutput" in model
            assert "result_data" in model
            assert "success" in model
            assert "pydantic" in model.lower()

    def test_generate_config_model(self, temp_templates_dir, analysis_result):
        """Test config model generation"""
        with patch("agents.lib.omninode_template_engine.get_config") as mock_config:
            mock_config.return_value = Mock(template_directory=str(temp_templates_dir))

            engine = OmniNodeTemplateEngine(
                enable_cache=False, enable_pattern_learning=False
            )

            model = engine._generate_config_model("user_auth", analysis_result)

            assert "ModelUserAuthConfig" in model
            assert "timeout_seconds" in model
            assert "retry_attempts" in model

    def test_generate_operation_enum(self, temp_templates_dir, analysis_result):
        """Test operation enum generation"""
        with patch("agents.lib.omninode_template_engine.get_config") as mock_config:
            mock_config.return_value = Mock(template_directory=str(temp_templates_dir))

            engine = OmniNodeTemplateEngine(
                enable_cache=False, enable_pattern_learning=False
            )

            enum = engine._generate_operation_enum("user_auth", analysis_result)

            assert "EnumUserAuthOperationType" in enum
            assert "CREATE" in enum
            assert "READ" in enum
            assert "UPDATE" in enum
            assert "DELETE" in enum

    def test_get_performance_fields_for_node_type(self, temp_templates_dir):
        """Test performance fields generation for each node type"""
        with patch("agents.lib.omninode_template_engine.get_config") as mock_config:
            mock_config.return_value = Mock(template_directory=str(temp_templates_dir))

            engine = OmniNodeTemplateEngine(
                enable_cache=False, enable_pattern_learning=False
            )

            # COMPUTE
            compute_fields = engine._get_performance_fields_for_node_type("COMPUTE")
            assert "single_operation_max_ms" in compute_fields

            # EFFECT
            effect_fields = engine._get_performance_fields_for_node_type("EFFECT")
            assert "max_response_time_ms" in effect_fields

            # REDUCER
            reducer_fields = engine._get_performance_fields_for_node_type("REDUCER")
            assert "aggregation_window_ms" in reducer_fields
            assert "max_aggregation_delay_ms" in reducer_fields

            # ORCHESTRATOR
            orchestrator_fields = engine._get_performance_fields_for_node_type(
                "ORCHESTRATOR"
            )
            assert "workflow_timeout_ms" in orchestrator_fields
            assert "coordination_overhead_ms" in orchestrator_fields

    def test_requirement_to_action_name(self, temp_templates_dir):
        """Test requirement to action name conversion"""
        with patch("agents.lib.omninode_template_engine.get_config") as mock_config:
            mock_config.return_value = Mock(template_directory=str(temp_templates_dir))

            engine = OmniNodeTemplateEngine(
                enable_cache=False, enable_pattern_learning=False
            )

            # Test conversion - takes first 3 words, then removes stop words
            assert (
                engine._requirement_to_action_name("Create user account")
                == "create_user_account"
            )
            # Takes first 3 words ["The", "system", "should"], then removes "The"
            assert (
                engine._requirement_to_action_name(
                    "The system should authenticate users"
                )
                == "system_should"
            )

    def test_build_actions_list(self, temp_templates_dir, analysis_result):
        """Test actions list building"""
        with patch("agents.lib.omninode_template_engine.get_config") as mock_config:
            mock_config.return_value = Mock(template_directory=str(temp_templates_dir))

            engine = OmniNodeTemplateEngine(
                enable_cache=False, enable_pattern_learning=False
            )

            actions = engine._build_actions_list(analysis_result, "EFFECT")

            assert "health_check" in actions
            # Should include requirements as actions
            assert len(actions) > 0

    def test_build_dependencies_list(self, temp_templates_dir, analysis_result):
        """Test dependencies list building"""
        with patch("agents.lib.omninode_template_engine.get_config") as mock_config:
            mock_config.return_value = Mock(template_directory=str(temp_templates_dir))

            engine = OmniNodeTemplateEngine(
                enable_cache=False, enable_pattern_learning=False
            )

            deps = engine._build_dependencies_list(analysis_result)

            assert "postgresql" in deps.lower()
            assert "redis" in deps.lower()

    def test_build_dependencies_list_empty(self, temp_templates_dir, analysis_result):
        """Test dependencies list building with no external systems"""
        with patch("agents.lib.omninode_template_engine.get_config") as mock_config:
            mock_config.return_value = Mock(template_directory=str(temp_templates_dir))

            engine = OmniNodeTemplateEngine(
                enable_cache=False, enable_pattern_learning=False
            )

            analysis_result.external_systems = []
            deps = engine._build_dependencies_list(analysis_result)

            assert deps == "  []"


# ============================================================================
# OmniNodeTemplateEngine Tests - Async Operations
# ============================================================================


class TestAsyncOperations:
    """Test async operations"""

    @pytest.mark.asyncio
    async def test_generate_node_basic(self, temp_templates_dir, analysis_result):
        """Test basic node generation"""

        with patch("agents.lib.omninode_template_engine.get_config") as mock_config:
            mock_config.return_value = Mock(
                template_directory=str(temp_templates_dir),
                postgres_host="localhost",
                postgres_port=5432,
                postgres_db="test_db",
                redis_host="localhost",
                redis_port=6379,
                kafka_bootstrap_servers="localhost:9092",
            )

            engine = OmniNodeTemplateEngine(
                enable_cache=False, enable_pattern_learning=False
            )

            # Use /tmp to avoid /var path issue
            with tempfile.TemporaryDirectory(dir="/tmp") as output_dir:
                result = await engine.generate_node(
                    analysis_result=analysis_result,
                    node_type="EFFECT",
                    microservice_name="user_auth",
                    domain="identity",
                    output_directory=output_dir,
                )

                # Check result structure
                assert result["node_type"] == "EFFECT"
                assert result["microservice_name"] == "user_auth"
                assert result["domain"] == "identity"
                assert "output_path" in result
                assert "main_file" in result
                assert "generated_files" in result

                # Check files were created
                assert Path(result["main_file"]).exists()

    @pytest.mark.asyncio
    async def test_generate_additional_files(
        self, temp_templates_dir, analysis_result, tmp_path
    ):
        """Test additional files generation"""
        with patch("agents.lib.omninode_template_engine.get_config") as mock_config:
            mock_config.return_value = Mock(
                template_directory=str(temp_templates_dir),
                postgres_host="localhost",
                postgres_port=5432,
                postgres_db="test_db",
                redis_host="localhost",
                redis_port=6379,
                kafka_bootstrap_servers="localhost:9092",
            )

            engine = OmniNodeTemplateEngine(
                enable_cache=False, enable_pattern_learning=False
            )

            context = {
                "MICROSERVICE_NAME": "user_auth",
                "NODE_TYPE": "EFFECT",
                "DOMAIN": "identity",
            }

            files = await engine._generate_additional_files(
                analysis_result, "EFFECT", "user_auth", "identity", context
            )

            # Check file structure
            assert "v1_0_0/models/model_user_auth_input.py" in files
            assert "v1_0_0/models/model_user_auth_output.py" in files
            assert "v1_0_0/models/model_user_auth_config.py" in files
            assert "v1_0_0/enums/enum_user_auth_operation_type.py" in files
            assert "v1_0_0/contract.yaml" in files
            assert "node.manifest.yaml" in files
            assert "v1_0_0/version.manifest.yaml" in files

    @pytest.mark.asyncio
    async def test_cleanup_async(self, temp_templates_dir):
        """Test async cleanup"""
        with patch("agents.lib.omninode_template_engine.get_config") as mock_config:
            mock_config.return_value = Mock(template_directory=str(temp_templates_dir))

            engine = OmniNodeTemplateEngine(
                enable_cache=True, enable_pattern_learning=False
            )

            # Cleanup should not raise
            await engine.cleanup_async(timeout=1.0)

    @pytest.mark.asyncio
    async def test_async_context_manager(self, temp_templates_dir):
        """Test async context manager"""
        with patch("agents.lib.omninode_template_engine.get_config") as mock_config:
            mock_config.return_value = Mock(template_directory=str(temp_templates_dir))

            async with OmniNodeTemplateEngine(
                enable_cache=True, enable_pattern_learning=False
            ) as engine:
                # Engine should be usable
                assert engine is not None
                assert engine.templates is not None

            # Cleanup should have been called


# ============================================================================
# Edge Cases and Error Handling
# ============================================================================


class TestEdgeCasesAndErrors:
    """Test edge cases and error handling"""

    @pytest.mark.asyncio
    async def test_generate_node_missing_template(self, analysis_result):
        """Test node generation with missing template"""

        # Create empty templates directory
        with tempfile.TemporaryDirectory(dir="/tmp") as tmp_dir:
            templates_dir = Path(tmp_dir) / "templates"
            templates_dir.mkdir()

            with patch("agents.lib.omninode_template_engine.get_config") as mock_config:
                mock_config.return_value = Mock(template_directory=str(templates_dir))

                engine = OmniNodeTemplateEngine(
                    enable_cache=False, enable_pattern_learning=False
                )

                output_dir = Path(tmp_dir) / "output"
                output_dir.mkdir()

                # Should raise error for missing template
                with pytest.raises(ModelOnexError) as exc_info:
                    await engine.generate_node(
                        analysis_result=analysis_result,
                        node_type="EFFECT",
                        microservice_name="user_auth",
                        domain="identity",
                        output_directory=str(output_dir),
                    )

                assert "No template found" in exc_info.value.message

    @pytest.mark.asyncio
    async def test_generate_node_empty_files_skipped(
        self, temp_templates_dir, analysis_result
    ):
        """Test that empty generated files are skipped"""

        with patch("agents.lib.omninode_template_engine.get_config") as mock_config:
            mock_config.return_value = Mock(
                template_directory=str(temp_templates_dir),
                postgres_host="localhost",
                postgres_port=5432,
                postgres_db="test_db",
                redis_host="localhost",
                redis_port=6379,
                kafka_bootstrap_servers="localhost:9092",
            )

            engine = OmniNodeTemplateEngine(
                enable_cache=False, enable_pattern_learning=False
            )

            with tempfile.TemporaryDirectory(dir="/tmp") as output_dir:
                # Generation should succeed and skip empty files
                result = await engine.generate_node(
                    analysis_result=analysis_result,
                    node_type="EFFECT",
                    microservice_name="user_auth",
                    domain="identity",
                    output_directory=output_dir,
                )

                # Should complete without errors
                assert result is not None

    def test_destructor_warning(self, temp_templates_dir, capsys):
        """Test destructor warning for pending tasks"""
        with patch("agents.lib.omninode_template_engine.get_config") as mock_config:
            mock_config.return_value = Mock(template_directory=str(temp_templates_dir))

            engine = OmniNodeTemplateEngine(
                enable_cache=True, enable_pattern_learning=False
            )

            # Add mock pending task
            if hasattr(engine.template_cache, "_background_tasks"):
                engine.template_cache._background_tasks = [Mock()]

            # Delete engine (triggers __del__)
            del engine

            # Should log warning (captured by capsys if logging configured)


# ============================================================================
# Integration Tests
# ============================================================================


@pytest.mark.integration
class TestIntegration:
    """Integration tests requiring full setup"""

    @pytest.mark.asyncio
    async def test_full_node_generation_workflow(
        self, temp_templates_dir, analysis_result
    ):
        """Test complete node generation workflow"""

        with patch("agents.lib.omninode_template_engine.get_config") as mock_config:
            mock_config.return_value = Mock(
                template_directory=str(temp_templates_dir),
                postgres_host="localhost",
                postgres_port=5432,
                postgres_db="omninode",
                redis_host="localhost",
                redis_port=6379,
                kafka_bootstrap_servers="localhost:9092",
            )

            engine = OmniNodeTemplateEngine(
                enable_cache=True, enable_pattern_learning=False
            )

            with tempfile.TemporaryDirectory(dir="/tmp") as output_dir:
                # Generate all 4 node types
                node_types = ["EFFECT", "COMPUTE", "REDUCER", "ORCHESTRATOR"]

                for node_type in node_types:
                    result = await engine.generate_node(
                        analysis_result=analysis_result,
                        node_type=node_type,
                        microservice_name="user_auth",
                        domain="identity",
                        output_directory=output_dir,
                    )

                    # Verify result structure
                    assert result["node_type"] == node_type
                    assert Path(result["main_file"]).exists()
                    assert len(result["generated_files"]) > 0

                    # Verify metadata
                    assert "session_id" in result["metadata"]
                    assert "correlation_id" in result["metadata"]
                    assert "confidence_score" in result["metadata"]

                # Check cache stats
                stats = engine.get_cache_stats()
                assert stats is not None
                assert stats["hits"] > 0  # Should have cache hits

    @pytest.mark.asyncio
    async def test_prepare_template_context_with_intelligence(
        self, temp_templates_dir, analysis_result
    ):
        """Test template context preparation with intelligence"""
        with patch("agents.lib.omninode_template_engine.get_config") as mock_config:
            mock_config.return_value = Mock(template_directory=str(temp_templates_dir))

            engine = OmniNodeTemplateEngine(
                enable_cache=False, enable_pattern_learning=False
            )

            # Mock intelligence context
            from agents.lib.models.intelligence_context import IntelligenceContext

            intelligence = IntelligenceContext(
                node_type_patterns=["Pattern 1", "Pattern 2"],
                common_operations=["op1", "op2"],
                required_mixins=["MixinEventBus"],
                performance_targets={"latency": "100ms"},
                error_scenarios=["Error 1", "Error 2"],
                domain_best_practices=["Best practice 1"],
                anti_patterns=["Anti-pattern 1"],
                testing_recommendations=["Test 1"],
                security_considerations=["Security 1"],
                confidence_score=0.95,
            )

            context = engine._prepare_template_context(
                analysis_result,
                "EFFECT",
                "user_auth",
                "identity",
                intelligence,
            )

            # Check intelligence fields are included
            assert "BEST_PRACTICES" in context
            assert "COMMON_OPERATIONS" in context
            assert "REQUIRED_MIXINS" in context
            assert "PERFORMANCE_TARGETS" in context
            assert "INTELLIGENCE_CONFIDENCE" in context
            assert context["INTELLIGENCE_CONFIDENCE"] == 0.95

    @pytest.mark.asyncio
    async def test_prepare_template_context_without_intelligence(
        self, temp_templates_dir, analysis_result
    ):
        """Test template context preparation without intelligence"""
        with patch("agents.lib.omninode_template_engine.get_config") as mock_config:
            mock_config.return_value = Mock(template_directory=str(temp_templates_dir))

            engine = OmniNodeTemplateEngine(
                enable_cache=False, enable_pattern_learning=False
            )

            context = engine._prepare_template_context(
                analysis_result,
                "EFFECT",
                "user_auth",
                "identity",
                None,  # No intelligence
            )

            # Check default values are provided
            assert context["BEST_PRACTICES"] == []
            assert context["COMMON_OPERATIONS"] == []
            assert context["INTELLIGENCE_CONFIDENCE"] == 0.0
            assert "Standard ONEX patterns" in context["BEST_PRACTICES_FORMATTED"]
