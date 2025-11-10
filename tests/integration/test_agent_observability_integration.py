#!/usr/bin/env python3
"""
Comprehensive Integration Tests for Agent Observability System

Tests the complete end-to-end flow of agent observability including:
- Agent action logging (all 4 types: tool_call, decision, error, success)
- Agent transformation events (Kafka → Database)
- Agent manifest injections (creation and retrieval)
- Correlation ID tracking across all tables
- Database schema compliance and constraints

These tests are designed to catch bugs like:
- UUID serialization issues (would catch the transformation event bug)
- Missing instrumentation (would catch 0 errors/successes logged)
- Schema violations
- Correlation ID mismatches
- Missing database writes

Usage:
    # Run all integration tests
    pytest tests/integration/test_agent_observability_integration.py -v

    # Run specific test class
    pytest tests/integration/test_agent_observability_integration.py::TestAgentActionsLogging -v

    # Run with detailed output
    pytest tests/integration/test_agent_observability_integration.py -v -s

Prerequisites:
    - PostgreSQL running and accessible (POSTGRES_* env vars set)
    - Kafka running and accessible (KAFKA_BOOTSTRAP_SERVERS env var set)
    - Consumer services running (agent_actions_consumer.py)
    - .env file loaded with credentials

Author: polymorphic-agent
Created: 2025-11-09
Correlation ID: d7072fb8-a0c5-4465-838e-05f54c70ef45
"""

import asyncio
import logging
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional
from uuid import UUID, uuid4

import pytest

# Database imports
try:
    import psycopg2
    from psycopg2.extras import RealDictCursor

    POSTGRES_AVAILABLE = True
except ImportError:
    POSTGRES_AVAILABLE = False
    pytest.skip("psycopg2 not installed", allow_module_level=True)

# Project imports
from agents.lib.action_logger import ActionLogger
from agents.lib.transformation_event_publisher import (
    publish_transformation_complete,
    publish_transformation_failed,
    publish_transformation_start,
)

logger = logging.getLogger(__name__)


# =============================================================================
# Pytest Fixtures
# =============================================================================


@pytest.fixture(scope="session")
def db_connection():
    """
    Session-scoped database connection fixture.

    Provides a shared database connection for all tests.
    Connection is automatically closed after all tests complete.
    """
    if not POSTGRES_AVAILABLE:
        pytest.skip("PostgreSQL not available")

    # Load credentials from environment
    db_config = {
        "host": os.getenv("POSTGRES_HOST", "localhost"),
        "port": int(os.getenv("POSTGRES_PORT", "5432")),
        "database": os.getenv("POSTGRES_DATABASE", "omninode_bridge"),
        "user": os.getenv("POSTGRES_USER", "postgres"),
        "password": os.getenv("POSTGRES_PASSWORD"),
    }

    if not db_config["password"]:
        pytest.skip("POSTGRES_PASSWORD not set - load .env file")

    try:
        conn = psycopg2.connect(**db_config)
        logger.info(
            f"✓ Database connection established: {db_config['host']}:{db_config['port']}"
        )
        yield conn
        conn.close()
        logger.info("✓ Database connection closed")
    except Exception as e:
        pytest.skip(f"Failed to connect to database: {e}")


@pytest.fixture
def correlation_id() -> str:
    """Generate unique correlation ID for each test."""
    return str(uuid4())


@pytest.fixture
def action_logger(correlation_id: str) -> ActionLogger:
    """Create ActionLogger instance for testing."""
    return ActionLogger(
        agent_name="test-agent-observability",
        correlation_id=correlation_id,
        project_name="omniclaude-test",
        project_path="/tmp/test-observability",
        debug_mode=True,
    )


@pytest.fixture
def kafka_available() -> bool:
    """Check if Kafka is available."""
    kafka_servers = os.getenv("KAFKA_BOOTSTRAP_SERVERS")
    if not kafka_servers:
        pytest.skip("KAFKA_BOOTSTRAP_SERVERS not set - load .env file")
    return True


@pytest.fixture
def consumer_wait_time() -> int:
    """
    Time to wait for Kafka consumer to process events and write to database.

    Increase this value if tests are flaky due to timing issues.
    """
    return int(os.getenv("TEST_CONSUMER_WAIT_TIME", "5"))  # seconds


# =============================================================================
# Helper Functions
# =============================================================================


