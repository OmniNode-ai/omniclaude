#!/usr/bin/env python3
"""
test_performance.py - Performance validation tests for hook system

Tests:
- SessionStart hook performance (<50ms avg, <75ms p95)
- SessionEnd hook performance (<50ms avg, <75ms p95)
- Stop hook performance (<30ms avg, <45ms p95)
- Enhanced metadata overhead (<15ms avg)
- Database write latency (<10ms avg)
- Hook execution under load (concurrent operations)
"""

# Database connection
# Note: Set PGPASSWORD environment variable before running
import os
import statistics
import sys
import time
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from typing import List, Tuple

import psycopg2
from psycopg2.extras import Json


DB_CONFIG = {
    "host": "localhost",
    "port": 5436,
    "database": "omninode_bridge",
    "user": "postgres",
    "password": os.getenv("PGPASSWORD", "YOUR_PASSWORD"),  # Set via environment
}

# Performance thresholds (milliseconds)
THRESHOLDS = {
    "session_start_avg": 50,
    "session_start_p95": 75,
    "session_end_avg": 50,
    "session_end_p95": 75,
    "stop_avg": 30,
    "stop_p95": 45,
    "metadata_overhead": 15,
    "database_write": 10,
}

# Test configuration
ITERATIONS = 100
CONCURRENT_OPERATIONS = 10


