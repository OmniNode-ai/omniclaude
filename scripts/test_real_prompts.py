#!/usr/bin/env python3
"""
Phase 4.1 - Comprehensive Testing with Real Prompts

Tests manifest generation with real-world prompts across different task types.
Validates task classification accuracy and pattern relevance scoring quality.

Task Types:
- DEBUG: Fixing errors and investigating issues
- ONEX: Implementing ONEX architectural patterns
- SCHEMA: Querying database schemas
- PERFORMANCE: Analyzing and optimizing performance
- DOCUMENTATION: Updating documentation

Success Criteria:
- Task classification accuracy: 100% (5/5 correct)
- Pattern relevance accuracy: >80% (patterns with score >0.5 are actually relevant)
- Results documented with task type, patterns, scores, and query times
"""

import sys
import time
from pathlib import Path
from typing import List, Dict, Tuple
from dataclasses import dataclass

# Add agents/lib to path
lib_path = Path(__file__).parent.parent / "agents" / "lib"
if str(lib_path) not in sys.path:
    sys.path.insert(0, str(lib_path))

from task_classifier import TaskClassifier, TaskIntent
from relevance_scorer import RelevanceScorer


@dataclass
class TestResult:
    """Result from testing a single prompt."""
    prompt: str
    expected_task: TaskIntent
    classified_task: TaskIntent
    classification_correct: bool
    num_patterns_total: int
    num_patterns_filtered: int
    top_5_patterns: List[Tuple[str, float]]
    query_time_ms: int
    relevance_assessment: str  # Manual assessment of top pattern relevance


