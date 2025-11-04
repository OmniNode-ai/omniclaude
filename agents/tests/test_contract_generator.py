#!/usr/bin/env python3
"""
Tests for Contract Generator

Tests YAML contract generation for all 4 node types, subcontract generation,
and validation logic.
"""

import shutil
import tempfile
from pathlib import Path
from uuid import uuid4

import pytest
import yaml

from agents.lib.contract_generator import ContractGenerator
from omnibase_core.errors import OnexError
from agents.lib.simple_prd_analyzer import (
    DecompositionResult,
    ParsedPRD,
    PRDAnalysisResult,
)


# Test fixtures
@pytest.fixture
def sample_prd_analysis():
    """Create a sample PRD analysis result"""
    parsed_prd = ParsedPRD(
        title="User Authentication Service",
        description="Service for authenticating users and managing sessions",
        functional_requirements=[
            "Must authenticate users with username and password",
            "Shall generate JWT tokens for authenticated users",
            "Required to validate existing JWT tokens",
            "Must handle password reset functionality",
        ],
        features=[
            "Multi-factor authentication support",
            "Session management and timeout",
            "OAuth integration for social login",
        ],
        success_criteria=[
            "Authentication response time < 200ms",
            "Support 1000 concurrent users",
            "99.9% uptime",
        ],
        technical_details=[
            "Use PostgreSQL for user data storage",
            "Use Redis for session caching",
            "JWT tokens with HS256 algorithm",
        ],
        dependencies=[
            "PostgreSQL database",
            "Redis cache",
            "Email service for password reset",
        ],
        extracted_keywords=["Authentication", "Security", "Session", "Token"],
        sections=["Overview", "Requirements", "Features"],
        word_count=250,
    )

    decomposition_result = DecompositionResult(
        tasks=[
            {
                "id": "task_1",
                "title": "Implement user authentication endpoint",
                "description": "Create API endpoint for user login",
                "priority": "high",
                "complexity": "medium",
            },
            {
                "id": "task_2",
                "title": "Implement JWT token generation",
                "description": "Generate and sign JWT tokens",
                "priority": "high",
                "complexity": "medium",
            },
            {
                "id": "task_3",
                "title": "Implement token validation",
                "description": "Validate and decode JWT tokens",
                "priority": "high",
                "complexity": "low",
            },
        ],
        total_tasks=3,
        verification_successful=True,
    )

    return PRDAnalysisResult(
        session_id=uuid4(),
        correlation_id=uuid4(),
        prd_content="Sample PRD content",
        parsed_prd=parsed_prd,
        decomposition_result=decomposition_result,
        node_type_hints={
            "EFFECT": 0.8,
            "COMPUTE": 0.3,
            "REDUCER": 0.1,
            "ORCHESTRATOR": 0.2,
        },
        recommended_mixins=[
            "MixinEventBus",
            "MixinCaching",
            "MixinHealthCheck",
            "MixinSecurity",
            "MixinValidation",
        ],
        external_systems=["PostgreSQL", "Redis", "Email Service"],
        quality_baseline=0.85,
        confidence_score=0.78,
    )


@pytest.fixture
def contract_generator():
    """Create a ContractGenerator instance"""
    return ContractGenerator()


@pytest.fixture
def temp_output_dir():
    """Create a temporary directory for output files"""
    temp_dir = tempfile.mkdtemp()
    yield temp_dir
    shutil.rmtree(temp_dir)


# Test YAML generation for all node types
@pytest.mark.asyncio
async def test_generate_effect_contract(
    contract_generator, sample_prd_analysis, temp_output_dir
):
    """Test EFFECT node contract generation"""
    result = await contract_generator.generate_contract_yaml(
        analysis_result=sample_prd_analysis,
        node_type="EFFECT",
        microservice_name="user_authentication",
        domain="auth",
        output_directory=temp_output_dir,
    )

    # Verify result structure
    assert "contract" in result
    assert "contract_yaml" in result
    assert "validation_result" in result
    assert result["validation_result"]["valid"] is True

    # Verify contract structure
    contract = result["contract"]
    assert contract["version"] == "1.0.0"
    assert contract["node_type"] == "EFFECT"
    assert contract["domain"] == "auth"
    assert contract["service_name"] == "user_authentication"
    assert "capabilities" in contract
    assert "subcontracts" in contract
    assert "dependencies" in contract

    # Verify YAML is valid
    parsed_yaml = yaml.safe_load(result["contract_yaml"])
    assert parsed_yaml["node_type"] == "EFFECT"

    # Verify file was written
    contract_file = Path(temp_output_dir) / "contract_user_authentication.yaml"
    assert contract_file.exists()