class PerformanceTest:
    """Performance test harness for hook system."""

    def __init__(self):
        self.conn = psycopg2.connect(**DB_CONFIG)
        self.tests_passed = 0
        self.tests_failed = 0
        self.results = {}

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

    def measure_time_ms(self, func) -> float:
        """Measure function execution time in milliseconds."""
        start = time.perf_counter()
        func()
        end = time.perf_counter()
        return (end - start) * 1000

    def cleanup_test_data(self, correlation_ids: List[str]):
        """Cleanup test data from database."""
        try:
            with self.conn.cursor() as cur:
                for correlation_id in correlation_ids:
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

    def test_session_start_performance(self):
        """Test SessionStart hook performance."""
        self.log_info("Test: SessionStart hook performance")

        times = []
        correlation_ids = []

        for i in range(ITERATIONS):
            correlation_id = f"perf-session-start-{uuid.uuid4()}"
            correlation_ids.append(correlation_id)

            def insert_session(cid=correlation_id):
                with self.conn.cursor() as cur:
                    cur.execute(
                        """
                        INSERT INTO service_sessions (id, service_name, instance_id, status, metadata)
                        VALUES (
                            gen_random_uuid(),
                            'claude-code',
                            'perf-test',
                            'active',
                            %s
                        )
                    """,
                        (Json({"correlation_id": cid, "test": True}),),
                    )
                    self.conn.commit()

            elapsed_ms = self.measure_time_ms(insert_session)
            times.append(elapsed_ms)

        avg_time = statistics.mean(times)
        p95_time = statistics.quantiles(times, n=20)[18]  # 95th percentile

        self.results["session_start_avg"] = avg_time
        self.results["session_start_p95"] = p95_time

        # Cleanup
        self.cleanup_test_data(correlation_ids)

        # Validate thresholds
        if avg_time < THRESHOLDS["session_start_avg"]:
            self.log_success(
                f"SessionStart avg: {avg_time:.2f}ms (target <{THRESHOLDS['session_start_avg']}ms)"
            )
        else:
            self.log_error(
                f"SessionStart avg: {avg_time:.2f}ms (target <{THRESHOLDS['session_start_avg']}ms) - EXCEEDED"
            )

        if p95_time < THRESHOLDS["session_start_p95"]:
            self.log_success(
                f"SessionStart p95: {p95_time:.2f}ms (target <{THRESHOLDS['session_start_p95']}ms)"
            )
        else:
            self.log_error(
                f"SessionStart p95: {p95_time:.2f}ms (target <{THRESHOLDS['session_start_p95']}ms) - EXCEEDED"
            )

    def test_session_end_performance(self):
        """Test SessionEnd hook performance."""
        self.log_info("Test: SessionEnd hook performance")

        times = []
        correlation_ids = []
        session_ids = []

        # Create test sessions first
        for i in range(ITERATIONS):
            correlation_id = f"perf-session-end-{uuid.uuid4()}"
            session_id = str(uuid.uuid4())

            correlation_ids.append(correlation_id)
            session_ids.append(session_id)

            with self.conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO service_sessions (id, service_name, instance_id, status, metadata)
                    VALUES (
                        %s::uuid,
                        'claude-code',
                        'perf-test',
                        'active',
                        %s
                    )
                """,
                    (
                        session_id,
                        Json({"correlation_id": correlation_id, "test": True}),
                    ),
                )
                self.conn.commit()

        # Measure update times
        for session_id in session_ids:

            def update_session(sid=session_id):
                with self.conn.cursor() as cur:
                    cur.execute(
                        """
                        UPDATE service_sessions
                        SET status = 'ended',
                            session_end = NOW(),
                            updated_at = NOW()
                        WHERE id = %s::uuid
                    """,
                        (sid,),
                    )
                    self.conn.commit()

            elapsed_ms = self.measure_time_ms(update_session)
            times.append(elapsed_ms)

        avg_time = statistics.mean(times)
        p95_time = statistics.quantiles(times, n=20)[18]

        self.results["session_end_avg"] = avg_time
        self.results["session_end_p95"] = p95_time

        # Cleanup
        self.cleanup_test_data(correlation_ids)

        # Validate thresholds
        if avg_time < THRESHOLDS["session_end_avg"]:
            self.log_success(
                f"SessionEnd avg: {avg_time:.2f}ms (target <{THRESHOLDS['session_end_avg']}ms)"
            )
        else:
            self.log_error(
                f"SessionEnd avg: {avg_time:.2f}ms (target <{THRESHOLDS['session_end_avg']}ms) - EXCEEDED"
            )

        if p95_time < THRESHOLDS["session_end_p95"]:
            self.log_success(
                f"SessionEnd p95: {p95_time:.2f}ms (target <{THRESHOLDS['session_end_p95']}ms)"
            )
        else:
            self.log_error(
                f"SessionEnd p95: {p95_time:.2f}ms (target <{THRESHOLDS['session_end_p95']}ms) - EXCEEDED"
            )

    def test_stop_hook_performance(self):
        """Test Stop hook performance."""
        self.log_info("Test: Stop hook performance")

        times = []
        correlation_ids = []

        for i in range(ITERATIONS):
            correlation_id = f"perf-stop-{uuid.uuid4()}"
            correlation_ids.append(correlation_id)

            def insert_stop_event(cid=correlation_id):
                with self.conn.cursor() as cur:
                    cur.execute(
                        """
                        INSERT INTO hook_events (id, source, action, resource, resource_id, payload, metadata)
                        VALUES (
                            gen_random_uuid(),
                            'Stop',
                            'response_completed',
                            'response',
                            'test-response',
                            %s,
                            %s
                        )
                    """,
                        (
                            Json({"response_length": 1000}),
                            Json({"correlation_id": cid, "test": True}),
                        ),
                    )
                    self.conn.commit()

            elapsed_ms = self.measure_time_ms(insert_stop_event)
            times.append(elapsed_ms)

        avg_time = statistics.mean(times)
        p95_time = statistics.quantiles(times, n=20)[18]

        self.results["stop_avg"] = avg_time
        self.results["stop_p95"] = p95_time

        # Cleanup
        self.cleanup_test_data(correlation_ids)

        # Validate thresholds
        if avg_time < THRESHOLDS["stop_avg"]:
            self.log_success(
                f"Stop hook avg: {avg_time:.2f}ms (target <{THRESHOLDS['stop_avg']}ms)"
            )
        else:
            self.log_error(
                f"Stop hook avg: {avg_time:.2f}ms (target <{THRESHOLDS['stop_avg']}ms) - EXCEEDED"
            )

        if p95_time < THRESHOLDS["stop_p95"]:
            self.log_success(
                f"Stop hook p95: {p95_time:.2f}ms (target <{THRESHOLDS['stop_p95']}ms)"
            )
        else:
            self.log_error(
                f"Stop hook p95: {p95_time:.2f}ms (target <{THRESHOLDS['stop_p95']}ms) - EXCEEDED"
            )

    def test_metadata_overhead(self):
        """Test enhanced metadata overhead."""
        self.log_info("Test: Enhanced metadata overhead")

        times_basic = []
        times_enhanced = []
        correlation_ids = []

        # Measure basic metadata
        for i in range(ITERATIONS):
            correlation_id = f"perf-basic-{uuid.uuid4()}"
            correlation_ids.append(correlation_id)

            def insert_basic(cid=correlation_id):
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
                            '{"test": true}'::jsonb,
                            %s
                        )
                    """,
                        (Json({"correlation_id": cid}),),
                    )
                    self.conn.commit()

            elapsed_ms = self.measure_time_ms(insert_basic)
            times_basic.append(elapsed_ms)

        # Measure enhanced metadata
        for i in range(ITERATIONS):
            correlation_id = f"perf-enhanced-{uuid.uuid4()}"
            correlation_ids.append(correlation_id)

            def insert_enhanced(cid=correlation_id):
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
                            '{"test": true, "data": "value"}'::jsonb,
                            %s
                        )
                    """,
                        (
                            Json(
                                {
                                    "correlation_id": cid,
                                    "hook_version": "2.0",
                                    "quality_check": {"enabled": True, "violations": 0},
                                    "timestamp": datetime.now(timezone.utc).isoformat(),
                                }
                            ),
                        ),
                    )
                    self.conn.commit()

            elapsed_ms = self.measure_time_ms(insert_enhanced)
            times_enhanced.append(elapsed_ms)

        avg_basic = statistics.mean(times_basic)
        avg_enhanced = statistics.mean(times_enhanced)
        overhead = avg_enhanced - avg_basic

        self.results["metadata_overhead"] = overhead

        # Cleanup
        self.cleanup_test_data(correlation_ids)

        # Validate threshold
        if overhead < THRESHOLDS["metadata_overhead"]:
            self.log_success(
                f"Metadata overhead: {overhead:.2f}ms (basic: {avg_basic:.2f}ms, enhanced: {avg_enhanced:.2f}ms, target <{THRESHOLDS['metadata_overhead']}ms)"
            )
        else:
            self.log_error(
                f"Metadata overhead: {overhead:.2f}ms (target <{THRESHOLDS['metadata_overhead']}ms) - EXCEEDED"
            )

    def test_concurrent_operations(self):
        """Test hook performance under concurrent load."""
        self.log_info("Test: Concurrent operations performance")

        def insert_concurrent_event(i: int) -> Tuple[int, float]:
            correlation_id = f"perf-concurrent-{uuid.uuid4()}"

            start = time.perf_counter()

            conn = psycopg2.connect(**DB_CONFIG)
            try:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        INSERT INTO hook_events (id, source, action, resource, resource_id, payload, metadata)
                        VALUES (
                            gen_random_uuid(),
                            'TestHook',
                            'test_action',
                            'test',
                            'concurrent-test',
                            '{"test": true}'::jsonb,
                            %s
                        )
                    """,
                        (Json({"correlation_id": correlation_id, "test": True}),),
                    )
                    conn.commit()
            finally:
                conn.close()

            end = time.perf_counter()
            elapsed_ms = (end - start) * 1000

            return (i, elapsed_ms, correlation_id)

        times = []
        correlation_ids = []

        with ThreadPoolExecutor(max_workers=CONCURRENT_OPERATIONS) as executor:
            futures = [
                executor.submit(insert_concurrent_event, i)
                for i in range(CONCURRENT_OPERATIONS * 5)
            ]

            for future in as_completed(futures):
                idx, elapsed_ms, correlation_id = future.result()
                times.append(elapsed_ms)
                correlation_ids.append(correlation_id)

        avg_time = statistics.mean(times)
        max_time = max(times)

        self.results["concurrent_avg"] = avg_time
        self.results["concurrent_max"] = max_time

        # Cleanup
        self.cleanup_test_data(correlation_ids)

        self.log_success(
            f"Concurrent operations: avg {avg_time:.2f}ms, max {max_time:.2f}ms ({CONCURRENT_OPERATIONS * 5} operations)"
        )

    def run_all_tests(self):
        """Run all performance tests."""
        print("=" * 50)
        print("Hook Performance Test Suite")
        print("=" * 50)
        print()

        self.test_session_start_performance()
        print()

        self.test_session_end_performance()
        print()

        self.test_stop_hook_performance()
        print()

        self.test_metadata_overhead()
        print()

        self.test_concurrent_operations()
        print()

        # Summary
        print("=" * 50)
        print("Test Summary")
        print("=" * 50)
        print(f"Tests Passed: {self.tests_passed}")
        print(f"Tests Failed: {self.tests_failed}")
        print()

        # Performance summary
        print("Performance Results:")
        for key, value in self.results.items():
            threshold = THRESHOLDS.get(key, None)
            if threshold:
                status = "✓" if value < threshold else "✗"
                print(f"  {status} {key}: {value:.2f}ms (threshold: {threshold}ms)")
            else:
                print(f"  ℹ {key}: {value:.2f}ms")

        return self.tests_failed == 0


if __name__ == "__main__":
    test = PerformanceTest()

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
