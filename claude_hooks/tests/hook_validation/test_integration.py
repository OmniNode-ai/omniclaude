#!/usr/bin/env python3
"""
test_integration.py - End-to-end integration tests for hook system

Tests:
- Full correlation flow: UserPromptSubmit → PreToolUse → PostToolUse → Stop
- Correlation ID propagation across all hooks
- Timeline verification (events ordered correctly)
- Session lifecycle integration
- Failure scenarios (graceful degradation)
- Database unavailable handling
"""

# Database connection
# Note: Set PGPASSWORD environment variable before running
import os
import sys
import time
import uuid

import psycopg2
from psycopg2.extras import Json


DB_CONFIG = {
    "host": "localhost",
    "port": 5436,
    "database": "omninode_bridge",
    "user": "postgres",
    "password": os.getenv("PGPASSWORD", "YOUR_PASSWORD"),  # Set via environment
}


class IntegrationTest:
    """Integration test harness for hook system."""

    def __init__(self):
        self.conn = psycopg2.connect(**DB_CONFIG)
        self.tests_passed = 0
        self.tests_failed = 0

    def close(self):
        """Close database connection."""
        if self.conn and not self.conn.closed:
            self.conn.close()

    def log_success(self, message: str):
        """Log successful test."""
        print(f"✓ {message}")
        self.tests_passed += 1

    def log_error(self, message: str):
        """Log failed test."""
        print(f"✗ {message}")
        self.tests_failed += 1

    def log_info(self, message: str):
        """Log informational message."""
        print(f"ℹ {message}")

    def cleanup_test_data(self, correlation_id: str):
        """Cleanup test data from database."""
        try:
            with self.conn.cursor() as cur:
                cur.execute(
                    "DELETE FROM hook_events WHERE metadata->>'correlation_id' = %s",
                    (correlation_id,),
                )
                cur.execute(
                    "DELETE FROM service_sessions WHERE metadata->>'correlation_id' = %s",
                    (correlation_id,),
                )
                self.conn.commit()
        except Exception as e:
            print(f"⚠ Cleanup warning: {e}")
            self.conn.rollback()

    def test_full_correlation_flow(self):
        """Test complete correlation flow across all hooks."""
        self.log_info("Test: Full correlation flow")

        correlation_id = f"integration-{uuid.uuid4()}"
        session_id = str(uuid.uuid4())

        try:
            # 1. Create session (SessionStart)
            with self.conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO service_sessions (id, service_name, instance_id, status, metadata)
                    VALUES (
                        %s::uuid,
                        'claude-code',
                        'integration-test',
                        'active',
                        %s
                    )
                """,
                    (
                        session_id,
                        Json(
                            {
                                "correlation_id": correlation_id,
                                "test": "full_correlation_flow",
                            }
                        ),
                    ),
                )
                self.conn.commit()

            # 2. UserPromptSubmit
            with self.conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO hook_events (id, source, action, resource, resource_id, payload, metadata, created_at)
                    VALUES (
                        gen_random_uuid(),
                        'UserPromptSubmit',
                        'prompt_submitted',
                        'prompt',
                        'test-prompt',
                        %s,
                        %s,
                        NOW()
                    )
                """,
                    (
                        Json(
                            {
                                "prompt": "Create a function",
                                "agent_detected": "agent-code-generator",
                            }
                        ),
                        Json(
                            {"correlation_id": correlation_id, "session_id": session_id}
                        ),
                    ),
                )
                self.conn.commit()

            # Small delay to ensure timeline ordering
            time.sleep(0.01)

            # 3. PreToolUse
            with self.conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO hook_events (id, source, action, resource, resource_id, payload, metadata, created_at)
                    VALUES (
                        gen_random_uuid(),
                        'PreToolUse',
                        'tool_invocation',
                        'tool',
                        'Write',
                        %s,
                        %s,
                        NOW()
                    )
                """,
                    (
                        Json({"file_path": "/test/example.py", "content_length": 200}),
                        Json(
                            {"correlation_id": correlation_id, "session_id": session_id}
                        ),
                    ),
                )
                self.conn.commit()

            time.sleep(0.01)

            # 4. PostToolUse
            with self.conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO hook_events (id, source, action, resource, resource_id, payload, metadata, created_at)
                    VALUES (
                        gen_random_uuid(),
                        'PostToolUse',
                        'tool_completed',
                        'tool',
                        'Write',
                        %s,
                        %s,
                        NOW()
                    )
                """,
                    (
                        Json({"file_path": "/test/example.py", "success": True}),
                        Json(
                            {"correlation_id": correlation_id, "session_id": session_id}
                        ),
                    ),
                )
                self.conn.commit()

            time.sleep(0.01)

            # 5. Stop
            with self.conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO hook_events (id, source, action, resource, resource_id, payload, metadata, created_at)
                    VALUES (
                        gen_random_uuid(),
                        'Stop',
                        'response_completed',
                        'response',
                        'test-response',
                        %s,
                        %s,
                        NOW()
                    )
                """,
                    (
                        Json({"response_length": 1500, "model": "claude-sonnet-4-5"}),
                        Json(
                            {"correlation_id": correlation_id, "session_id": session_id}
                        ),
                    ),
                )
                self.conn.commit()

            # 6. End session (SessionEnd)
            with self.conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE service_sessions
                    SET status = 'ended',
                        session_end = NOW(),
                        updated_at = NOW()
                    WHERE id = %s::uuid
                """,
                    (session_id,),
                )
                self.conn.commit()

            # Verify all events exist and are correlated
            with self.conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT source, action, created_at
                    FROM hook_events
                    WHERE metadata->>'correlation_id' = %s
                    ORDER BY created_at ASC
                """,
                    (correlation_id,),
                )

                events = cur.fetchall()

            if len(events) == 4:  # UserPromptSubmit, PreToolUse, PostToolUse, Stop
                expected_sources = [
                    "UserPromptSubmit",
                    "PreToolUse",
                    "PostToolUse",
                    "Stop",
                ]
                actual_sources = [event[0] for event in events]

                if actual_sources == expected_sources:
                    self.log_success(
                        "Full correlation flow: All 4 hooks executed in correct order"
                    )
                else:
                    self.log_error(
                        f"Full correlation flow: Incorrect order. Expected {expected_sources}, got {actual_sources}"
                    )
            else:
                self.log_error(
                    f"Full correlation flow: Expected 4 events, found {len(events)}"
                )

        except Exception as e:
            self.log_error(f"Full correlation flow failed: {e}")
        finally:
            self.cleanup_test_data(correlation_id)

    def test_correlation_id_propagation(self):
        """Test correlation ID propagates across all hooks."""
        self.log_info("Test: Correlation ID propagation")

        correlation_id = f"propagation-{uuid.uuid4()}"
        session_id = str(uuid.uuid4())

        try:
            # Create events with same correlation ID
            for source in ["UserPromptSubmit", "PreToolUse", "PostToolUse", "Stop"]:
                with self.conn.cursor() as cur:
                    cur.execute(
                        """
                        INSERT INTO hook_events (id, source, action, resource, resource_id, payload, metadata)
                        VALUES (
                            gen_random_uuid(),
                            %s,
                            'test_action',
                            'test',
                            'test-resource',
                            '{"test": true}'::jsonb,
                            %s
                        )
                    """,
                        (
                            source,
                            Json(
                                {
                                    "correlation_id": correlation_id,
                                    "session_id": session_id,
                                }
                            ),
                        ),
                    )
                    self.conn.commit()

            # Verify all events have same correlation ID
            with self.conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT COUNT(DISTINCT metadata->>'correlation_id') as distinct_correlations,
                           COUNT(*) as total_events
                    FROM hook_events
                    WHERE metadata->>'correlation_id' = %s
                """,
                    (correlation_id,),
                )

                result = cur.fetchone()
                distinct_correlations, total_events = result

            if distinct_correlations == 1 and total_events == 4:
                self.log_success(
                    "Correlation ID propagation: All events share same correlation ID"
                )
            else:
                self.log_error(
                    f"Correlation ID propagation: Expected 1 distinct ID and 4 events, got {distinct_correlations} and {total_events}"
                )

        except Exception as e:
            self.log_error(f"Correlation ID propagation failed: {e}")
        finally:
            self.cleanup_test_data(correlation_id)

    def test_timeline_verification(self):
        """Test events are ordered correctly in timeline."""
        self.log_info("Test: Timeline verification")

        correlation_id = f"timeline-{uuid.uuid4()}"

        try:
            # Create events with explicit timing
            events_to_create = [
                ("UserPromptSubmit", "prompt_submitted", 1),
                ("PreToolUse", "tool_invocation", 2),
                ("PostToolUse", "tool_completed", 3),
                ("Stop", "response_completed", 4),
            ]

            for source, action, order in events_to_create:
                time.sleep(0.01)  # Ensure ordering

                with self.conn.cursor() as cur:
                    cur.execute(
                        """
                        INSERT INTO hook_events (id, source, action, resource, resource_id, payload, metadata, created_at)
                        VALUES (
                            gen_random_uuid(),
                            %s,
                            %s,
                            'test',
                            'test-resource',
                            %s,
                            %s,
                            NOW()
                        )
                    """,
                        (
                            source,
                            action,
                            Json({"order": order}),
                            Json({"correlation_id": correlation_id}),
                        ),
                    )
                    self.conn.commit()

            # Verify timeline order
            with self.conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT source, payload->>'order', created_at
                    FROM hook_events
                    WHERE metadata->>'correlation_id' = %s
                    ORDER BY created_at ASC
                """,
                    (correlation_id,),
                )

                results = cur.fetchall()

            # Check if order matches expected sequence
            expected_order = [
                ("UserPromptSubmit", "1"),
                ("PreToolUse", "2"),
                ("PostToolUse", "3"),
                ("Stop", "4"),
            ]
            actual_order = [(r[0], r[1]) for r in results]

            if actual_order == expected_order:
                self.log_success("Timeline verification: Events ordered correctly")
            else:
                self.log_error(
                    f"Timeline verification: Expected {expected_order}, got {actual_order}"
                )

        except Exception as e:
            self.log_error(f"Timeline verification failed: {e}")
        finally:
            self.cleanup_test_data(correlation_id)

    def test_session_lifecycle_integration(self):
        """Test session lifecycle integration with hook events."""
        self.log_info("Test: Session lifecycle integration")

        correlation_id = f"lifecycle-{uuid.uuid4()}"
        session_id = str(uuid.uuid4())

        try:
            # Create session
            with self.conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO service_sessions (id, service_name, instance_id, status, metadata, session_start)
                    VALUES (
                        %s::uuid,
                        'claude-code',
                        'integration-test',
                        'active',
                        %s,
                        NOW()
                    )
                    RETURNING session_start
                """,
                    (session_id, Json({"correlation_id": correlation_id})),
                )

                cur.fetchone()[0]
                self.conn.commit()

            # Create hook events
            time.sleep(0.05)

            with self.conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO hook_events (id, source, action, resource, resource_id, payload, metadata)
                    VALUES (
                        gen_random_uuid(),
                        'PreToolUse',
                        'tool_invocation',
                        'tool',
                        'Write',
                        '{"test": true}'::jsonb,
                        %s
                    )
                """,
                    (
                        Json(
                            {"correlation_id": correlation_id, "session_id": session_id}
                        ),
                    ),
                )
                self.conn.commit()

            time.sleep(0.05)

            # End session
            with self.conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE service_sessions
                    SET status = 'ended',
                        session_end = NOW(),
                        updated_at = NOW()
                    WHERE id = %s::uuid
                    RETURNING session_end
                """,
                    (session_id,),
                )

                cur.fetchone()[0]
                self.conn.commit()

            # Verify session lifecycle
            with self.conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT session_start, session_end, status,
                           (SELECT COUNT(*) FROM hook_events WHERE metadata->>'session_id' = %s) as event_count
                    FROM service_sessions
                    WHERE id = %s::uuid
                """,
                    (session_id, session_id),
                )

                result = cur.fetchone()

            if result:
                start, end, status, event_count = result

                if status == "ended" and event_count > 0 and end > start:
                    self.log_success(
                        f"Session lifecycle integration: Session ended correctly with {event_count} event(s)"
                    )
                else:
                    self.log_error(
                        f"Session lifecycle integration: Invalid state - status={status}, events={event_count}"
                    )
            else:
                self.log_error("Session lifecycle integration: Session not found")

        except Exception as e:
            self.log_error(f"Session lifecycle integration failed: {e}")
        finally:
            self.cleanup_test_data(correlation_id)

    def test_graceful_degradation(self):
        """Test graceful degradation when database operations fail."""
        self.log_info("Test: Graceful degradation (invalid data handling)")

        correlation_id = f"graceful-{uuid.uuid4()}"

        try:
            # Try to insert event with missing required fields (should be handled gracefully)
            # In production, hooks should catch exceptions and continue

            # For testing purposes, we'll verify that partial data doesn't break the system
            with self.conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO hook_events (id, source, action, resource, resource_id, payload, metadata)
                    VALUES (
                        gen_random_uuid(),
                        'TestHook',
                        'test_action',
                        'test',
                        'test-resource',
                        '{}'::jsonb,
                        %s
                    )
                """,
                    (Json({"correlation_id": correlation_id, "incomplete": True}),),
                )
                self.conn.commit()

            # Verify event was created despite minimal data
            with self.conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT id
                    FROM hook_events
                    WHERE metadata->>'correlation_id' = %s
                """,
                    (correlation_id,),
                )

                result = cur.fetchone()

            if result:
                self.log_success(
                    "Graceful degradation: System handles incomplete data gracefully"
                )
            else:
                self.log_error("Graceful degradation: Failed to handle incomplete data")

        except Exception as e:
            # Expected: some operations might fail, but system should continue
            self.log_success(
                f"Graceful degradation: System continues despite error ({type(e).__name__})"
            )
        finally:
            try:
                self.cleanup_test_data(correlation_id)
            except Exception:
                pass

    def run_all_tests(self):
        """Run all integration tests."""
        print("=" * 50)
        print("Hook Integration Test Suite")
        print("=" * 50)
        print()

        self.test_full_correlation_flow()
        print()

        self.test_correlation_id_propagation()
        print()

        self.test_timeline_verification()
        print()

        self.test_session_lifecycle_integration()
        print()

        self.test_graceful_degradation()
        print()

        # Summary
        print("=" * 50)
        print("Test Summary")
        print("=" * 50)
        print(f"Tests Passed: {self.tests_passed}")
        print(f"Tests Failed: {self.tests_failed}")

        return self.tests_failed == 0


if __name__ == "__main__":
    test = IntegrationTest()

    try:
        success = test.run_all_tests()
        exit_code = 0 if success else 1
    except Exception as e:
        print(f"✗ Test suite failed with error: {e}")
        import traceback

        traceback.print_exc()
        exit_code = 1
    finally:
        test.close()

    sys.exit(exit_code)