@pytest.mark.asyncio
async def test_generate_compute_contract(contract_generator, sample_prd_analysis):
    """Test COMPUTE node contract generation"""
    result = await contract_generator.generate_contract_yaml(
        analysis_result=sample_prd_analysis,
        node_type="COMPUTE",
        microservice_name="data_processor",
        domain="processing",
    )

    contract = result["contract"]
    assert contract["node_type"] == "COMPUTE"
    assert contract["service_name"] == "data_processor"
    assert contract["domain"] == "processing"

    # Verify COMPUTE-specific capabilities
    capabilities = contract["capabilities"]
    capability_names = [cap["name"] for cap in capabilities]
    assert "data_transformation" in capability_names


@pytest.mark.asyncio
async def test_generate_reducer_contract(contract_generator, sample_prd_analysis):
    """Test REDUCER node contract generation"""
    result = await contract_generator.generate_contract_yaml(
        analysis_result=sample_prd_analysis,
        node_type="REDUCER",
        microservice_name="data_aggregator",
        domain="analytics",
    )

    contract = result["contract"]
    assert contract["node_type"] == "REDUCER"
    assert contract["service_name"] == "data_aggregator"

    # Verify REDUCER-specific capabilities
    capabilities = contract["capabilities"]
    capability_names = [cap["name"] for cap in capabilities]
    assert "data_aggregation" in capability_names


@pytest.mark.asyncio
async def test_generate_orchestrator_contract(contract_generator, sample_prd_analysis):
    """Test ORCHESTRATOR node contract generation"""
    result = await contract_generator.generate_contract_yaml(
        analysis_result=sample_prd_analysis,
        node_type="ORCHESTRATOR",
        microservice_name="workflow_manager",
        domain="coordination",
    )

    contract = result["contract"]
    assert contract["node_type"] == "ORCHESTRATOR"
    assert contract["service_name"] == "workflow_manager"

    # Verify ORCHESTRATOR-specific capabilities
    capabilities = contract["capabilities"]
    capability_names = [cap["name"] for cap in capabilities]
    assert "workflow_coordination" in capability_names


# Test subcontract generation
@pytest.mark.asyncio
async def test_generate_subcontracts(contract_generator):
    """Test subcontract generation for mixins"""
    recommended_mixins = ["MixinEventBus", "MixinCaching", "MixinHealthCheck"]
    contract_fields = {
        "capabilities": [{"name": "test_capability", "type": "operation"}],
        "operations": [],
        "external_systems": [],
    }

    subcontracts = await contract_generator.generate_subcontracts(
        recommended_mixins=recommended_mixins, contract_fields=contract_fields
    )

    assert len(subcontracts) == 3

    # Verify EventBus subcontract
    event_bus_subcontract = next(
        (sc for sc in subcontracts if sc["mixin"] == "MixinEventBus"), None
    )
    assert event_bus_subcontract is not None
    assert "config" in event_bus_subcontract
    assert "bootstrap_servers" in event_bus_subcontract["config"]
    assert event_bus_subcontract["required"] is True

    # Verify Caching subcontract
    caching_subcontract = next(
        (sc for sc in subcontracts if sc["mixin"] == "MixinCaching"), None
    )
    assert caching_subcontract is not None
    assert "config" in caching_subcontract
    assert "ttl_seconds" in caching_subcontract["config"]


@pytest.mark.asyncio
async def test_generate_subcontracts_unknown_mixin(contract_generator):
    """Test subcontract generation with unknown mixin"""
    recommended_mixins = ["UnknownMixin"]
    contract_fields = {"capabilities": [], "operations": [], "external_systems": []}

    subcontracts = await contract_generator.generate_subcontracts(
        recommended_mixins=recommended_mixins, contract_fields=contract_fields
    )

    assert len(subcontracts) == 1
    assert subcontracts[0]["mixin"] == "UnknownMixin"
    assert subcontracts[0]["config"] == {}