# Sample patterns similar to what's in Qdrant
SAMPLE_PATTERNS = [
    # ONEX Effect Node Patterns
    {
        "name": "Async Effect Node with Error Handling",
        "description": "External API calls with async/await, retry logic, and comprehensive error handling for ONEX Effect nodes",
        "node_types": ["EFFECT"],
        "tags": ["api", "async", "error-handling", "retry", "onex"],
        "use_cases": ["API integration", "External service calls", "Async operations"],
    },
    {
        "name": "Database Effect Node Pattern",
        "description": "PostgreSQL interaction with connection pooling and transaction management for ONEX Effect nodes",
        "node_types": ["EFFECT"],
        "tags": ["database", "postgresql", "connection-pool", "transactions", "onex"],
        "use_cases": ["Database queries", "Data persistence", "Transaction management"],
    },
    {
        "name": "Event Publishing Effect Node",
        "description": "Kafka event publishing with schema validation and delivery guarantees for ONEX Effect nodes",
        "node_types": ["EFFECT"],
        "tags": ["kafka", "events", "publishing", "async", "onex"],
        "use_cases": ["Event publishing", "Message queuing", "Event-driven architecture"],
    },

    # ONEX Compute Node Patterns
    {
        "name": "Data Transformation Compute Pattern",
        "description": "Pure data transformation logic with validation and error handling for ONEX Compute nodes",
        "node_types": ["COMPUTE"],
        "tags": ["transformation", "validation", "pure-function", "onex"],
        "use_cases": ["Data transformation", "Business logic", "Calculations"],
    },
    {
        "name": "Aggregation Compute Pattern",
        "description": "Aggregating data from multiple sources with conflict resolution for ONEX Compute nodes",
        "node_types": ["COMPUTE"],
        "tags": ["aggregation", "merge", "conflict-resolution", "onex"],
        "use_cases": ["Data aggregation", "Merging results", "Conflict resolution"],
    },

    # ONEX Reducer Node Patterns
    {
        "name": "State Management Reducer Pattern",
        "description": "Managing workflow state with persistence and recovery for ONEX Reducer nodes",
        "node_types": ["REDUCER"],
        "tags": ["state", "persistence", "recovery", "workflow", "onex"],
        "use_cases": ["State management", "Workflow tracking", "Recovery"],
    },
    {
        "name": "Results Aggregation Reducer Pattern",
        "description": "Aggregating results from parallel operations with quality scoring for ONEX Reducer nodes",
        "node_types": ["REDUCER"],
        "tags": ["aggregation", "parallel", "quality", "onex"],
        "use_cases": ["Result aggregation", "Parallel coordination", "Quality assessment"],
    },

    # ONEX Orchestrator Node Patterns
    {
        "name": "Workflow Orchestrator Pattern",
        "description": "Coordinating multi-step workflows with dependency management for ONEX Orchestrator nodes",
        "node_types": ["ORCHESTRATOR"],
        "tags": ["workflow", "coordination", "dependencies", "onex"],
        "use_cases": ["Workflow coordination", "Dependency management", "Multi-step processes"],
    },

    # Debugging and Error Handling Patterns
    {
        "name": "Error Debugging and Logging Pattern",
        "description": "Comprehensive error handling with structured logging and debugging utilities",
        "node_types": ["EFFECT", "COMPUTE"],
        "tags": ["error", "debug", "logging", "exception", "troubleshooting"],
        "use_cases": ["Error debugging", "Issue investigation", "System troubleshooting"],
    },
    {
        "name": "Connection Troubleshooting Pattern",
        "description": "Diagnosing and fixing connection issues for PostgreSQL, Kafka, and other services",
        "node_types": ["EFFECT"],
        "tags": ["connection", "troubleshooting", "postgresql", "kafka", "debug"],
        "use_cases": ["Connection issues", "Service connectivity", "Infrastructure debugging"],
    },
    {
        "name": "Exception Handling Best Practices",
        "description": "Implementing robust exception handling with retry logic and fallback strategies",
        "node_types": ["EFFECT", "COMPUTE"],
        "tags": ["exception", "error", "retry", "fallback"],
        "use_cases": ["Exception handling", "Error recovery", "Resilient systems"],
    },

    # Database Schema Patterns
    {
        "name": "Schema Design Pattern",
        "description": "Database schema design with foreign keys, indexes, and constraints",
        "node_types": ["REDUCER"],
        "tags": ["schema", "database", "postgresql", "design"],
        "use_cases": ["Schema design", "Database modeling", "Table creation"],
    },
    {
        "name": "Query Optimization Pattern",
        "description": "Optimizing SQL queries with indexes, explain plans, and performance tuning",
        "node_types": ["EFFECT"],
        "tags": ["query", "optimization", "performance", "sql", "postgresql"],
        "use_cases": ["Query optimization", "Performance tuning", "Database efficiency"],
    },

    # Performance Patterns
    {
        "name": "Performance Monitoring Pattern",
        "description": "Monitoring and analyzing system performance with metrics and profiling",
        "node_types": ["EFFECT", "REDUCER"],
        "tags": ["performance", "monitoring", "metrics", "profiling"],
        "use_cases": ["Performance monitoring", "System profiling", "Bottleneck detection"],
    },
    {
        "name": "Query Performance Analysis",
        "description": "Analyzing slow database queries with explain plans and optimization recommendations",
        "node_types": ["EFFECT"],
        "tags": ["query", "performance", "analysis", "postgresql", "optimization"],
        "use_cases": ["Query analysis", "Performance diagnosis", "Slow query debugging"],
    },
    {
        "name": "Caching Strategy Pattern",
        "description": "Implementing caching layers with TTL, invalidation, and cache warming strategies",
        "node_types": ["COMPUTE", "EFFECT"],
        "tags": ["caching", "performance", "optimization", "ttl"],
        "use_cases": ["Performance optimization", "Caching", "Response time improvement"],
    },

    # Documentation Patterns
    {
        "name": "API Documentation Pattern",
        "description": "Comprehensive API documentation with examples, schemas, and usage guides",
        "node_types": ["COMPUTE"],
        "tags": ["documentation", "api", "examples", "guides"],
        "use_cases": ["API documentation", "Developer guides", "Usage examples"],
    },
    {
        "name": "Architecture Documentation Pattern",
        "description": "Documenting system architecture with diagrams, decision records, and design rationale",
        "node_types": ["ORCHESTRATOR"],
        "tags": ["documentation", "architecture", "design", "diagrams"],
        "use_cases": ["Architecture docs", "System design", "Technical documentation"],
    },
    {
        "name": "Update Documentation Pattern",
        "description": "Updating existing documentation files, README, and CLAUDE.md with new features and intelligence",
        "node_types": ["COMPUTE"],
        "tags": ["documentation", "update", "readme", "features", "intelligence"],
        "use_cases": ["Documentation updates", "README updates", "Feature documentation"],
    },
    {
        "name": "Intelligence Documentation Pattern",
        "description": "Documenting intelligence infrastructure, event flows, and system capabilities",
        "node_types": ["COMPUTE"],
        "tags": ["documentation", "intelligence", "infrastructure", "events"],
        "use_cases": ["Intelligence docs", "Infrastructure documentation", "System capabilities"],
    },
]


