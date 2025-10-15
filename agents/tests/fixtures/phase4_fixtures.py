#!/usr/bin/env python3
"""
Phase 4 Test Fixtures - Sample PRDs and Expected Outputs

Comprehensive fixtures for testing contract, model, and enum generators.
"""

from typing import Dict, Any, List
from uuid import uuid4
from datetime import datetime
from agents.lib.simple_prd_analyzer import (
    SimpleParsedPRD,
    SimpleDecompositionResult,
    SimplePRDAnalysisResult
)


# ============================================================================
# SAMPLE PRDs FOR EACH NODE TYPE
# ============================================================================

EFFECT_NODE_PRD = """# User Management Service

## Overview
User Management Service provides comprehensive user lifecycle operations through a RESTful API.
This service handles user authentication, profile management, and access control.

## Functional Requirements
- Create new user accounts with validation
- Update existing user profiles
- Delete user accounts with soft-delete support
- Retrieve user information by ID or email
- Authenticate users with credentials
- Manage user roles and permissions

## Features
- Email validation and verification
- Password strength enforcement
- Multi-factor authentication support
- Role-based access control
- Audit logging for all operations
- Rate limiting for API endpoints

## Success Criteria
- 99.9% uptime guarantee
- Sub-100ms response time for read operations
- Sub-500ms response time for write operations
- Support 10,000 concurrent users
- Zero data loss on failures

## Technical Details
- RESTful API design
- PostgreSQL for user data storage
- Redis for session caching
- JWT token-based authentication
- Event-driven notifications via Kafka
- Comprehensive input validation
- Health check endpoints

## Dependencies
- PostgreSQL database cluster
- Redis cache cluster
- Kafka event bus
- Authentication service
- Email notification service
"""

COMPUTE_NODE_PRD = """# Data Transformation Service

## Overview
Data Transformation Service transforms CSV data to JSON format with comprehensive validation
and enrichment capabilities. This service processes large datasets efficiently using
streaming algorithms.

## Functional Requirements
- Parse CSV files with configurable delimiters
- Validate data types and constraints
- Transform CSV rows to JSON objects
- Enrich data with computed fields
- Handle malformed data gracefully
- Generate transformation reports

## Features
- Streaming processing for large files
- Configurable transformation rules
- Schema validation with JSON Schema
- Data quality scoring
- Automatic type inference
- Parallel processing support

## Success Criteria
- Process 1 million rows per minute
- 99.99% transformation accuracy
- Graceful handling of malformed data
- Memory usage under 2GB for any file size
- Zero data loss during transformation

## Technical Details
- Pure computation with no side effects
- Streaming CSV parser
- JSON schema validation
- Type inference algorithms
- Parallel processing with worker pools
- Deterministic transformation logic
- Comprehensive error reporting

## Dependencies
- JSON Schema validator library
- CSV parsing library
- Data quality scoring algorithms
"""

REDUCER_NODE_PRD = """# Analytics Aggregator Service

## Overview
Analytics Aggregator Service processes user activity metrics and computes trends,
aggregations, and statistical summaries. This service combines data from multiple
sources to generate comprehensive analytics reports.

## Functional Requirements
- Aggregate user activity metrics by time period
- Compute statistical summaries (mean, median, percentiles)
- Identify usage trends and patterns
- Generate time-series aggregations
- Merge data from multiple sources
- Persist aggregated results to database

## Features
- Real-time aggregation streaming
- Time-window based grouping
- Custom aggregation functions
- Incremental updates support
- Data deduplication
- Materialized view management

## Success Criteria
- Process 100,000 events per second
- Sub-second aggregation latency
- 99.9% accuracy in calculations
- Support 1TB of historical data
- Automatic recomputation on data changes

## Technical Details
- Stateful aggregation with checkpointing
- PostgreSQL for persistent storage
- Redis for intermediate state
- Time-series optimizations
- Incremental aggregation algorithms
- Distributed aggregation support
- Materialized view refresh strategies

## Dependencies
- PostgreSQL database
- Redis cache
- Time-series database
- Data quality monitoring
"""