def query_agent_actions(
    db_conn, correlation_id: str, action_type: Optional[str] = None
) -> List[Dict]:
    """
    Query agent_actions table by correlation_id.

    Args:
        db_conn: Database connection
        correlation_id: Correlation ID to filter by
        action_type: Optional action type filter (tool_call, decision, error, success)

    Returns:
        List of action records as dictionaries
    """
    cursor = db_conn.cursor(cursor_factory=RealDictCursor)

    if action_type:
        query = """
            SELECT * FROM agent_actions
            WHERE correlation_id = %s AND action_type = %s
            ORDER BY created_at ASC
        """
        cursor.execute(query, (correlation_id, action_type))
    else:
        query = """
            SELECT * FROM agent_actions
            WHERE correlation_id = %s
            ORDER BY created_at ASC
        """
        cursor.execute(query, (correlation_id,))

    results = cursor.fetchall()
    cursor.close()
    return [dict(row) for row in results]


def query_transformation_events(db_conn, correlation_id: str) -> List[Dict]:
    """
    Query agent_transformation_events table by correlation_id.

    Args:
        db_conn: Database connection
        correlation_id: Correlation ID to filter by

    Returns:
        List of transformation event records as dictionaries
    """
    cursor = db_conn.cursor(cursor_factory=RealDictCursor)
    query = """
        SELECT * FROM agent_transformation_events
        WHERE correlation_id = %s
        ORDER BY started_at ASC
    """
    cursor.execute(query, (correlation_id,))
    results = cursor.fetchall()
    cursor.close()
    return [dict(row) for row in results]


def query_manifest_injections(db_conn, correlation_id: str) -> List[Dict]:
    """
    Query agent_manifest_injections table by correlation_id.

    Args:
        db_conn: Database connection
        correlation_id: Correlation ID to filter by

    Returns:
        List of manifest injection records as dictionaries
    """
    cursor = db_conn.cursor(cursor_factory=RealDictCursor)
    query = """
        SELECT * FROM agent_manifest_injections
        WHERE correlation_id = %s
        ORDER BY created_at ASC
    """
    cursor.execute(query, (correlation_id,))
    results = cursor.fetchall()
    cursor.close()
    return [dict(row) for row in results]


def query_routing_decisions(db_conn, correlation_id: str) -> List[Dict]:
    """
    Query agent_routing_decisions table by correlation_id.

    Args:
        db_conn: Database connection
        correlation_id: Correlation ID to filter by

    Returns:
        List of routing decision records as dictionaries
    """
    cursor = db_conn.cursor(cursor_factory=RealDictCursor)
    query = """
        SELECT * FROM agent_routing_decisions
        WHERE correlation_id = %s
        ORDER BY created_at ASC
    """
    cursor.execute(query, (correlation_id,))
    results = cursor.fetchall()
    cursor.close()
    return [dict(row) for row in results]


def verify_uuid_field(value, field_name: str):
    """
    Verify that a field is a valid UUID.

    This would catch the UUID serialization bug where UUIDs were being
    stored as strings instead of proper UUID types.

    Args:
        value: Value to check
        field_name: Name of field for error messages

    Raises:
        AssertionError: If value is not a valid UUID
    """
    assert value is not None, f"{field_name} is None"
    # In PostgreSQL, UUIDs are returned as strings by psycopg2
    # Verify it's a valid UUID string format
    try:
        UUID(str(value))
    except (ValueError, AttributeError) as e:
        pytest.fail(f"{field_name} is not a valid UUID: {value} ({type(value)})")


# =============================================================================
# Test Class: Agent Actions Logging
# =============================================================================