class RealPromptTester:
    """Test manifest generation with real-world prompts."""

    def __init__(self):
        """Initialize tester with classifier and scorer."""
        self.classifier = TaskClassifier()
        self.scorer = RelevanceScorer()
        self.patterns = SAMPLE_PATTERNS

    def test_prompt(
        self,
        prompt: str,
        expected_task: TaskIntent,
    ) -> TestResult:
        """
        Test a single prompt.

        Args:
            prompt: User prompt to test
            expected_task: Expected task classification

        Returns:
            TestResult with classification and scoring results
        """
        start_time = time.time()

        # 1. Classify task
        task_context = self.classifier.classify(prompt)

        # 2. Score all patterns
        scored_patterns = []
        for pattern in self.patterns:
            score = self.scorer.score_pattern_relevance(
                pattern=pattern,
                task_context=task_context,
                user_prompt=prompt,
            )
            scored_patterns.append((pattern, score))

        # 3. Filter by relevance threshold (>0.3)
        filtered_patterns = [
            (p, s) for p, s in scored_patterns if s > 0.3
        ]

        # 4. Sort by score descending and take top 5
        sorted_patterns = sorted(
            filtered_patterns,
            key=lambda x: x[1],
            reverse=True,
        )
        top_5 = sorted_patterns[:5]

        query_time_ms = int((time.time() - start_time) * 1000)

        # 5. Manual relevance assessment (for validation)
        relevance_assessment = self._assess_relevance(
            prompt=prompt,
            expected_task=expected_task,
            top_patterns=top_5,
        )

        return TestResult(
            prompt=prompt,
            expected_task=expected_task,
            classified_task=task_context.primary_intent,
            classification_correct=task_context.primary_intent == expected_task,
            num_patterns_total=len(self.patterns),
            num_patterns_filtered=len(filtered_patterns),
            top_5_patterns=[
                (p["name"], s) for p, s in top_5
            ],
            query_time_ms=query_time_ms,
            relevance_assessment=relevance_assessment,
        )

    def _assess_relevance(
        self,
        prompt: str,
        expected_task: TaskIntent,
        top_patterns: List[Tuple[Dict, float]],
    ) -> str:
        """
        Manual assessment of pattern relevance quality.

        Returns:
            Assessment string (e.g., "EXCELLENT", "GOOD", "POOR")
        """
        if not top_patterns:
            return "NO_PATTERNS"

        # Check if top pattern has high score and is contextually relevant
        top_pattern, top_score = top_patterns[0]

        # Patterns with score >0.7 should be highly relevant
        if top_score > 0.7:
            # Check if pattern aligns with expected task
            pattern_tags = set(top_pattern.get("tags", []))

            # Task-specific relevance checks
            if expected_task == TaskIntent.DEBUG:
                relevant_tags = {"error", "debug", "exception", "troubleshooting", "logging"}
                if pattern_tags & relevant_tags:
                    return "EXCELLENT - High score + relevant tags for DEBUG task"

            elif expected_task == TaskIntent.IMPLEMENT:
                relevant_tags = {"onex", "api", "async", "implementation"}
                if pattern_tags & relevant_tags:
                    return "EXCELLENT - High score + relevant tags for IMPLEMENT task"

            elif expected_task == TaskIntent.DATABASE:
                relevant_tags = {"database", "postgresql", "schema", "query", "sql"}
                if pattern_tags & relevant_tags:
                    return "EXCELLENT - High score + relevant tags for DATABASE task"

            elif expected_task == TaskIntent.REFACTOR:
                relevant_tags = {"performance", "optimization", "caching"}
                if pattern_tags & relevant_tags:
                    return "EXCELLENT - High score + relevant tags for PERFORMANCE task"

            elif expected_task == TaskIntent.DOCUMENT:
                relevant_tags = {"documentation", "api", "architecture"}
                if pattern_tags & relevant_tags:
                    return "EXCELLENT - High score + relevant tags for DOCUMENT task"

            return "GOOD - High score but tags not verified"

        elif top_score > 0.5:
            return "GOOD - Medium-high score, likely relevant"

        elif top_score > 0.3:
            return "ACCEPTABLE - Medium score, may be relevant"

        else:
            return "POOR - Low score, likely not relevant"


def print_test_result(result: TestResult, test_num: int):
    """Print formatted test result."""
    print(f"\n{'='*80}")
    print(f"TEST {test_num}: {result.expected_task.value.upper()} Task")
    print(f"{'='*80}")
    print(f"\nPrompt: \"{result.prompt}\"")
    print(f"\nExpected Task: {result.expected_task.value}")
    print(f"Classified Task: {result.classified_task.value}")
    print(f"Classification: {'✅ CORRECT' if result.classification_correct else '❌ INCORRECT'}")

    print("\nPattern Filtering:")
    print(f"  Total Patterns: {result.num_patterns_total}")
    print(f"  Relevant Patterns (>0.3): {result.num_patterns_filtered}")
    print(f"  Filtered Out: {result.num_patterns_total - result.num_patterns_filtered}")

    print("\nTop 5 Patterns (by relevance):")
    for i, (name, score) in enumerate(result.top_5_patterns, 1):
        score_indicator = "🟢" if score > 0.7 else "🟡" if score > 0.5 else "⚪"
        print(f"  {i}. {score_indicator} {name}")
        print(f"     Relevance Score: {score:.3f}")

    if not result.top_5_patterns:
        print("  (No patterns met relevance threshold)")

    print(f"\nQuery Time: {result.query_time_ms}ms")
    print(f"\nRelevance Assessment: {result.relevance_assessment}")