ORCHESTRATOR_NODE_PRD = """# Workflow Coordinator Service

## Overview
Workflow Coordinator Service orchestrates multi-step data processing pipelines.
This service manages workflow execution, handles failures, and ensures data consistency
across distributed operations.

## Functional Requirements
- Define and execute multi-step workflows
- Coordinate between multiple microservices
- Handle workflow failures and retries
- Track workflow execution state
- Support parallel execution paths
- Implement compensation logic for failures

## Features
- Declarative workflow definitions
- Dynamic workflow branching
- Distributed transaction support
- Saga pattern implementation
- Workflow visualization and monitoring
- SLA tracking and alerting

## Success Criteria
- Execute 1,000 workflows concurrently
- 99.99% workflow completion rate
- Average workflow latency under 5 seconds
- Automatic failure recovery
- Zero data inconsistency

## Technical Details
- State machine based orchestration
- Event-driven coordination via Kafka
- Distributed transaction management
- Workflow persistence in PostgreSQL
- Circuit breaker patterns
- Health monitoring for all services
- Comprehensive audit logging

## Dependencies
- Kafka event bus
- PostgreSQL workflow state database
- Redis for workflow locks
- All downstream microservices
- Monitoring and alerting infrastructure
"""


# ============================================================================
# MOCK ANALYSIS RESULTS
# ============================================================================

def create_mock_analysis_result(
    prd_content: str,
    node_type: str,
    mixins: List[str] = None,
    external_systems: List[str] = None
) -> SimplePRDAnalysisResult:
    """Create a mock SimplePRDAnalysisResult for testing"""

    # Parse the PRD content
    from agents.lib.simple_prd_analyzer import SimplePRDAnalyzer
    analyzer = SimplePRDAnalyzer()

    # Extract basic info for parsed PRD
    title_line = prd_content.split('\n')[0].strip('# ')

    # Create basic parsed PRD
    parsed_prd = SimpleParsedPRD(
        title=title_line,
        description=f"Test {node_type} node for {title_line}",
        features=["Feature 1", "Feature 2", "Feature 3"],
        functional_requirements=["Requirement 1", "Requirement 2"],
        success_criteria=["99.9% uptime", "Sub-second response"],
        technical_details=["High availability", "Scalability"],
        dependencies=external_systems or ["database"],
        extracted_keywords=["test", "node", node_type.lower()],
        sections=["Overview", "Requirements", "Features"],
        word_count=len(prd_content.split())
    )

    # Create decomposition
    decomposition_result = SimpleDecompositionResult(
        tasks=[
            {
                "id": "task_1",
                "title": "Implement core functionality",
                "description": f"Implement core {node_type} logic",
                "priority": "high",
                "complexity": "medium"
            },
            {
                "id": "task_2",
                "title": "Add validation",
                "description": "Add input validation",
                "priority": "medium",
                "complexity": "low"
            }
        ],
        total_tasks=2,
        verification_successful=True
    )

    # Set node type hints
    node_type_hints = {
        "EFFECT": 0.0,
        "COMPUTE": 0.0,
        "REDUCER": 0.0,
        "ORCHESTRATOR": 0.0
    }
    node_type_hints[node_type] = 0.9

    return SimplePRDAnalysisResult(
        session_id=uuid4(),
        correlation_id=uuid4(),
        prd_content=prd_content,
        parsed_prd=parsed_prd,
        decomposition_result=decomposition_result,
        node_type_hints=node_type_hints,
        recommended_mixins=mixins or ["MixinEventBus", "MixinHealthCheck"],
        external_systems=external_systems or ["PostgreSQL", "Redis"],
        quality_baseline=0.85,
        confidence_score=0.90,
        analysis_timestamp=datetime.utcnow()
    )


# Pre-created analysis results for each node type
EFFECT_ANALYSIS_RESULT = create_mock_analysis_result(
    EFFECT_NODE_PRD,
    "EFFECT",
    mixins=["MixinEventBus", "MixinHealthCheck", "MixinCaching"],
    external_systems=["PostgreSQL", "Redis", "Kafka"]
)

COMPUTE_ANALYSIS_RESULT = create_mock_analysis_result(
    COMPUTE_NODE_PRD,
    "COMPUTE",
    mixins=["MixinValidation", "MixinMetrics"],
    external_systems=[]
)

REDUCER_ANALYSIS_RESULT = create_mock_analysis_result(
    REDUCER_NODE_PRD,
    "REDUCER",
    mixins=["MixinEventBus", "MixinCaching", "MixinMetrics"],
    external_systems=["PostgreSQL", "Redis"]
)

ORCHESTRATOR_ANALYSIS_RESULT = create_mock_analysis_result(
    ORCHESTRATOR_NODE_PRD,
    "ORCHESTRATOR",
    mixins=["MixinEventBus", "MixinHealthCheck", "MixinCircuitBreaker", "MixinRetry"],
    external_systems=["Kafka", "PostgreSQL", "Redis"]
)


# ============================================================================
# EXPECTED CONTRACT YAML OUTPUTS
# ============================================================================