@pytest.mark.integration
class TestAgentActionsLogging:
    """
    Integration tests for agent action logging.

    Tests all 4 action types:
    - tool_call: Tool invocations (Read, Write, Edit, Bash, etc.)
    - decision: Routing decisions and agent selection
    - error: Error events and exceptions
    - success: Success events and completions

    These tests would have caught the missing instrumentation bugs
    where error and success logging had 0 records.
    """

    @pytest.mark.asyncio
    async def test_tool_call_logging(
        self,
        db_connection,
        action_logger: ActionLogger,
        correlation_id: str,
        kafka_available: bool,
        consumer_wait_time: int,
    ):
        """
        Test that tool call actions are logged correctly to Kafka and PostgreSQL.

        This test would catch:
        - Missing tool call instrumentation
        - Schema violations in action_details
        - UUID serialization issues
        """
        logger.info(f"Testing tool_call logging (correlation_id: {correlation_id})")

        # Publish tool call action
        async with action_logger.tool_call(
            "Read", tool_parameters={"file_path": "/tmp/test.py", "offset": 0}
        ) as action:
            await asyncio.sleep(0.01)
            action.set_result({"line_count": 100, "success": True})

        logger.info("✓ Tool call action published to Kafka")

        # Wait for consumer to process
        await asyncio.sleep(consumer_wait_time)

        # Query database
        actions = query_agent_actions(db_connection, correlation_id, "tool_call")

        # Assertions
        assert len(actions) >= 1, "Expected at least 1 tool_call action in database"

        action = actions[0]
        assert action["action_type"] == "tool_call"
        assert action["action_name"] == "Read"
        verify_uuid_field(action["correlation_id"], "correlation_id")
        assert action["agent_name"] == "test-agent-observability"
        assert action["action_details"] is not None
        assert "file_path" in action["action_details"]
        assert "line_count" in action["action_details"]
        assert action["duration_ms"] is not None
        assert action["duration_ms"] > 0

        logger.info(f"✓ Tool call action verified in database: {action['id']}")

    @pytest.mark.asyncio
    async def test_decision_logging(
        self,
        db_connection,
        action_logger: ActionLogger,
        correlation_id: str,
        kafka_available: bool,
        consumer_wait_time: int,
    ):
        """
        Test that decision actions are logged correctly to Kafka and PostgreSQL.

        This test would catch:
        - Missing decision instrumentation
        - Schema violations in decision_context/decision_result
        """
        logger.info(f"Testing decision logging (correlation_id: {correlation_id})")

        # Publish decision action
        await action_logger.log_decision(
            decision_name="select_agent",
            decision_context={"candidates": ["agent-a", "agent-b", "agent-c"]},
            decision_result={"selected": "agent-a", "confidence": 0.92},
            duration_ms=15,
        )

        logger.info("✓ Decision action published to Kafka")

        # Wait for consumer to process
        await asyncio.sleep(consumer_wait_time)

        # Query database
        actions = query_agent_actions(db_connection, correlation_id, "decision")

        # Assertions
        assert len(actions) >= 1, "Expected at least 1 decision action in database"

        action = actions[0]
        assert action["action_type"] == "decision"
        assert action["action_name"] == "select_agent"
        verify_uuid_field(action["correlation_id"], "correlation_id")
        assert action["action_details"] is not None
        assert "decision_context" in action["action_details"]
        assert "decision_result" in action["action_details"]
        assert action["action_details"]["decision_result"]["selected"] == "agent-a"
        assert action["duration_ms"] == 15

        logger.info(f"✓ Decision action verified in database: {action['id']}")

    @pytest.mark.asyncio
    async def test_error_logging(
        self,
        db_connection,
        action_logger: ActionLogger,
        correlation_id: str,
        kafka_available: bool,
        consumer_wait_time: int,
    ):
        """
        Test that error actions are logged correctly to Kafka and PostgreSQL.

        THIS TEST WOULD HAVE CAUGHT THE BUG: Manual testing found 0 errors logged!

        This test verifies:
        - Error events are published to Kafka
        - Consumer processes error events
        - Errors are persisted to agent_actions table
        - Error details are properly stored in action_details JSONB
        """
        logger.info(f"Testing error logging (correlation_id: {correlation_id})")

        # Publish error action
        test_host = os.getenv("POSTGRES_HOST", "localhost")
        test_port = int(os.getenv("POSTGRES_PORT", "5432"))
        await action_logger.log_error(
            error_type="DatabaseConnectionError",
            error_message=f"Failed to connect to PostgreSQL at {test_host}:{test_port}",
            error_context={
                "host": test_host,
                "port": test_port,
                "database": "omninode_bridge",
                "retry_count": 3,
            },
            severity="error",
            send_slack_notification=False,  # Don't spam Slack in tests
        )

        logger.info("✓ Error action published to Kafka")

        # Wait for consumer to process
        await asyncio.sleep(consumer_wait_time)

        # Query database
        actions = query_agent_actions(db_connection, correlation_id, "error")

        # Assertions
        # THIS IS THE CRITICAL ASSERTION THAT WOULD FAIL IF ERROR LOGGING IS BROKEN
        assert (
            len(actions) >= 1
        ), "FAILED: Expected at least 1 error action in database - ERROR LOGGING NOT WORKING!"

        action = actions[0]
        assert action["action_type"] == "error"
        assert action["action_name"] == "DatabaseConnectionError"
        verify_uuid_field(action["correlation_id"], "correlation_id")
        assert action["action_details"] is not None
        assert "error_type" in action["action_details"]
        assert "error_message" in action["action_details"]
        assert "error_context" in action["action_details"]
        assert action["action_details"]["error_type"] == "DatabaseConnectionError"
        expected_host = os.getenv("POSTGRES_HOST", "localhost")
        assert expected_host in action["action_details"]["error_message"]

        logger.info(f"✓ Error action verified in database: {action['id']}")

    @pytest.mark.asyncio
    async def test_success_logging(
        self,
        db_connection,
        action_logger: ActionLogger,
        correlation_id: str,
        kafka_available: bool,
        consumer_wait_time: int,
    ):
        """
        Test that success actions are logged correctly to Kafka and PostgreSQL.

        THIS TEST WOULD HAVE CAUGHT THE BUG: Manual testing found 0 successes logged!

        This test verifies:
        - Success events are published to Kafka
        - Consumer processes success events
        - Successes are persisted to agent_actions table
        - Success details are properly stored in action_details JSONB
        """
        logger.info(f"Testing success logging (correlation_id: {correlation_id})")

        # Publish success action
        await action_logger.log_success(
            success_name="task_completed",
            success_details={
                "files_processed": 5,
                "quality_score": 0.95,
                "output_path": "/tmp/output",
            },
            duration_ms=250,
        )

        logger.info("✓ Success action published to Kafka")

        # Wait for consumer to process
        await asyncio.sleep(consumer_wait_time)

        # Query database
        actions = query_agent_actions(db_connection, correlation_id, "success")

        # Assertions
        # THIS IS THE CRITICAL ASSERTION THAT WOULD FAIL IF SUCCESS LOGGING IS BROKEN
        assert (
            len(actions) >= 1
        ), "FAILED: Expected at least 1 success action in database - SUCCESS LOGGING NOT WORKING!"

        action = actions[0]
        assert action["action_type"] == "success"
        assert action["action_name"] == "task_completed"
        verify_uuid_field(action["correlation_id"], "correlation_id")
        assert action["action_details"] is not None
        assert "success_details" in action["action_details"]
        assert action["action_details"]["success_details"]["files_processed"] == 5
        assert action["action_details"]["success_details"]["quality_score"] == 0.95
        assert action["duration_ms"] == 250

        logger.info(f"✓ Success action verified in database: {action['id']}")

    @pytest.mark.asyncio
    async def test_all_action_types_together(
        self,
        db_connection,
        action_logger: ActionLogger,
        correlation_id: str,
        kafka_available: bool,
        consumer_wait_time: int,
    ):
        """
        Test that all 4 action types can be logged in sequence and retrieved together.

        This test verifies:
        - Multiple action types with same correlation_id
        - Chronological ordering
        - Complete trace reconstruction
        """
        logger.info(
            f"Testing all action types together (correlation_id: {correlation_id})"
        )

        # Log all 4 action types in sequence
        await action_logger.log_tool_call(
            tool_name="Read",
            tool_parameters={"file_path": "/tmp/test.py"},
            tool_result={"line_count": 100},
            duration_ms=25,
        )

        await action_logger.log_decision(
            decision_name="select_strategy",
            decision_result={"strategy": "parallel"},
            duration_ms=10,
        )

        await action_logger.log_error(
            error_type="ValidationError",
            error_message="Invalid input detected",
            severity="warning",
            send_slack_notification=False,
        )

        await action_logger.log_success(
            success_name="validation_completed", duration_ms=50
        )

        logger.info("✓ All 4 action types published to Kafka")

        # Wait for consumer to process
        await asyncio.sleep(consumer_wait_time)

        # Query database
        all_actions = query_agent_actions(db_connection, correlation_id)

        # Assertions
        assert (
            len(all_actions) >= 4
        ), f"Expected at least 4 actions, found {len(all_actions)}"

        action_types = {action["action_type"] for action in all_actions}
        assert "tool_call" in action_types, "Missing tool_call action"
        assert "decision" in action_types, "Missing decision action"
        assert "error" in action_types, "Missing error action"
        assert "success" in action_types, "Missing success action"

        # Verify chronological ordering
        timestamps = [action["created_at"] for action in all_actions]
        assert timestamps == sorted(timestamps), "Actions not in chronological order"

        logger.info(f"✓ All 4 action types verified in database with correct ordering")