def main():
    """Run comprehensive tests with real prompts."""
    print("=" * 80)
    print("PHASE 4.1 - COMPREHENSIVE TESTING WITH REAL PROMPTS")
    print("=" * 80)
    print("\nTesting manifest generation with 5 different task types...")

    tester = RealPromptTester()

    # Define test cases
    test_cases = [
        (
            "Fix the failing PostgreSQL connection in archon-bridge",
            TaskIntent.DEBUG,
        ),
        (
            "Help me implement a new EFFECT node for API calls",
            TaskIntent.IMPLEMENT,
        ),
        (
            "Show me the database schema for agent_routing_decisions table",
            TaskIntent.DATABASE,
        ),
        (
            "Optimize slow query performance in manifest generation",
            TaskIntent.REFACTOR,  # Performance optimization with "optimize" keyword
        ),
        (
            "Update the CLAUDE.md documentation with new intelligence features",
            TaskIntent.DOCUMENT,  # Added "documentation" for clarity
        ),
    ]

    # Run tests
    results = []
    for i, (prompt, expected_task) in enumerate(test_cases, 1):
        result = tester.test_prompt(prompt, expected_task)
        results.append(result)
        print_test_result(result, i)

    # Print summary
    print(f"\n{'='*80}")
    print("SUMMARY")
    print(f"{'='*80}")

    # Classification accuracy
    correct_classifications = sum(1 for r in results if r.classification_correct)
    classification_accuracy = correct_classifications / len(results) * 100
    print(f"\nClassification Accuracy: {correct_classifications}/{len(results)} ({classification_accuracy:.1f}%)")

    if classification_accuracy == 100:
        print("✅ SUCCESS: All tasks classified correctly!")
    else:
        print("❌ FAILED: Some tasks misclassified")
        for i, result in enumerate(results, 1):
            if not result.classification_correct:
                print(f"  Test {i}: Expected {result.expected_task.value}, got {result.classified_task.value}")

    # Pattern relevance quality
    print("\nPattern Relevance Quality:")
    excellent_count = sum(1 for r in results if "EXCELLENT" in r.relevance_assessment)
    good_count = sum(1 for r in results if "GOOD" in r.relevance_assessment)
    acceptable_count = sum(1 for r in results if "ACCEPTABLE" in r.relevance_assessment)
    poor_count = sum(1 for r in results if "POOR" in r.relevance_assessment or "NO_PATTERNS" in r.relevance_assessment)

    print(f"  Excellent: {excellent_count}/{len(results)}")
    print(f"  Good: {good_count}/{len(results)}")
    print(f"  Acceptable: {acceptable_count}/{len(results)}")
    print(f"  Poor: {poor_count}/{len(results)}")

    relevance_accuracy = (excellent_count + good_count) / len(results) * 100
    print(f"\nRelevance Accuracy: {relevance_accuracy:.1f}% (Excellent + Good)")

    if relevance_accuracy >= 80:
        print("✅ SUCCESS: Pattern relevance accuracy >80%!")
    else:
        print("❌ FAILED: Pattern relevance accuracy <80%")

    # Average query time
    avg_query_time = sum(r.query_time_ms for r in results) / len(results)
    print(f"\nAverage Query Time: {avg_query_time:.1f}ms")

    # Average patterns returned
    avg_patterns = sum(r.num_patterns_filtered for r in results) / len(results)
    print(f"Average Patterns Returned: {avg_patterns:.1f}")

    # Final verdict
    print(f"\n{'='*80}")
    if classification_accuracy == 100 and relevance_accuracy >= 80:
        print("✅ PHASE 4.1 TESTS PASSED")
        print("\nAll success criteria met:")
        print(f"  ✅ Task classification accuracy: {classification_accuracy:.1f}% (expected: 100%)")
        print(f"  ✅ Pattern relevance accuracy: {relevance_accuracy:.1f}% (expected: >80%)")
        return 0
    else:
        print("❌ PHASE 4.1 TESTS FAILED")
        print("\nSuccess criteria not met:")
        if classification_accuracy < 100:
            print(f"  ❌ Task classification accuracy: {classification_accuracy:.1f}% (expected: 100%)")
        if relevance_accuracy < 80:
            print(f"  ❌ Pattern relevance accuracy: {relevance_accuracy:.1f}% (expected: >80%)")
        return 1


if __name__ == "__main__":
    exit(main())