EXPECTED_EFFECT_CONTRACT_YAML = """# Contract for User Management Service Effect Node
version: "1.0.0"
node_type: "EFFECT"
domain: "identity"
microservice_name: "user_management"

capabilities:
  - name: "create_user"
    description: "Create new user account"
    operation_type: "write"
  - name: "update_user"
    description: "Update existing user profile"
    operation_type: "write"
  - name: "delete_user"
    description: "Delete user account"
    operation_type: "write"
  - name: "get_user"
    description: "Retrieve user information"
    operation_type: "read"

mixins:
  - MixinEventBus
  - MixinHealthCheck
  - MixinCaching

external_dependencies:
  - type: "database"
    name: "PostgreSQL"
    operations: ["read", "write"]
  - type: "cache"
    name: "Redis"
    operations: ["read", "write"]
  - type: "event_bus"
    name: "Kafka"
    operations: ["publish"]

quality_requirements:
  response_time_ms: 500
  availability_percent: 99.9
  error_rate_percent: 0.1
"""

EXPECTED_COMPUTE_CONTRACT_YAML = """# Contract for Data Transformation Service Compute Node
version: "1.0.0"
node_type: "COMPUTE"
domain: "data_processing"
microservice_name: "csv_json_transformer"

capabilities:
  - name: "transform_csv_to_json"
    description: "Transform CSV data to JSON format"
    operation_type: "transform"
  - name: "validate_data"
    description: "Validate data types and constraints"
    operation_type: "validate"

mixins:
  - MixinValidation
  - MixinMetrics

external_dependencies: []

quality_requirements:
  throughput_per_second: 1000000
  accuracy_percent: 99.99
  memory_limit_mb: 2048
"""


# ============================================================================
# EXPECTED MODEL CODE OUTPUTS
# ============================================================================

EXPECTED_INPUT_MODEL_TEMPLATE = '''#!/usr/bin/env python3
"""
Input model for {microservice_name}
"""

from typing import Dict, Any, Optional
from uuid import UUID
from pydantic import BaseModel, Field
from datetime import datetime


class Model{microservice_name_pascal}Input(BaseModel):
    """Input model for {microservice_name} operations"""

    operation: str = Field(..., description="Operation to perform")
    data: Dict[str, Any] = Field(default_factory=dict, description="Input data")
    correlation_id: UUID = Field(..., description="Correlation ID for tracing")
    timestamp: datetime = Field(default_factory=datetime.utcnow, description="Request timestamp")
    metadata: Optional[Dict[str, Any]] = Field(default=None, description="Additional metadata")

    class Config:
        json_schema_extra = {{
            "example": {{
                "operation": "create",
                "data": {{}},
                "correlation_id": "123e4567-e89b-12d3-a456-426614174000",
                "timestamp": "2025-10-15T00:00:00Z"
            }}
        }}
'''

EXPECTED_OUTPUT_MODEL_TEMPLATE = '''#!/usr/bin/env python3
"""
Output model for {microservice_name}
"""

from typing import Dict, Any, Optional
from uuid import UUID
from pydantic import BaseModel, Field
from datetime import datetime


class Model{microservice_name_pascal}Output(BaseModel):
    """Output model for {microservice_name} operations"""

    success: bool = Field(..., description="Operation success status")
    result_data: Dict[str, Any] = Field(default_factory=dict, description="Result data")
    correlation_id: UUID = Field(..., description="Correlation ID for tracing")
    timestamp: datetime = Field(default_factory=datetime.utcnow, description="Response timestamp")
    error_message: Optional[str] = Field(default=None, description="Error message if failed")
    metadata: Optional[Dict[str, Any]] = Field(default=None, description="Additional metadata")

    class Config:
        json_schema_extra = {{
            "example": {{
                "success": True,
                "result_data": {{}},
                "correlation_id": "123e4567-e89b-12d3-a456-426614174000",
                "timestamp": "2025-10-15T00:00:00Z"
            }}
        }}
'''


# ============================================================================
# EXPECTED ENUM CODE OUTPUTS
# ============================================================================

EXPECTED_OPERATION_ENUM_TEMPLATE = '''#!/usr/bin/env python3
"""
Operation type enum for {microservice_name}
"""

from enum import Enum


class Enum{microservice_name_pascal}OperationType(str, Enum):
    """Operation types for {microservice_name}"""

    CREATE = "create"
    READ = "read"
    UPDATE = "update"
    DELETE = "delete"
    LIST = "list"

    def __str__(self) -> str:
        return self.value
'''


# ============================================================================
# TEST HELPER DATA
# ============================================================================

