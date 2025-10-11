#!/usr/bin/env python3
"""
Performance Test Script for Pattern Tracking

This script validates the performance improvements made to the pattern tracking system.
"""

import sys
import time
import asyncio
import json
from pathlib import Path
from datetime import datetime
from typing import Dict, Any

# Add lib to path
SCRIPT_DIR = Path(__file__).parent
sys.path.insert(0, str(SCRIPT_DIR / "lib"))

# Import both trackers for comparison
try:
    from pattern_tracker_sync import PatternTrackerSync
    SYNC_AVAILABLE = True
except ImportError:
    SYNC_AVAILABLE = False
    PatternTrackerSync = None

try:
    from enhanced_pattern_tracker import EnhancedPatternTracker, get_enhanced_tracker
    ENHANCED_AVAILABLE = True
except ImportError:
    ENHANCED_AVAILABLE = False
    EnhancedPatternTracker = None


class PerformanceTestSuite:
    """Comprehensive performance testing suite."""

    def __init__(self):
        self.results = {
            "test_timestamp": datetime.now().isoformat(),
            "sync_tracker": {},
            "enhanced_tracker": {},
            "comparison": {}
        }

    def test_sync_tracker(self) -> Dict[str, Any]:
        """Test performance of synchronous tracker."""
        if not SYNC_AVAILABLE:
            return {"error": "Sync tracker not available"}

        print("🧪 Testing Sync Tracker Performance...")
        tracker = PatternTrackerSync()

        # Test data
        test_code = """
def example_function(param1: str, param2: int = 42) -> str:
    '''Example function for performance testing.'''
    return f"Hello {param1}! The answer is {param2}"
"""

        test_contexts = [
            {"event_type": "pattern_created", "file_path": f"/test/file_{i}.py", "language": "python"}
            for i in range(20)
        ]

        # Test 1: Single operation performance
        start_time = time.time()
        pattern_id = tracker.track_pattern_creation(test_code, test_contexts[0])
        single_op_time = (time.time() - start_time) * 1000

        # Test 2: Multiple operations
        start_time = time.time()
        pattern_ids = []
        for context in test_contexts[:10]:
            pattern_id = tracker.track_pattern_creation(test_code, context)
            pattern_ids.append(pattern_id)
        multi_op_time = time.time() - start_time

        # Test 3: Cache effectiveness
        start_time = time.time()
        for _ in range(10):
            tracker.track_pattern_creation(test_code, test_contexts[0])
        cache_time = time.time() - start_time

        # Get metrics
        metrics = tracker.get_performance_metrics()

        result = {
            "available": True,
            "single_operation_ms": single_op_time,
            "multi_operations_time": multi_op_time,
            "multi_operations_count": 10,
            "operations_per_second": 10 / multi_op_time,
            "cache_test_time": cache_time,
            "cache_operations_per_second": 10 / cache_time,
            "metrics": metrics
        }

        print(f"✅ Sync Tracker: {result['operations_per_second']:.1f} ops/sec")
        print(f"✅ Cache Performance: {result['cache_operations_per_second']:.1f} ops/sec")

        return result

    async def test_enhanced_tracker(self) -> Dict[str, Any]:
        """Test performance of enhanced tracker."""
        if not ENHANCED_AVAILABLE:
            return {"error": "Enhanced tracker not available"}

        print("🧪 Testing Enhanced Tracker Performance...")
        tracker = EnhancedPatternTracker()

        # Test data
        test_code = """
def example_function(param1: str, param2: int = 42) -> str:
    '''Example function for performance testing.'''
    return f"Hello {param1}! The answer is {param2}"
"""

        test_contexts = [
            {"event_type": "pattern_created", "file_path": f"/test/file_{i}.py", "language": "python"}
            for i in range(20)
        ]

        # Test 1: Single operation performance
        start_time = time.time()
        pattern_id = await tracker.track_pattern_creation(test_code, test_contexts[0])
        single_op_time = (time.time() - start_time) * 1000

        # Test 2: Multiple operations
        start_time = time.time()
        pattern_ids = []
        for context in test_contexts[:10]:
            pattern_id = await tracker.track_pattern_creation(test_code, context)
            pattern_ids.append(pattern_id)
        multi_op_time = time.time() - start_time

        # Test 3: Batch processing
        start_time = time.time()
        batch_patterns = [(test_code, context, None) for context in test_contexts[:10]]
        batch_pattern_ids = await tracker.track_pattern_creation_batch(batch_patterns)
        batch_time = time.time() - start_time

        # Test 4: Cache effectiveness
        start_time = time.time()
        for _ in range(10):
            await tracker.track_pattern_creation(test_code, test_contexts[0])
        cache_time = time.time() - start_time

        # Get metrics
        metrics = tracker.get_performance_summary()

        await tracker.close()

        result = {
            "available": True,
            "single_operation_ms": single_op_time,
            "multi_operations_time": multi_op_time,
            "multi_operations_count": 10,
            "operations_per_second": 10 / multi_op_time,
            "batch_processing_time": batch_time,
            "batch_operations_count": 10,
            "batch_operations_per_second": 10 / batch_time,
            "cache_test_time": cache_time,
            "cache_operations_per_second": 10 / cache_time,
            "metrics": metrics
        }

        print(f"✅ Enhanced Tracker: {result['operations_per_second']:.1f} ops/sec")
        print(f"✅ Batch Processing: {result['batch_operations_per_second']:.1f} ops/sec")
        print(f"✅ Cache Performance: {result['cache_operations_per_second']:.1f} ops/sec")

        return result

    def generate_performance_report(self) -> Dict[str, Any]:
        """Generate comprehensive performance comparison report."""
        print("🚀 Starting Performance Test Suite...")
        print("=" * 60)

        # Test sync tracker
        if SYNC_AVAILABLE:
            self.results["sync_tracker"] = self.test_sync_tracker()
        else:
            self.results["sync_tracker"] = {"error": "Not available"}

        print()

        # Test enhanced tracker
        if ENHANCED_AVAILABLE:
            self.results["enhanced_tracker"] = asyncio.run(self.test_enhanced_tracker())
        else:
            self.results["enhanced_tracker"] = {"error": "Not available"}

        print()

        # Generate comparison
        self._generate_comparison()

        print("=" * 60)
        print("✅ Performance Testing Complete!")

        return self.results

    def _generate_comparison(self):
        """Generate comparison metrics."""
        sync_result = self.results["sync_tracker"]
        enhanced_result = self.results["enhanced_tracker"]

        if sync_result.get("available") and enhanced_result.get("available"):
            # Calculate improvements
            sync_ops_per_sec = sync_result["operations_per_second"]
            enhanced_ops_per_sec = enhanced_result["operations_per_second"]
            batch_ops_per_sec = enhanced_result["batch_operations_per_second"]

            improvement_over_sync = ((enhanced_ops_per_sec - sync_ops_per_sec) / sync_ops_per_sec) * 100
            batch_improvement = ((batch_ops_per_sec - sync_ops_per_sec) / sync_ops_per_sec) * 100

            self.results["comparison"] = {
                "sync_vs_enhanced_improvement_percent": improvement_over_sync,
                "sync_vs_batch_improvement_percent": batch_improvement,
                "sync_ops_per_second": sync_ops_per_sec,
                "enhanced_ops_per_second": enhanced_ops_per_sec,
                "batch_ops_per_second": batch_ops_per_sec,
                "performance_tier": self._get_performance_tier(batch_ops_per_sec)
            }

            print(f"📊 Performance Comparison:")
            print(f"   Sync Tracker: {sync_ops_per_sec:.1f} ops/sec")
            print(f"   Enhanced Tracker: {enhanced_ops_per_sec:.1f} ops/sec ({improvement_over_sync:+.1f}%)")
            print(f"   Batch Processing: {batch_ops_per_sec:.1f} ops/sec ({batch_improvement:+.1f}%)")
            print(f"   Performance Tier: {self.results['comparison']['performance_tier']}")

    def _get_performance_tier(self, ops_per_second: float) -> str:
        """Determine performance tier based on operations per second."""
        if ops_per_second >= 100:
            return "Exceptional (100+ ops/sec)"
        elif ops_per_second >= 50:
            return "Excellent (50-99 ops/sec)"
        elif ops_per_second >= 20:
            return "Good (20-49 ops/sec)"
        elif ops_per_second >= 10:
            return "Fair (10-19 ops/sec)"
        else:
            return "Needs Improvement (<10 ops/sec)"

    def save_report(self, filename: str = "performance_test_results.json"):
        """Save test results to file."""
        report_path = Path.home() / ".claude" / "hooks" / "logs" / filename
        report_path.parent.mkdir(parents=True, exist_ok=True)

        with open(report_path, 'w') as f:
            json.dump(self.results, f, indent=2)

        print(f"📄 Report saved to: {report_path}")
        return report_path


def main():
    """Main test runner."""
    print("🎯 Pattern Tracking Performance Test Suite")
    print("=" * 60)

    # Check tracker availability
    print(f"📋 System Status:")
    print(f"   Sync Tracker: {'✅ Available' if SYNC_AVAILABLE else '❌ Not Available'}")
    print(f"   Enhanced Tracker: {'✅ Available' if ENHANCED_AVAILABLE else '❌ Not Available'}")
    print()

    # Run performance tests
    test_suite = PerformanceTestSuite()
    results = test_suite.generate_performance_report()

    # Save report
    report_path = test_suite.save_report()

    # Print summary
    print(f"\n📈 Test Summary:")
    if "comparison" in results:
        comparison = results["comparison"]
        print(f"   Best Performance: {comparison['batch_ops_per_second']:.1f} ops/sec")
        print(f"   Performance Tier: {comparison['performance_tier']}")
        print(f"   Improvement over sync: {comparison['sync_vs_batch_improvement_percent']:+.1f}%")

    print(f"\n📄 Full report: {report_path}")
    print("🔗 Open the performance dashboard for real-time monitoring")


if __name__ == "__main__":
    main()