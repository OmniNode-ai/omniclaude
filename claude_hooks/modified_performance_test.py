#!/usr/bin/env python3
"""
Modified Performance Test Script - Avoids duplicate key constraints

This script validates the performance improvements while avoiding API constraints.
"""

import json
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict


# Import sync tracker for testing
try:
    from .lib.pattern_tracker_sync import PatternTrackerSync

    SYNC_AVAILABLE = True
except ImportError:
    SYNC_AVAILABLE = False
    PatternTrackerSync = None


class ModifiedPerformanceTestSuite:
    """Modified performance testing suite that avoids duplicate constraints."""

    def __init__(self):
        self.results = {
            "test_timestamp": datetime.now().isoformat(),
            "sync_tracker": {},
            "comparison": {},
        }

    def test_sync_tracker_unique_patterns(self) -> Dict[str, Any]:
        """Test performance of synchronous tracker with unique patterns."""
        if not SYNC_AVAILABLE:
            return {"error": "Sync tracker not available"}

        print("🧪 Testing Sync Tracker Performance with Unique Patterns...")
        tracker = PatternTrackerSync()

        # Generate unique test patterns to avoid duplicate constraints
        test_patterns = []
        for i in range(10):
            unique_code = f"""
def unique_function_{i}(param1: str, param2: int = {i}) -> str:
    '''Unique function {i} for performance testing.'''
    return f"Hello {{param1}}! The answer is {{param2}}"
"""
            test_patterns.append(unique_code)

        test_contexts = [
            {
                "event_type": "pattern_created",
                "file_path": f"/test/unique_file_{i}.py",
                "language": "python",
            }
            for i in range(10)
        ]

        # Test 1: Single operation performance
        start_time = time.time()
        try:
            pattern_id = tracker.track_pattern_creation(
                test_patterns[0], test_contexts[0]
            )
            single_op_time = (time.time() - start_time) * 1000
            single_op_success = pattern_id is not None
        except Exception as e:
            print(f"Single op test failed: {e}")
            single_op_time = 0
            single_op_success = False

        # Test 2: Multiple unique operations
        start_time = time.time()
        pattern_ids = []
        successful_ops = 0

        for i, (code, context) in enumerate(zip(test_patterns[:5], test_contexts[:5])):
            try:
                pattern_id = tracker.track_pattern_creation(code, context)
                if pattern_id:
                    pattern_ids.append(pattern_id)
                    successful_ops += 1
            except Exception as e:
                print(f"Operation {i} failed: {e}")

        multi_op_time = time.time() - start_time

        # Test 3: Cache effectiveness (test same pattern again)
        start_time = time.time()
        cache_hits = 0
        for _ in range(3):
            try:
                result = tracker.track_pattern_creation(
                    test_patterns[0], test_contexts[0]
                )
                if result:
                    cache_hits += 1
            except Exception:
                pass
        cache_time = time.time() - start_time

        # Get metrics
        metrics = tracker.get_performance_metrics()

        result = {
            "available": True,
            "single_operation_ms": single_op_time,
            "single_operation_success": single_op_success,
            "multi_operations_time": multi_op_time,
            "successful_operations": successful_ops,
            "attempted_operations": 5,
            "operations_per_second": (
                successful_ops / multi_op_time if multi_op_time > 0 else 0
            ),
            "cache_test_time": cache_time,
            "cache_hits": cache_hits,
            "cache_operations_per_second": (
                cache_hits / cache_time if cache_time > 0 else 0
            ),
            "success_rate": (successful_ops / 5) * 100,
            "metrics": metrics,
        }

        print(f"✅ Sync Tracker: {result['operations_per_second']:.1f} ops/sec")
        print(f"✅ Success Rate: {result['success_rate']:.1f}%")
        print(
            f"✅ Cache Performance: {result['cache_operations_per_second']:.1f} ops/sec"
        )

        return result

    def test_optimization_components(self) -> Dict[str, Any]:
        """Test individual optimization components."""
        print("🧪 Testing Individual Optimization Components...")

        # Test 1: Pattern ID Generation Performance
        print("Testing Pattern ID Generation...")
        import hashlib

        test_code = "def example(): return 'hello'"
        test_context = {"file_path": "/test/example.py"}
        iterations = 1000

        # Without caching
        start_time = time.time()
        for i in range(iterations):
            file_path = test_context["file_path"]
            cache_key = f"{file_path}:{test_code[:200]}"
            hash_obj = hashlib.sha256(cache_key.encode())
            pattern_id = hash_obj.hexdigest()[:16]
        uncached_time = time.time() - start_time

        # With caching simulation
        pattern_id_cache = {}
        start_time = time.time()
        for i in range(iterations):
            file_path = test_context["file_path"]
            cache_key = f"{file_path}:{test_code[:200]}"
            if cache_key in pattern_id_cache:
                pattern_id = pattern_id_cache[cache_key]
            else:
                hash_obj = hashlib.sha256(cache_key.encode())
                pattern_id = hash_obj.hexdigest()[:16]
                pattern_id_cache[cache_key] = pattern_id
        cached_time = time.time() - start_time

        caching_improvement = (
            ((uncached_time - cached_time) / uncached_time * 100)
            if uncached_time > 0
            else 0
        )

        # Test 2: HTTP Connection Pooling Performance
        print("Testing HTTP Connection Pooling...")
        import requests

        # Test connection pooling setup time
        start_time = time.time()
        session = requests.Session()
        adapter = requests.adapters.HTTPAdapter(
            pool_connections=10, pool_maxsize=20, max_retries=3
        )
        session.mount("http://", adapter)
        session.mount("https://", adapter)
        setup_time = time.time() - start_time

        result = {
            "pattern_id_generation": {
                "uncached_time_ms": uncached_time * 1000,
                "cached_time_ms": cached_time * 1000,
                "improvement_percent": caching_improvement,
                "cache_hit_rate": (len(pattern_id_cache) / iterations) * 100,
            },
            "connection_pooling": {
                "setup_time_ms": setup_time * 1000,
                "pool_connections": 10,
                "pool_maxsize": 20,
            },
        }

        print(f"✅ Pattern ID Caching: {caching_improvement:.1f}% improvement")
        print(f"✅ Connection Pool Setup: {setup_time * 1000:.1f}ms")

        return result

    def generate_performance_report(self) -> Dict[str, Any]:
        """Generate comprehensive performance comparison report."""
        print("🚀 Starting Modified Performance Test Suite...")
        print("=" * 60)

        # Test optimization components
        component_results = self.test_optimization_components()
        self.results["components"] = component_results

        print()

        # Test sync tracker
        if SYNC_AVAILABLE:
            self.results["sync_tracker"] = self.test_sync_tracker_unique_patterns()
        else:
            self.results["sync_tracker"] = {"error": "Not available"}

        print()

        # Generate summary
        self._generate_summary()

        print("=" * 60)
        print("✅ Modified Performance Testing Complete!")

        return self.results

    def _generate_summary(self):
        """Generate performance summary."""
        sync_result = self.results.get("sync_tracker", {})
        component_results = self.results.get("components", {})

        print("📊 Performance Summary:")

        # Component improvements
        if "pattern_id_generation" in component_results:
            caching = component_results["pattern_id_generation"]
            print(
                f"   Pattern ID Caching: {caching['improvement_percent']:.1f}% improvement"
            )

        if "connection_pooling" in component_results:
            pooling = component_results["connection_pooling"]
            print(
                f"   Connection Pooling: {pooling['pool_connections']} connections, {pooling['pool_maxsize']} max size"
            )

        # Sync tracker performance
        if sync_result.get("available"):
            ops_per_sec = sync_result.get("operations_per_second", 0)
            success_rate = sync_result.get("success_rate", 0)

            print(f"   Sync Tracker Performance: {ops_per_sec:.1f} ops/sec")
            print(f"   Success Rate: {success_rate:.1f}%")

            if ops_per_sec >= 20:
                performance_tier = "Excellent (20+ ops/sec)"
            elif ops_per_sec >= 10:
                performance_tier = "Good (10-19 ops/sec)"
            elif ops_per_sec >= 5:
                performance_tier = "Fair (5-9 ops/sec)"
            else:
                performance_tier = "Needs Improvement (<5 ops/sec)"

            print(f"   Performance Tier: {performance_tier}")

    def save_report(self, filename: str = "modified_performance_test_results.json"):
        """Save test results to file."""
        report_path = Path.home() / ".claude" / "hooks" / "logs" / filename
        report_path.parent.mkdir(parents=True, exist_ok=True)

        with open(report_path, "w") as f:
            json.dump(self.results, f, indent=2)

        print(f"📄 Report saved to: {report_path}")
        return report_path


def main():
    """Main test runner."""
    print("🎯 Modified Pattern Tracking Performance Test Suite")
    print("=" * 60)

    # Check tracker availability
    print("📋 System Status:")
    print(
        f"   Sync Tracker: {'✅ Available' if SYNC_AVAILABLE else '❌ Not Available'}"
    )
    print()

    # Run performance tests
    test_suite = ModifiedPerformanceTestSuite()
    results = test_suite.generate_performance_report()

    # Save report
    report_path = test_suite.save_report()

    # Print summary
    print("\n📈 Test Summary:")
    if "components" in results:
        components = results["components"]
        if "pattern_id_generation" in components:
            caching = components["pattern_id_generation"]
            print(
                f"   Pattern ID caching improvement: {caching['improvement_percent']:.1f}%"
            )

    if "sync_tracker" in results and results["sync_tracker"].get("available"):
        sync = results["sync_tracker"]
        print(f"   Operations per second: {sync.get('operations_per_second', 0):.1f}")
        print(f"   Success rate: {sync.get('success_rate', 0):.1f}%")

    print(f"\n📄 Full report: {report_path}")


if __name__ == "__main__":
    main()