NODE_TYPE_FIXTURES = {
    "EFFECT": {
        "prd": EFFECT_NODE_PRD,
        "analysis": EFFECT_ANALYSIS_RESULT,
        "expected_contract": EXPECTED_EFFECT_CONTRACT_YAML,
        "microservice_name": "user_management",
        "domain": "identity"
    },
    "COMPUTE": {
        "prd": COMPUTE_NODE_PRD,
        "analysis": COMPUTE_ANALYSIS_RESULT,
        "expected_contract": EXPECTED_COMPUTE_CONTRACT_YAML,
        "microservice_name": "csv_json_transformer",
        "domain": "data_processing"
    },
    "REDUCER": {
        "prd": REDUCER_NODE_PRD,
        "analysis": REDUCER_ANALYSIS_RESULT,
        "expected_contract": None,  # To be defined
        "microservice_name": "analytics_aggregator",
        "domain": "analytics"
    },
    "ORCHESTRATOR": {
        "prd": ORCHESTRATOR_NODE_PRD,
        "analysis": ORCHESTRATOR_ANALYSIS_RESULT,
        "expected_contract": None,  # To be defined
        "microservice_name": "workflow_coordinator",
        "domain": "orchestration"
    }
}


# ============================================================================
# VALIDATION TEST DATA
# ============================================================================

ONEX_NAMING_VIOLATIONS = [
    "user_service.py",  # Should be node_user_management_effect.py
    "DataProcessor.py",  # Wrong case
    "model-user.py",  # Should use underscores
    "EnumStatus.py",  # Should be enum_status.py
]

ONEX_NAMING_VALID = [
    "node_user_management_effect.py",
    "model_user_input.py",
    "model_user_output.py",
    "enum_operation_type.py",
]

TYPE_SAFETY_VIOLATIONS = [
    "def process(data: Any) -> Any:",  # Uses Any
    "result: Dict = {}",  # Missing type parameter
    "items: List = []",  # Missing type parameter
]

TYPE_SAFETY_VALID = [
    "def process(data: Dict[str, Any]) -> ModelOutput:",
    "result: Dict[str, int] = {}",
    "items: List[str] = []",
]


# ============================================================================
# PERFORMANCE TEST DATA
# ============================================================================

PERFORMANCE_EXPECTATIONS = {
    "prd_analysis_ms": 2000,  # 2 seconds max
    "contract_generation_ms": 1000,  # 1 second max
    "model_generation_ms": 500,  # 500ms per model
    "enum_generation_ms": 200,  # 200ms per enum
    "total_pipeline_ms": 5000,  # 5 seconds max for full pipeline
}

LARGE_PRD_CONTENT = """# Large Enterprise System

## Overview
""" + "\n".join([f"- Feature {i}: Description of feature {i}" for i in range(100)]) + """

## Functional Requirements
""" + "\n".join([f"- Requirement {i}: Detailed requirement description {i}" for i in range(50)]) + """

## Technical Details
""" + "\n".join([f"- Technical detail {i}: Implementation detail {i}" for i in range(50)])


# ============================================================================
# ERROR CASE TEST DATA
# ============================================================================

EMPTY_PRD = ""

MALFORMED_PRD = """This is not a properly formatted PRD
It has no sections
And no structure
"""

MINIMAL_PRD = """# Minimal PRD

## Overview
Basic service
"""


# ============================================================================
# EXPORT ALL FIXTURES
# ============================================================================

__all__ = [
    # PRD Content
    "EFFECT_NODE_PRD",
    "COMPUTE_NODE_PRD",
    "REDUCER_NODE_PRD",
    "ORCHESTRATOR_NODE_PRD",

    # Analysis Results
    "EFFECT_ANALYSIS_RESULT",
    "COMPUTE_ANALYSIS_RESULT",
    "REDUCER_ANALYSIS_RESULT",
    "ORCHESTRATOR_ANALYSIS_RESULT",

    # Expected Outputs
    "EXPECTED_EFFECT_CONTRACT_YAML",
    "EXPECTED_COMPUTE_CONTRACT_YAML",
    "EXPECTED_INPUT_MODEL_TEMPLATE",
    "EXPECTED_OUTPUT_MODEL_TEMPLATE",
    "EXPECTED_OPERATION_ENUM_TEMPLATE",

    # Organized Fixtures
    "NODE_TYPE_FIXTURES",

    # Validation Data
    "ONEX_NAMING_VIOLATIONS",
    "ONEX_NAMING_VALID",
    "TYPE_SAFETY_VIOLATIONS",
    "TYPE_SAFETY_VALID",

    # Performance Data
    "PERFORMANCE_EXPECTATIONS",
    "LARGE_PRD_CONTENT",

    # Error Cases
    "EMPTY_PRD",
    "MALFORMED_PRD",
    "MINIMAL_PRD",

    # Helper Functions
    "create_mock_analysis_result",
]