# Test field inference
@pytest.mark.asyncio
async def test_infer_contract_fields(contract_generator, sample_prd_analysis):
    """Test contract field inference from PRD analysis"""
    contract_fields = await contract_generator.infer_contract_fields(
        analysis_result=sample_prd_analysis, node_type="EFFECT"
    )

    assert "capabilities" in contract_fields
    assert "operations" in contract_fields
    assert "external_systems" in contract_fields

    # Verify capabilities were extracted from requirements
    capabilities = contract_fields["capabilities"]
    assert len(capabilities) > 0

    # Check for required capability
    required_caps = [cap for cap in capabilities if cap["required"]]
    assert len(required_caps) > 0

    # Verify external systems
    assert contract_fields["external_systems"] == [
        "PostgreSQL",
        "Redis",
        "Email Service",
    ]


@pytest.mark.asyncio
async def test_capability_type_inference(contract_generator):
    """Test capability type inference from requirement text"""
    # Test create operation
    create_type = contract_generator._infer_capability_type(
        "Create new user account", "EFFECT"
    )
    assert create_type == "create"

    # Test read operation
    read_type = contract_generator._infer_capability_type(
        "Fetch user profile data", "EFFECT"
    )
    assert read_type == "read"

    # Test update operation
    update_type = contract_generator._infer_capability_type(
        "Update user settings", "EFFECT"
    )
    assert update_type == "update"

    # Test delete operation
    delete_type = contract_generator._infer_capability_type(
        "Delete inactive accounts", "EFFECT"
    )
    assert delete_type == "delete"

    # Test compute operation
    compute_type = contract_generator._infer_capability_type(
        "Process payment transactions", "COMPUTE"
    )
    assert compute_type == "compute"


# Test validation logic
@pytest.mark.asyncio
async def test_validate_valid_contract(contract_generator):
    """Test validation of a valid contract"""
    contract = {
        "version": "1.0.0",
        "node_type": "EFFECT",
        "domain": "test",
        "service_name": "test_service",
        "capabilities": [
            {"name": "test_capability", "type": "operation", "required": True}
        ],
        "subcontracts": [{"mixin": "MixinEventBus", "config": {}}],
        "dependencies": {"external_systems": [], "required_mixins": ["MixinEventBus"]},
    }

    validation_result = await contract_generator.validate_contract(contract)

    assert validation_result["valid"] is True
    assert len(validation_result["issues"]) == 0


@pytest.mark.asyncio
async def test_validate_missing_required_fields(contract_generator):
    """Test validation with missing required fields"""
    contract = {
        "version": "1.0.0",
        "node_type": "EFFECT",
        # Missing: domain, service_name, capabilities, dependencies
    }

    validation_result = await contract_generator.validate_contract(contract)

    assert validation_result["valid"] is False
    assert len(validation_result["issues"]) > 0
    assert any("domain" in issue for issue in validation_result["issues"])


@pytest.mark.asyncio
async def test_validate_invalid_node_type(contract_generator):
    """Test validation with invalid node type"""
    contract = {
        "version": "1.0.0",
        "node_type": "INVALID_TYPE",
        "domain": "test",
        "service_name": "test_service",
        "capabilities": [],
        "subcontracts": [],
        "dependencies": {},
    }

    validation_result = await contract_generator.validate_contract(contract)

    assert validation_result["valid"] is False
    assert any("Invalid node type" in issue for issue in validation_result["issues"])


@pytest.mark.asyncio
async def test_validate_invalid_subcontract(contract_generator):
    """Test validation with invalid subcontract structure"""
    contract = {
        "version": "1.0.0",
        "node_type": "EFFECT",
        "domain": "test",
        "service_name": "test_service",
        "capabilities": [],
        "subcontracts": [{"config": {}}],  # Missing 'mixin' field
        "dependencies": {},
    }

    validation_result = await contract_generator.validate_contract(contract)

    assert validation_result["valid"] is False
    assert any("mixin" in issue.lower() for issue in validation_result["issues"])