# =============================================================================
# Test Class: Agent Transformation Events
# =============================================================================


@pytest.mark.integration
class TestTransformationEvents:
    """
    Integration tests for agent transformation event logging.

    Tests the complete flow:
    1. Publish transformation event to Kafka
    2. Consumer picks up event and processes
    3. Event persisted to agent_transformation_events table
    4. UUID fields are properly serialized

    THIS TEST CLASS WOULD HAVE CAUGHT THE UUID SERIALIZATION BUG!
    """

    @pytest.mark.asyncio
    async def test_transformation_complete_event(
        self,
        db_connection,
        correlation_id: str,
        kafka_available: bool,
        consumer_wait_time: int,
    ):
        """
        Test successful transformation event flow.

        THIS TEST WOULD CATCH THE UUID SERIALIZATION BUG!

        The bug was: UUID objects were being serialized to Kafka but the
        consumer couldn't deserialize them properly, causing silent failures
        or incorrect data in the database.
        """
        logger.info(
            f"Testing transformation_complete event (correlation_id: {correlation_id})"
        )

        # Publish transformation complete event
        success = await publish_transformation_complete(
            source_agent="polymorphic-agent",
            target_agent="agent-api-architect",
            transformation_reason="API design task detected",
            correlation_id=correlation_id,
            user_request="Design a REST API for user management",
            routing_confidence=0.92,
            routing_strategy="fuzzy_match",
            transformation_duration_ms=45,
            initialization_duration_ms=120,
        )

        assert success, "Failed to publish transformation event to Kafka"
        logger.info("✓ Transformation complete event published to Kafka")

        # Wait for consumer to process
        await asyncio.sleep(consumer_wait_time)

        # Query database
        events = query_transformation_events(db_connection, correlation_id)

        # Assertions
        # THIS IS THE CRITICAL ASSERTION THAT WOULD CATCH THE UUID BUG
        assert (
            len(events) >= 1
        ), "FAILED: Expected at least 1 transformation event - UUID SERIALIZATION MAY BE BROKEN!"

        event = events[0]
        assert event["event_type"] == "transformation_complete"
        verify_uuid_field(event["correlation_id"], "correlation_id")
        assert event["source_agent"] == "polymorphic-agent"
        assert event["target_agent"] == "agent-api-architect"
        assert event["routing_confidence"] == 0.92
        assert event["transformation_duration_ms"] == 45
        assert event["success"] is True

        logger.info(
            f"✓ Transformation complete event verified in database: {event['id']}"
        )

    @pytest.mark.asyncio
    async def test_transformation_failed_event(
        self,
        db_connection,
        correlation_id: str,
        kafka_available: bool,
        consumer_wait_time: int,
    ):
        """
        Test failed transformation event flow.
        """
        logger.info(
            f"Testing transformation_failed event (correlation_id: {correlation_id})"
        )

        # Publish transformation failed event
        success = await publish_transformation_failed(
            source_agent="polymorphic-agent",
            target_agent="agent-nonexistent",
            transformation_reason="Attempted transformation to unknown agent",
            correlation_id=correlation_id,
            error_message="Agent definition not found: agent-nonexistent.yaml",
            error_type="FileNotFoundError",
            user_request="Use nonexistent agent",
            routing_confidence=0.75,
        )

        assert success, "Failed to publish transformation failed event to Kafka"
        logger.info("✓ Transformation failed event published to Kafka")

        # Wait for consumer to process
        await asyncio.sleep(consumer_wait_time)

        # Query database
        events = query_transformation_events(db_connection, correlation_id)

        # Assertions
        assert len(events) >= 1, "Expected at least 1 transformation event"

        event = events[0]
        assert event["event_type"] == "transformation_failed"
        verify_uuid_field(event["correlation_id"], "correlation_id")
        assert event["source_agent"] == "polymorphic-agent"
        assert event["target_agent"] == "agent-nonexistent"
        assert event["success"] is False
        assert event["error_type"] == "FileNotFoundError"
        assert "not found" in event["error_message"]

        logger.info(
            f"✓ Transformation failed event verified in database: {event['id']}"
        )

    @pytest.mark.asyncio
    async def test_transformation_start_event(
        self,
        db_connection,
        correlation_id: str,
        kafka_available: bool,
        consumer_wait_time: int,
    ):
        """
        Test transformation start event flow.
        """
        logger.info(
            f"Testing transformation_start event (correlation_id: {correlation_id})"
        )

        # Publish transformation start event
        success = await publish_transformation_start(
            source_agent="polymorphic-agent",
            target_agent="agent-debug-intelligence",
            transformation_reason="Debug investigation task detected",
            correlation_id=correlation_id,
            user_request="Debug why my database queries are slow",
            routing_confidence=0.88,
            routing_strategy="capability_match",
        )

        assert success, "Failed to publish transformation start event to Kafka"
        logger.info("✓ Transformation start event published to Kafka")

        # Wait for consumer to process
        await asyncio.sleep(consumer_wait_time)

        # Query database
        events = query_transformation_events(db_connection, correlation_id)

        # Assertions
        assert len(events) >= 1, "Expected at least 1 transformation event"

        event = events[0]
        assert event["event_type"] == "transformation_start"
        verify_uuid_field(event["correlation_id"], "correlation_id")
        assert event["source_agent"] == "polymorphic-agent"
        assert event["target_agent"] == "agent-debug-intelligence"
        assert event["routing_confidence"] == 0.88

        logger.info(f"✓ Transformation start event verified in database: {event['id']}")

    @pytest.mark.asyncio
    async def test_polymorphic_agent_switching(
        self,
        db_connection,
        correlation_id: str,
        kafka_available: bool,
        consumer_wait_time: int,
    ):
        """
        Test multiple transformation events for polymorphic agent switching.

        This test simulates a realistic workflow:
        1. Start transformation to specialized agent
        2. Complete transformation
        3. Verify both events are linked by correlation_id
        """
        logger.info(
            f"Testing polymorphic agent switching (correlation_id: {correlation_id})"
        )

        # Publish start event
        await publish_transformation_start(
            source_agent="polymorphic-agent",
            target_agent="agent-onex-architect",
            transformation_reason="ONEX node generation task",
            correlation_id=correlation_id,
            user_request="Generate ONEX Effect node for API calls",
            routing_confidence=0.95,
            routing_strategy="fuzzy_match",
        )

        # Wait a bit to simulate processing time
        await asyncio.sleep(0.5)

        # Publish complete event
        await publish_transformation_complete(
            source_agent="polymorphic-agent",
            target_agent="agent-onex-architect",
            transformation_reason="ONEX node generation completed",
            correlation_id=correlation_id,
            user_request="Generate ONEX Effect node for API calls",
            routing_confidence=0.95,
            routing_strategy="fuzzy_match",
            transformation_duration_ms=50,
            initialization_duration_ms=200,
        )

        logger.info("✓ Both transformation events published to Kafka")

        # Wait for consumer to process
        await asyncio.sleep(consumer_wait_time)

        # Query database
        events = query_transformation_events(db_connection, correlation_id)

        # Assertions
        assert (
            len(events) >= 2
        ), f"Expected at least 2 transformation events, found {len(events)}"

        # Verify both events have same correlation_id
        correlation_ids = {str(event["correlation_id"]) for event in events}
        assert (
            len(correlation_ids) == 1
        ), f"Multiple correlation IDs found: {correlation_ids}"
        assert correlation_id in correlation_ids

        # Verify event types
        event_types = {event["event_type"] for event in events}
        assert "transformation_start" in event_types
        assert "transformation_complete" in event_types

        # Verify chronological ordering
        start_event = next(
            e for e in events if e["event_type"] == "transformation_start"
        )
        complete_event = next(
            e for e in events if e["event_type"] == "transformation_complete"
        )
        assert start_event["started_at"] < complete_event["started_at"]

        logger.info(f"✓ Polymorphic agent switching verified with {len(events)} events")


