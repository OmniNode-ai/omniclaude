#!/usr/bin/env python3
"""
Test OmniNode Template Engine
"""

import tempfile
from pathlib import Path

import pytest

from agents.lib.omninode_template_engine import OmniNodeTemplateEngine
from agents.lib.simple_prd_analyzer import (
    DecompositionResult,
    ParsedPRD,
    PRDAnalysisResult,
)


class TestOmniNodeTemplateEngine:
    """Test the OmniNode template engine"""

    def test_template_loading(self):
        """Test that templates are loaded correctly"""
        engine = OmniNodeTemplateEngine()

        # Check that all node types are loaded
        assert "EFFECT" in engine.templates
        assert "COMPUTE" in engine.templates
        assert "REDUCER" in engine.templates
        assert "ORCHESTRATOR" in engine.templates

        # Check template content
        effect_template = engine.templates["EFFECT"]
        assert "MICROSERVICE_NAME" in effect_template.placeholders
        assert "MICROSERVICE_NAME_PASCAL" in effect_template.placeholders
        assert "BUSINESS_DESCRIPTION" in effect_template.placeholders

    def test_template_rendering(self):
        """Test template rendering with context"""
        engine = OmniNodeTemplateEngine()
        effect_template = engine.templates["EFFECT"]

        context = {
            "MICROSERVICE_NAME": "user_management",
            "MICROSERVICE_NAME_PASCAL": "UserManagement",
            "DOMAIN": "identity",
            "DOMAIN_PASCAL": "Identity",
            "BUSINESS_DESCRIPTION": "User management service for identity operations",
            "MIXIN_IMPORTS": "",
            "MIXIN_INHERITANCE": "",
            "MIXIN_INITIALIZATION": "",
            "BUSINESS_LOGIC_STUB": "        # TODO: Implement user management logic",
            "OPERATIONS": ["create_user", "update_user", "delete_user"],
            "FEATURES": ["authentication", "authorization", "profile_management"],
            # Intelligence-driven placeholders (defaults)
            "BEST_PRACTICES_FORMATTED": "    - Standard ONEX patterns",
            "ERROR_SCENARIOS_FORMATTED": "    - Standard error handling",
            "PERFORMANCE_TARGETS_FORMATTED": "    - Standard performance requirements",
            "DOMAIN_PATTERNS_FORMATTED": "    - Standard domain patterns",
            "PATTERN_CODE_BLOCKS": "",
            "TESTING_SECTION": "        pass  # Add tests here",
            "SECURITY_SECTION": "        pass  # Add security validations here",
        }

        rendered = effect_template.render(context)

        # Check that placeholders are replaced
        assert "user_management" in rendered
        assert "UserManagement" in rendered
        assert "identity" in rendered
        assert "User management service for identity operations" in rendered
        assert "create_user" in rendered
        assert "authentication" in rendered

        # Check that no placeholders remain
        assert "{MICROSERVICE_NAME}" not in rendered
        assert "{DOMAIN}" not in rendered

    def test_context_preparation(self):
        """Test context preparation from analysis result"""
        engine = OmniNodeTemplateEngine()

        # Create mock analysis result
        parsed_prd = ParsedPRD(
            title="User Management Service",
            description="Test service for user operations",
            features=["authentication", "authorization"],
            functional_requirements=["Create users", "Update users", "Delete users"],
            success_criteria=["99.9% uptime", "Sub-second response"],
            technical_details=["High availability", "Security"],
            dependencies=["database", "auth_service"],
            extracted_keywords=["user", "management", "authentication"],
            sections=["overview", "requirements", "features"],
            word_count=150,
        )

        decomposition_result = DecompositionResult(
            tasks=[
                {
                    "title": "Create User",
                    "description": "Create new user account",
                    "priority": "high",
                    "complexity": "medium",
                    "dependencies": [],
                    "estimated_effort": 8,
                },
                {
                    "title": "Update User",
                    "description": "Update existing user",
                    "priority": "medium",
                    "complexity": "low",
                    "dependencies": ["Create User"],
                    "estimated_effort": 4,
                },
            ],
            total_tasks=2,
            verification_successful=True,
        )

        from datetime import datetime
        from uuid import uuid4

        analysis_result = PRDAnalysisResult(
            session_id=uuid4(),
            correlation_id=uuid4(),
            prd_content="Test PRD content",
            parsed_prd=parsed_prd,
            decomposition_result=decomposition_result,
            node_type_hints={"EFFECT": 0.8, "COMPUTE": 0.6},
            recommended_mixins=["MixinEventBus", "MixinCaching"],
            external_systems=["database", "auth_service"],
            quality_baseline=0.8,
            confidence_score=0.85,
            analysis_timestamp=datetime.utcnow(),
        )

        context = engine._prepare_template_context(
            analysis_result, "EFFECT", "user_management", "identity"
        )

        # Check basic context
        assert context["DOMAIN"] == "identity"
        assert context["MICROSERVICE_NAME"] == "user_management"
        assert context["MICROSERVICE_NAME_PASCAL"] == "UserManagement"
        assert context["DOMAIN_PASCAL"] == "Identity"
        assert context["NODE_TYPE"] == "EFFECT"
        assert context["BUSINESS_DESCRIPTION"] == "Test service for user operations"

        # Check mixin context - omnibase_core now supports mixins
        # MixinEventBus is available, MixinCaching is not (not in AVAILABLE_MIXINS)
        assert "MixinEventBus" in context["MIXIN_IMPORTS"]
        assert "MixinEventBus" in context["MIXIN_INHERITANCE"]

        # Check operations
        assert "Create User" in context["OPERATIONS"]
        assert "Update User" in context["OPERATIONS"]

        # Check features
        assert "authentication" in context["FEATURES"]
        assert "authorization" in context["FEATURES"]

    @pytest.mark.asyncio
    async def test_node_generation(self):
        """Test complete node generation"""
        engine = OmniNodeTemplateEngine()

        # Create mock analysis result
        parsed_prd = ParsedPRD(
            title="User Management Service",
            description="Test service for user operations",
            features=["authentication", "authorization"],
            functional_requirements=["Create users", "Update users"],
            success_criteria=["99.9% uptime"],
            technical_details=["High availability"],
            dependencies=["database"],
            extracted_keywords=["user", "management"],
            sections=["overview", "requirements"],
            word_count=100,
        )

        decomposition_result = DecompositionResult(
            tasks=[
                {
                    "title": "Create User",
                    "description": "Create new user account",
                    "priority": "high",
                    "complexity": "medium",
                    "dependencies": [],
                    "estimated_effort": 8,
                }
            ],
            total_tasks=1,
            verification_successful=True,
        )

        from datetime import datetime
        from uuid import uuid4

        analysis_result = PRDAnalysisResult(
            session_id=uuid4(),
            correlation_id=uuid4(),
            prd_content="Test PRD content",
            parsed_prd=parsed_prd,
            decomposition_result=decomposition_result,
            node_type_hints={"EFFECT": 0.8},
            recommended_mixins=["MixinEventBus"],
            external_systems=["database"],
            quality_baseline=0.8,
            confidence_score=0.85,
            analysis_timestamp=datetime.utcnow(),
        )

        # Create temporary directory for output
        with tempfile.TemporaryDirectory() as temp_dir:
            result = await engine.generate_node(
                analysis_result=analysis_result,
                node_type="EFFECT",
                microservice_name="user_management",
                domain="identity",
                output_directory=temp_dir,
            )

            # Check result structure
            assert result["node_type"] == "EFFECT"
            assert result["microservice_name"] == "user_management"
            assert result["domain"] == "identity"
            assert "output_path" in result
            assert "main_file" in result
            assert "generated_files" in result
            assert "metadata" in result

            # Check that files were created
            output_path = Path(result["output_path"])
            assert output_path.exists()

            main_file = Path(result["main_file"])
            assert main_file.exists()

            # Check main file content
            with open(main_file, "r") as f:
                content = f.read()
                assert "user_management" in content
                assert "UserManagement" in content
                assert "Test service for user operations" in content
                # Note: MixinEventBus not in content because mixins are disabled
                # until omnibase_core supports them

    def test_pascal_case_conversion(self):
        """Test PascalCase conversion"""
        engine = OmniNodeTemplateEngine()

        assert engine._to_pascal_case("user_management") == "UserManagement"
        assert engine._to_pascal_case("user-management") == "UserManagement"
        assert engine._to_pascal_case("user management") == "UserManagement"
        assert engine._to_pascal_case("user") == "User"

    def test_mixin_generation(self):
        """Test mixin-related code generation"""
        engine = OmniNodeTemplateEngine()

        mixins = ["MixinEventBus", "MixinCaching", "MixinHealthCheck"]

        # Test mixin imports - omnibase_core now supports mixins
        imports = engine._generate_mixin_imports(mixins)
        # MixinEventBus and MixinHealthCheck are available, MixinCaching is not
        assert "MixinEventBus" in imports
        assert "MixinHealthCheck" in imports
        assert "MixinCaching" not in imports  # Not in AVAILABLE_MIXINS

        # Test mixin inheritance - omnibase_core now supports mixins
        inheritance = engine._generate_mixin_inheritance(mixins)
        # Returns comma-prefixed string for class inheritance
        assert "MixinEventBus" in inheritance
        assert "MixinHealthCheck" in inheritance
        assert inheritance.startswith(", ")  # Should start with comma

        # Test mixin initialization (ONEX compliant - mixins handle their own init)
        initialization = engine._generate_mixin_initialization(mixins)
        # In ONEX architecture, mixins handle their own initialization via __init__
        # so the initialization code should be empty
        assert initialization == ""