# Test error handling
@pytest.mark.asyncio
async def test_invalid_node_type_raises_error(contract_generator, sample_prd_analysis):
    """Test that invalid node type raises OnexError"""
    with pytest.raises(OnexError) as exc_info:
        await contract_generator.generate_contract_yaml(
            analysis_result=sample_prd_analysis,
            node_type="INVALID_TYPE",
            microservice_name="test_service",
            domain="test",
        )

    assert "Invalid node type" in str(exc_info.value)


# Test integration with PRD analysis
@pytest.mark.asyncio
async def test_full_contract_generation_workflow(
    contract_generator, sample_prd_analysis, temp_output_dir
):
    """Test complete contract generation workflow"""
    result = await contract_generator.generate_contract_yaml(
        analysis_result=sample_prd_analysis,
        node_type="EFFECT",
        microservice_name="user_authentication",
        domain="auth",
        output_directory=temp_output_dir,
    )

    # Verify all components are present
    assert result["validation_result"]["valid"] is True
    assert result["subcontract_count"] == len(sample_prd_analysis.recommended_mixins)

    # Verify contract includes PRD metadata
    contract = result["contract"]
    assert contract["quality_baseline"] == sample_prd_analysis.quality_baseline
    assert contract["confidence_score"] == sample_prd_analysis.confidence_score
    assert str(sample_prd_analysis.session_id) in contract["metadata"]["prd_session_id"]

    # Verify recommended mixins are in subcontracts
    subcontract_mixins = [sc["mixin"] for sc in contract["subcontracts"]]
    for mixin in sample_prd_analysis.recommended_mixins:
        assert mixin in subcontract_mixins

    # Verify external systems are in dependencies
    assert (
        contract["dependencies"]["external_systems"]
        == sample_prd_analysis.external_systems
    )


@pytest.mark.asyncio
async def test_contract_yaml_format(contract_generator, sample_prd_analysis):
    """Test that generated YAML is properly formatted"""
    result = await contract_generator.generate_contract_yaml(
        analysis_result=sample_prd_analysis,
        node_type="EFFECT",
        microservice_name="test_service",
        domain="test",
    )

    yaml_content = result["contract_yaml"]

    # Verify YAML can be parsed
    parsed = yaml.safe_load(yaml_content)
    assert parsed is not None

    # Verify key fields are present in YAML
    assert "version" in yaml_content
    assert "node_type" in yaml_content
    assert "capabilities" in yaml_content
    assert "subcontracts" in yaml_content


@pytest.mark.asyncio
async def test_mixin_integration_points(contract_generator):
    """Test extraction of mixin integration points"""
    contract_fields = {"capabilities": [], "operations": [], "external_systems": []}

    # Test EventBus integration points
    event_bus_points = contract_generator._extract_mixin_integration_points(
        "MixinEventBus", contract_fields
    )
    assert "on_event_received" in event_bus_points
    assert "publish_event" in event_bus_points

    # Test Caching integration points
    caching_points = contract_generator._extract_mixin_integration_points(
        "MixinCaching", contract_fields
    )
    assert "cache_get" in caching_points
    assert "cache_set" in caching_points
    assert "cache_invalidate" in caching_points


@pytest.mark.asyncio
async def test_capability_name_sanitization(contract_generator):
    """Test capability name sanitization"""
    # Test with special characters
    sanitized = contract_generator._sanitize_capability_name(
        "Create User Account (with validation!)"
    )
    assert sanitized == "create_user_account_with_validation"

    # Test with spaces and hyphens
    sanitized = contract_generator._sanitize_capability_name("Update-User Profile Data")
    assert sanitized == "update_user_profile_data"

    # Test length limit
    long_name = "a" * 100
    sanitized = contract_generator._sanitize_capability_name(long_name)
    assert len(sanitized) <= 50


@pytest.mark.asyncio
async def test_required_capability_detection(contract_generator):
    """Test detection of required capabilities"""
    # Test with required keywords
    assert contract_generator._is_capability_required("Must authenticate users")
    assert contract_generator._is_capability_required("Required to validate tokens")
    assert contract_generator._is_capability_required("Shall encrypt passwords")
    assert contract_generator._is_capability_required("Critical security feature")

    # Test without required keywords
    assert not contract_generator._is_capability_required(
        "Can support multi-factor auth"
    )
    assert not contract_generator._is_capability_required("May include social login")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