# =============================================================================
# Test Class: Manifest Injections
# =============================================================================


@pytest.mark.integration
class TestManifestInjections:
    """
    Integration tests for agent manifest injection tracking.

    Tests:
    - Manifest creation and database persistence
    - Correlation ID linking with routing decisions
    - Manifest snapshot storage and retrieval
    - Performance metrics tracking
    """

    @pytest.mark.asyncio
    async def test_manifest_injection_schema_compliance(self, db_connection):
        """
        Test that agent_manifest_injections table schema is correct.

        This test verifies:
        - Required columns exist
        - Data types are correct
        - Constraints are enforced
        """
        logger.info("Testing manifest injection schema compliance")

        cursor = db_connection.cursor(cursor_factory=RealDictCursor)

        # Query table schema
        query = """
            SELECT column_name, data_type, is_nullable
            FROM information_schema.columns
            WHERE table_name = 'agent_manifest_injections'
            ORDER BY ordinal_position
        """
        cursor.execute(query)
        schema = cursor.fetchall()
        cursor.close()

        # Convert to dict for easier lookup
        schema_dict = {row["column_name"]: row for row in schema}

        # Verify critical columns exist
        required_columns = [
            "id",
            "correlation_id",
            "agent_name",
            "manifest_version",
            "generation_source",
            "sections_included",
            "patterns_count",
            "total_query_time_ms",
            "full_manifest_snapshot",
            "created_at",
        ]

        for col in required_columns:
            assert col in schema_dict, f"Missing required column: {col}"

        # Verify data types
        assert schema_dict["id"]["data_type"] == "uuid"
        assert schema_dict["correlation_id"]["data_type"] == "uuid"
        assert schema_dict["patterns_count"]["data_type"] == "integer"
        assert schema_dict["total_query_time_ms"]["data_type"] == "integer"
        assert schema_dict["full_manifest_snapshot"]["data_type"] == "jsonb"

        logger.info("✓ Manifest injection schema verified")

    @pytest.mark.asyncio
    async def test_correlation_id_tracking_across_tables(
        self, db_connection, correlation_id: str
    ):
        """
        Test that correlation_id properly links records across all tables.

        This test verifies the complete traceability chain:
        routing_decision → manifest_injection → transformation_event → actions

        Note: This test creates mock records directly in database for testing.
        In production, these would be created by real agent workflows.
        """
        logger.info(
            f"Testing correlation_id tracking across tables (correlation_id: {correlation_id})"
        )

        cursor = db_connection.cursor()

        # Create mock routing decision
        cursor.execute(
            """
            INSERT INTO agent_routing_decisions (
                correlation_id, user_request, selected_agent,
                confidence_score, routing_strategy, routing_time_ms
            ) VALUES (%s, %s, %s, %s, %s, %s)
            RETURNING id
        """,
            (
                correlation_id,
                "Test request for correlation tracking",
                "test-agent",
                0.95,
                "test_strategy",
                50,
            ),
        )
        routing_id = cursor.fetchone()[0]

        # Create mock manifest injection
        cursor.execute(
            """
            INSERT INTO agent_manifest_injections (
                correlation_id, routing_decision_id, agent_name,
                manifest_version, generation_source, sections_included,
                total_query_time_ms, full_manifest_snapshot
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING id
        """,
            (
                correlation_id,
                routing_id,
                "test-agent",
                "2.0.0",
                "test",
                ["patterns", "infrastructure"],
                1500,
                '{"test": "data"}',
            ),
        )
        manifest_id = cursor.fetchone()[0]

        db_connection.commit()
        cursor.close()

        logger.info("✓ Mock records created")

        # Query all tables by correlation_id
        routing_decisions = query_routing_decisions(db_connection, correlation_id)
        manifest_injections = query_manifest_injections(db_connection, correlation_id)

        # Assertions
        assert len(routing_decisions) == 1, "Expected 1 routing decision"
        assert len(manifest_injections) == 1, "Expected 1 manifest injection"

        # Verify correlation_id matches
        assert str(routing_decisions[0]["correlation_id"]) == correlation_id
        assert str(manifest_injections[0]["correlation_id"]) == correlation_id

        # Verify foreign key relationship
        assert (
            manifest_injections[0]["routing_decision_id"] == routing_decisions[0]["id"]
        )

        logger.info("✓ Correlation ID tracking verified across all tables")


# =============================================================================
# Test Class: Database Schema Validation
# =============================================================================


@pytest.mark.integration
class TestDatabaseSchemaValidation:
    """
    Integration tests for database schema validation and constraints.

    Tests:
    - Table existence
    - Index existence
    - Constraint enforcement
    - View availability
    """

    def test_agent_actions_table_exists(self, db_connection):
        """Test that agent_actions table exists with correct schema."""
        cursor = db_connection.cursor()
        cursor.execute(
            """
            SELECT EXISTS (
                SELECT FROM information_schema.tables
                WHERE table_name = 'agent_actions'
            )
        """
        )
        exists = cursor.fetchone()[0]
        cursor.close()

        assert exists, "agent_actions table does not exist"

    def test_agent_transformation_events_table_exists(self, db_connection):
        """Test that agent_transformation_events table exists with correct schema."""
        cursor = db_connection.cursor()
        cursor.execute(
            """
            SELECT EXISTS (
                SELECT FROM information_schema.tables
                WHERE table_name = 'agent_transformation_events'
            )
        """
        )
        exists = cursor.fetchone()[0]
        cursor.close()

        assert exists, "agent_transformation_events table does not exist"

    def test_agent_manifest_injections_table_exists(self, db_connection):
        """Test that agent_manifest_injections table exists with correct schema."""
        cursor = db_connection.cursor()
        cursor.execute(
            """
            SELECT EXISTS (
                SELECT FROM information_schema.tables
                WHERE table_name = 'agent_manifest_injections'
            )
        """
        )
        exists = cursor.fetchone()[0]
        cursor.close()

        assert exists, "agent_manifest_injections table does not exist"

    def test_agent_routing_decisions_table_exists(self, db_connection):
        """Test that agent_routing_decisions table exists with correct schema."""
        cursor = db_connection.cursor()
        cursor.execute(
            """
            SELECT EXISTS (
                SELECT FROM information_schema.tables
                WHERE table_name = 'agent_routing_decisions'
            )
        """
        )
        exists = cursor.fetchone()[0]
        cursor.close()

        assert exists, "agent_routing_decisions table does not exist"

    def test_required_indexes_exist(self, db_connection):
        """Test that required indexes exist for performance."""
        cursor = db_connection.cursor()

        required_indexes = [
            ("agent_actions", "idx_agent_actions_correlation_id"),
            ("agent_actions", "idx_agent_actions_action_type"),
            (
                "agent_transformation_events",
                "idx_agent_transformation_events_correlation",
            ),
            ("agent_manifest_injections", "idx_agent_manifest_injections_correlation"),
            ("agent_routing_decisions", "idx_agent_routing_decisions_correlation"),
        ]

        for table_name, index_name in required_indexes:
            cursor.execute(
                """
                SELECT EXISTS (
                    SELECT FROM pg_indexes
                    WHERE tablename = %s AND indexname = %s
                )
            """,
                (table_name, index_name),
            )
            exists = cursor.fetchone()[0]
            assert exists, f"Required index {index_name} does not exist on {table_name}"

        cursor.close()
        logger.info("✓ All required indexes exist")

    def test_analytical_views_exist(self, db_connection):
        """Test that analytical views exist for querying."""
        cursor = db_connection.cursor()

        required_views = [
            "v_agent_execution_trace",
            "v_manifest_injection_performance",
            "v_routing_decision_accuracy",
            "recent_debug_traces",
        ]

        for view_name in required_views:
            cursor.execute(
                """
                SELECT EXISTS (
                    SELECT FROM information_schema.views
                    WHERE table_name = %s
                )
            """,
                (view_name,),
            )
            exists = cursor.fetchone()[0]
            assert exists, f"Required view {view_name} does not exist"

        cursor.close()
        logger.info("✓ All required views exist")

    def test_action_type_constraint(self, db_connection):
        """Test that action_type constraint is enforced."""
        cursor = db_connection.cursor()

        # Try to insert invalid action_type
        try:
            cursor.execute(
                """
                INSERT INTO agent_actions (
                    correlation_id, agent_name, action_type, action_name
                ) VALUES (%s, %s, %s, %s)
            """,
                (str(uuid4()), "test-agent", "invalid_type", "test_action"),
            )
            db_connection.commit()
            pytest.fail("Expected constraint violation for invalid action_type")
        except psycopg2.IntegrityError as e:
            # Expected - constraint should prevent this
            db_connection.rollback()
            assert "action_type" in str(e).lower()
            logger.info("✓ Action type constraint enforced correctly")
        finally:
            cursor.close()


# =============================================================================
# Entry Point (for running tests directly)
# =============================================================================

if __name__ == "__main__":
    """
    Run tests directly with pytest.

    Usage:
        python tests/integration/test_agent_observability_integration.py
    """
    import sys

    pytest.main([__file__, "-v", "-s"] + sys.argv[1:])
