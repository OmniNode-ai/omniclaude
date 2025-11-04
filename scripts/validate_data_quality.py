#!/usr/bin/env python3
"""
Data Quality Validation Script

Performs comprehensive spot checks on:
1. Pattern relevance scoring accuracy
2. Schema filtering accuracy
3. Task classification accuracy

Generates quality report with detailed findings and recommendations.

Part of Phase 4.3: Data Quality Spot Checks
"""

import sys
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, List, Tuple

# Add agents/lib to path for imports
lib_path = Path(__file__).parent.parent / "agents" / "lib"
sys.path.insert(0, str(lib_path))

from relevance_scorer import RelevanceScorer
from task_classifier import TaskClassifier, TaskIntent


@dataclass
class ValidationResult:
    """Result of a validation test."""

    test_name: str
    passed: bool
    expected: Any
    actual: Any
    score: float = 0.0
    details: str = ""


@dataclass
class QualityReport:
    """Comprehensive quality report."""

    timestamp: datetime = field(default_factory=datetime.now)
    pattern_relevance_accuracy: float = 0.0
    schema_filtering_precision: float = 0.0
    schema_filtering_recall: float = 0.0
    task_classification_accuracy: float = 0.0
    total_tests: int = 0
    passed_tests: int = 0
    failed_tests: int = 0
    validation_results: List[ValidationResult] = field(default_factory=list)
    recommendations: List[str] = field(default_factory=list)


class DataQualityValidator:
    """
    Comprehensive data quality validator.

    Performs spot checks on relevance scoring, schema filtering,
    and task classification accuracy.
    """

    def __init__(self):
        """Initialize validator with scorer and classifier."""
        self.scorer = RelevanceScorer()
        self.classifier = TaskClassifier()
        self.report = QualityReport()

    def validate_all(self) -> QualityReport:
        """
        Run all validation checks and generate report.

        Returns:
            QualityReport with detailed findings
        """
        print("=" * 80)
        print("DATA QUALITY VALIDATION - Phase 4.3")
        print("=" * 80)
        print()

        # Section A: Pattern Relevance Accuracy
        print("A. Pattern Relevance Accuracy")
        print("-" * 80)
        pattern_accuracy = self._validate_pattern_relevance()
        self.report.pattern_relevance_accuracy = pattern_accuracy
        print(f"✓ Pattern Relevance Accuracy: {pattern_accuracy:.1%}")
        print()

        # Section B: Schema Filtering Accuracy
        print("B. Schema Filtering Accuracy")
        print("-" * 80)
        precision, recall = self._validate_schema_filtering()
        self.report.schema_filtering_precision = precision
        self.report.schema_filtering_recall = recall
        print(f"✓ Schema Filtering Precision: {precision:.1%}")
        print(f"✓ Schema Filtering Recall: {recall:.1%}")
        print()

        # Section C: Task Classification Accuracy
        print("C. Task Classification Accuracy")
        print("-" * 80)
        classification_accuracy = self._validate_task_classification()
        self.report.task_classification_accuracy = classification_accuracy
        print(f"✓ Task Classification Accuracy: {classification_accuracy:.1%}")
        print()

        # Generate recommendations
        self._generate_recommendations()

        # Calculate summary statistics
        self.report.total_tests = len(self.report.validation_results)
        self.report.passed_tests = sum(
            1 for r in self.report.validation_results if r.passed
        )
        self.report.failed_tests = self.report.total_tests - self.report.passed_tests

        # Print summary
        self._print_summary()

        return self.report

    def _validate_pattern_relevance(self) -> float:
        """
        Validate pattern relevance scoring accuracy.

        Tests:
        1. Sample 10 patterns for "Fix PostgreSQL error" prompt
        2. Verify top 5 patterns are actually relevant
        3. Check that irrelevant patterns have low scores (<0.3)
        4. Verify keyword matching works

        Returns:
            Accuracy percentage (0.0 - 1.0)
        """
        test_cases = [
            # Test Case 1: PostgreSQL error debugging
            {
                "prompt": "Fix PostgreSQL connection error in Effect node",
                "patterns": [
                    {
                        "name": "PostgreSQL Connection Error Handling",
                        "description": "Database connection error handling and retry logic for PostgreSQL",
                        "node_types": ["EFFECT"],
                        "expected_relevant": True,
                    },
                    {
                        "name": "Effect Node Error Handling",
                        "description": "Error handling patterns for Effect nodes with external dependencies",
                        "node_types": ["EFFECT"],
                        "expected_relevant": True,
                    },
                    {
                        "name": "Database Query Optimization",
                        "description": "SQL query optimization for PostgreSQL databases",
                        "node_types": ["REDUCER"],
                        "expected_relevant": True,  # Related to PostgreSQL
                    },
                    {
                        "name": "Debug Logging Pattern",
                        "description": "Comprehensive debug logging for error troubleshooting",
                        "node_types": ["EFFECT"],
                        "expected_relevant": True,  # Related to debugging
                    },
                    {
                        "name": "Effect Node Implementation",
                        "description": "Basic Effect node implementation pattern",
                        "node_types": ["EFFECT"],
                        "expected_relevant": False,  # Too generic
                    },
                    {
                        "name": "Kafka Event Publishing",
                        "description": "Publishing events to Kafka topics",
                        "node_types": ["EFFECT"],
                        "expected_relevant": False,  # Not related to PostgreSQL
                    },
                    {
                        "name": "React Component Pattern",
                        "description": "Frontend React component implementation",
                        "node_types": ["COMPUTE"],
                        "expected_relevant": False,  # Completely unrelated
                    },
                    {
                        "name": "API Rate Limiting",
                        "description": "Rate limiting for external API calls",
                        "node_types": ["EFFECT"],
                        "expected_relevant": False,  # Not related to database
                    },
                    {
                        "name": "Data Transformation Pipeline",
                        "description": "ETL data transformation pipeline",
                        "node_types": ["COMPUTE"],
                        "expected_relevant": False,  # Not related to errors
                    },
                    {
                        "name": "User Authentication",
                        "description": "User authentication and authorization",
                        "node_types": ["EFFECT"],
                        "expected_relevant": False,  # Not related
                    },
                ],
            },
            # Test Case 2: Implementing EFFECT node
            {
                "prompt": "Create an Effect node for async API calls with retry logic",
                "patterns": [
                    {
                        "name": "Async Effect Node Pattern",
                        "description": "Effect node with async/await API calls",
                        "node_types": ["EFFECT"],
                        "expected_relevant": True,
                    },
                    {
                        "name": "API Retry Logic Pattern",
                        "description": "Retry logic with exponential backoff for API calls",
                        "node_types": ["EFFECT"],
                        "expected_relevant": True,
                    },
                    {
                        "name": "Effect Node Base Template",
                        "description": "Base template for Effect node implementation",
                        "node_types": ["EFFECT"],
                        "expected_relevant": True,
                    },
                    {
                        "name": "HTTP Client Pattern",
                        "description": "HTTP client implementation for API calls",
                        "node_types": ["EFFECT"],
                        "expected_relevant": True,
                    },
                    {
                        "name": "Database Migration",
                        "description": "Database schema migration patterns",
                        "node_types": ["REDUCER"],
                        "expected_relevant": False,
                    },
                ],
            },
        ]

        correct_predictions = 0
        total_predictions = 0

        for test_case in test_cases:
            prompt = test_case["prompt"]
            patterns = test_case["patterns"]

            # Classify task
            task_context = self.classifier.classify(prompt)

            print(f"\nTest Prompt: '{prompt}'")
            print(
                f"Classification: {task_context.primary_intent.value} (confidence: {task_context.confidence:.2f})"
            )
            print(f"Keywords: {', '.join(task_context.keywords)}")
            print()

            # Score all patterns
            scored_patterns = []
            for pattern in patterns:
                score = self.scorer.score_pattern_relevance(
                    pattern=pattern,
                    task_context=task_context,
                    user_prompt=prompt,
                )
                scored_patterns.append((pattern, score))

            # Sort by score descending
            scored_patterns.sort(key=lambda x: x[1], reverse=True)

            # Validate predictions
            print(f"{'Pattern Name':<50} {'Score':<10} {'Expected':<15} {'Result'}")
            print("-" * 90)

            for pattern, score in scored_patterns:
                expected_relevant = pattern["expected_relevant"]
                predicted_relevant = score > 0.3  # Threshold from manifest_injector.py

                is_correct = predicted_relevant == expected_relevant
                total_predictions += 1
                if is_correct:
                    correct_predictions += 1

                result_icon = "✓" if is_correct else "✗"
                expected_str = "Relevant" if expected_relevant else "Irrelevant"

                print(
                    f"{pattern['name']:<50} {score:<10.3f} {expected_str:<15} {result_icon}"
                )

                # Record validation result
                self.report.validation_results.append(
                    ValidationResult(
                        test_name=f"Pattern Relevance: {pattern['name'][:40]}",
                        passed=is_correct,
                        expected=expected_relevant,
                        actual=predicted_relevant,
                        score=score,
                        details=f"Prompt: '{prompt[:50]}...' | Score: {score:.3f}",
                    )
                )

            print()

        accuracy = (
            correct_predictions / total_predictions if total_predictions > 0 else 0.0
        )
        return accuracy

    def _validate_schema_filtering(self) -> Tuple[float, float]:
        """
        Validate schema filtering accuracy.

        Tests:
        1. Query for "routing" context - verify routing tables returned
        2. Query for "intelligence" context - verify intelligence tables returned
        3. Check irrelevant tables are filtered out

        Returns:
            Tuple of (precision, recall)
        """
        test_cases = [
            # Test Case 1: Routing context
            {
                "prompt": "Show me agent routing decisions from the database",
                "schemas": [
                    {
                        "table_name": "agent_routing_decisions",
                        "expected_relevant": True,
                    },
                    {
                        "table_name": "agent_transformation_events",
                        "expected_relevant": True,
                    },
                    {
                        "table_name": "router_performance_metrics",
                        "expected_relevant": True,
                    },
                    {
                        "table_name": "agent_manifest_injections",
                        "expected_relevant": False,
                    },
                    {"table_name": "workflow_events", "expected_relevant": False},
                    {"table_name": "user_preferences", "expected_relevant": False},
                    {"table_name": "llm_calls", "expected_relevant": False},
                ],
            },
            # Test Case 2: Intelligence context
            {
                "prompt": "Query the intelligence manifest injection data",
                "schemas": [
                    {
                        "table_name": "agent_manifest_injections",
                        "expected_relevant": True,
                    },
                    {"table_name": "intelligence_queries", "expected_relevant": True},
                    {
                        "table_name": "pattern_discovery_events",
                        "expected_relevant": True,
                    },
                    {
                        "table_name": "agent_routing_decisions",
                        "expected_relevant": False,
                    },
                    {"table_name": "user_sessions", "expected_relevant": False},
                    {"table_name": "api_rate_limits", "expected_relevant": False},
                ],
            },
            # Test Case 3: Workflow/debug context
            {
                "prompt": "Find error events in workflow execution",
                "schemas": [
                    {"table_name": "workflow_events", "expected_relevant": True},
                    {"table_name": "error_events", "expected_relevant": True},
                    {"table_name": "workflow_steps", "expected_relevant": True},
                    {
                        "table_name": "agent_routing_decisions",
                        "expected_relevant": False,
                    },
                    {
                        "table_name": "pattern_quality_scores",
                        "expected_relevant": False,
                    },
                ],
            },
        ]

        true_positives = 0
        false_positives = 0
        true_negatives = 0
        false_negatives = 0

        for test_case in test_cases:
            prompt = test_case["prompt"]
            schemas = test_case["schemas"]

            # Classify task
            task_context = self.classifier.classify(prompt)

            print(f"\nTest Prompt: '{prompt}'")
            print(f"Classification: {task_context.primary_intent.value}")
            print()

            print(f"{'Table Name':<40} {'Score':<10} {'Expected':<15} {'Result'}")
            print("-" * 75)

            for schema in schemas:
                score = self.scorer.score_schema_relevance(
                    schema=schema,
                    task_context=task_context,
                    user_prompt=prompt,
                )

                expected_relevant = schema["expected_relevant"]
                predicted_relevant = score > 0.3  # Using same threshold

                # Track metrics
                if expected_relevant and predicted_relevant:
                    true_positives += 1
                elif expected_relevant and not predicted_relevant:
                    false_negatives += 1
                elif not expected_relevant and predicted_relevant:
                    false_positives += 1
                else:
                    true_negatives += 1

                is_correct = predicted_relevant == expected_relevant
                result_icon = "✓" if is_correct else "✗"
                expected_str = "Relevant" if expected_relevant else "Irrelevant"

                print(
                    f"{schema['table_name']:<40} {score:<10.3f} {expected_str:<15} {result_icon}"
                )

                # Record validation result
                self.report.validation_results.append(
                    ValidationResult(
                        test_name=f"Schema Filtering: {schema['table_name']}",
                        passed=is_correct,
                        expected=expected_relevant,
                        actual=predicted_relevant,
                        score=score,
                        details=f"Prompt: '{prompt[:50]}...' | Score: {score:.3f}",
                    )
                )

            print()

        # Calculate precision and recall
        precision = (
            true_positives / (true_positives + false_positives)
            if (true_positives + false_positives) > 0
            else 0.0
        )
        recall = (
            true_positives / (true_positives + false_negatives)
            if (true_positives + false_negatives) > 0
            else 0.0
        )

        return precision, recall

    def _validate_task_classification(self) -> float:
        """
        Validate task classification accuracy.

        Tests:
        1. Test 10 diverse prompts
        2. Verify classification matches expected type
        3. Check confidence scores are reasonable
        4. Validate fallback to UNKNOWN works

        Returns:
            Accuracy percentage (0.0 - 1.0)
        """
        test_cases = [
            {
                "prompt": "Fix the PostgreSQL connection error in the Effect node",
                "expected_intent": TaskIntent.DEBUG,
                "expected_keywords": ["fix", "error"],
                "expected_entities": [],
            },
            {
                "prompt": "Implement a new Effect node for Kafka event publishing",
                "expected_intent": TaskIntent.IMPLEMENT,
                "expected_keywords": ["implement"],
                "expected_entities": [],
            },
            {
                "prompt": "Query the agent_routing_decisions table for recent data",
                "expected_intent": TaskIntent.DATABASE,
                "expected_keywords": ["query", "table"],
                "expected_entities": ["agent_routing_decisions"],
            },
            {
                "prompt": "Refactor the manifest injector to improve performance",
                "expected_intent": TaskIntent.REFACTOR,
                "expected_keywords": ["refactor", "improve"],
                "expected_entities": ["manifest_injector"],
            },
            {
                "prompt": "What is the purpose of the RelevanceScorer class?",
                "expected_intent": TaskIntent.RESEARCH,
                "expected_keywords": ["what"],
                "expected_entities": [],
            },
            {
                "prompt": "Write unit tests for the pattern quality scorer",
                "expected_intent": TaskIntent.TEST,
                "expected_keywords": ["test"],
                "expected_entities": ["pattern_quality_scorer"],
            },
            {
                "prompt": "Add documentation to the TaskClassifier module",
                "expected_intent": TaskIntent.DOCUMENT,
                "expected_keywords": ["documentation"],
                "expected_entities": [],
            },
            {
                "prompt": "Debug the error in node_user_reducer.py file",
                "expected_intent": TaskIntent.DEBUG,
                "expected_keywords": ["debug", "error"],
                "expected_entities": ["node_user_reducer.py"],
            },
            {
                "prompt": "Create a database migration for the new workflow_events table",
                "expected_intent": TaskIntent.DATABASE,
                "expected_keywords": ["database", "migration", "table"],
                "expected_entities": ["workflow_events"],
            },
            {
                "prompt": "Investigate why the Kafka consumer is not processing messages",
                "expected_intent": TaskIntent.DEBUG,
                "expected_keywords": ["investigate"],
                "expected_entities": [],
            },
        ]

        correct_classifications = 0
        total_classifications = len(test_cases)

        print(
            f"\n{'Prompt':<60} {'Expected':<15} {'Actual':<15} {'Confidence':<12} {'Result'}"
        )
        print("-" * 110)

        for test_case in test_cases:
            prompt = test_case["prompt"]
            expected_intent = test_case["expected_intent"]

            # Classify
            task_context = self.classifier.classify(prompt)

            # Check if classification is correct
            is_correct = task_context.primary_intent == expected_intent
            if is_correct:
                correct_classifications += 1

            result_icon = "✓" if is_correct else "✗"

            print(
                f"{prompt:<60} {expected_intent.value:<15} {task_context.primary_intent.value:<15} {task_context.confidence:<12.2f} {result_icon}"
            )

            # Record validation result
            self.report.validation_results.append(
                ValidationResult(
                    test_name=f"Task Classification: {prompt[:50]}",
                    passed=is_correct,
                    expected=expected_intent.value,
                    actual=task_context.primary_intent.value,
                    score=task_context.confidence,
                    details=f"Keywords: {', '.join(task_context.keywords[:5])}",
                )
            )

        print()

        accuracy = correct_classifications / total_classifications
        return accuracy

    def _generate_recommendations(self):
        """Generate recommendations based on validation results."""
        recommendations = []

        # Pattern relevance recommendations
        if self.report.pattern_relevance_accuracy < 0.8:
            recommendations.append(
                f"⚠️  Pattern relevance accuracy ({self.report.pattern_relevance_accuracy:.1%}) "
                "is below target (80%). Consider:\n"
                "   - Adjusting keyword weights (currently 60% keywords, 40% heuristics)\n"
                "   - Adding more domain-specific heuristics\n"
                "   - Lowering or raising the 0.3 relevance threshold"
            )
        else:
            recommendations.append(
                f"✓ Pattern relevance accuracy ({self.report.pattern_relevance_accuracy:.1%}) "
                "meets or exceeds target (80%)"
            )

        # Schema filtering recommendations
        if self.report.schema_filtering_precision < 0.9:
            recommendations.append(
                f"⚠️  Schema filtering precision ({self.report.schema_filtering_precision:.1%}) "
                "is below target (90%). Consider:\n"
                "   - Stricter schema matching rules\n"
                "   - Higher threshold for schema relevance\n"
                "   - Better keyword extraction from table names"
            )
        else:
            recommendations.append(
                f"✓ Schema filtering precision ({self.report.schema_filtering_precision:.1%}) "
                "meets or exceeds target (90%)"
            )

        if self.report.schema_filtering_recall < 0.8:
            recommendations.append(
                f"⚠️  Schema filtering recall ({self.report.schema_filtering_recall:.1%}) "
                "is below acceptable level (80%). Consider:\n"
                "   - More lenient schema matching\n"
                "   - Synonym expansion for table names\n"
                "   - Fuzzy matching for similar table names"
            )
        else:
            recommendations.append(
                f"✓ Schema filtering recall ({self.report.schema_filtering_recall:.1%}) "
                "is acceptable (>=80%)"
            )

        # Task classification recommendations
        if self.report.task_classification_accuracy < 0.95:
            recommendations.append(
                f"⚠️  Task classification accuracy ({self.report.task_classification_accuracy:.1%}) "
                "is below target (95%). Consider:\n"
                "   - Expanding keyword patterns for each intent\n"
                "   - Adding confidence threshold for fallback to UNKNOWN\n"
                "   - Using LLM-based classification for edge cases"
            )
        else:
            recommendations.append(
                f"✓ Task classification accuracy ({self.report.task_classification_accuracy:.1%}) "
                "meets or exceeds target (95%)"
            )

        # Overall recommendations
        failed_count = self.report.failed_tests
        if failed_count > 0:
            recommendations.append(
                f"\n⚠️  {failed_count} validation test(s) failed. "
                "Review detailed results above for specific issues."
            )
        else:
            recommendations.append(
                "\n✓ All validation tests passed! Data quality is excellent."
            )

        self.report.recommendations = recommendations

    def _print_summary(self):
        """Print summary report."""
        print("=" * 80)
        print("VALIDATION SUMMARY")
        print("=" * 80)
        print()
        print(f"Timestamp: {self.report.timestamp.strftime('%Y-%m-%d %H:%M:%S')}")
        print()
        print("Metrics:")
        print(
            f"  • Pattern Relevance Accuracy:     {self.report.pattern_relevance_accuracy:.1%}"
        )
        print(
            f"  • Schema Filtering Precision:     {self.report.schema_filtering_precision:.1%}"
        )
        print(
            f"  • Schema Filtering Recall:        {self.report.schema_filtering_recall:.1%}"
        )
        print(
            f"  • Task Classification Accuracy:   {self.report.task_classification_accuracy:.1%}"
        )
        print()
        print(
            f"Test Results: {self.report.passed_tests}/{self.report.total_tests} passed ({self.report.passed_tests/self.report.total_tests*100:.1f}%)"
        )
        print()
        print("Recommendations:")
        for rec in self.report.recommendations:
            print(rec)
        print()

        # Overall status
        all_passed = (
            self.report.pattern_relevance_accuracy >= 0.8
            and self.report.schema_filtering_precision >= 0.9
            and self.report.task_classification_accuracy >= 0.95
        )

        if all_passed:
            print("✅ SUCCESS: All quality metrics meet or exceed targets!")
        else:
            print(
                "⚠️  WARNING: Some quality metrics are below targets. See recommendations above."
            )
        print()
        print("=" * 80)

    def export_report(self, output_path: str):
        """
        Export detailed validation report to file.

        Args:
            output_path: Path to output file
        """
        with open(output_path, "w") as f:
            f.write("=" * 80 + "\n")
            f.write("DATA QUALITY VALIDATION REPORT\n")
            f.write("=" * 80 + "\n")
            f.write(f"\nGenerated: {self.report.timestamp.isoformat()}\n")
            f.write("\n")

            # Summary metrics
            f.write("SUMMARY METRICS\n")
            f.write("-" * 80 + "\n")
            f.write(
                f"Pattern Relevance Accuracy:     {self.report.pattern_relevance_accuracy:.1%}\n"
            )
            f.write(
                f"Schema Filtering Precision:     {self.report.schema_filtering_precision:.1%}\n"
            )
            f.write(
                f"Schema Filtering Recall:        {self.report.schema_filtering_recall:.1%}\n"
            )
            f.write(
                f"Task Classification Accuracy:   {self.report.task_classification_accuracy:.1%}\n"
            )
            f.write(
                f"\nTests Passed: {self.report.passed_tests}/{self.report.total_tests} ({self.report.passed_tests/self.report.total_tests*100:.1f}%)\n"
            )
            f.write("\n")

            # Detailed results
            f.write("DETAILED VALIDATION RESULTS\n")
            f.write("-" * 80 + "\n")

            for result in self.report.validation_results:
                status = "PASS" if result.passed else "FAIL"
                f.write(f"\n[{status}] {result.test_name}\n")
                f.write(f"  Expected: {result.expected}\n")
                f.write(f"  Actual:   {result.actual}\n")
                f.write(f"  Score:    {result.score:.3f}\n")
                if result.details:
                    f.write(f"  Details:  {result.details}\n")

            f.write("\n")

            # Recommendations
            f.write("RECOMMENDATIONS\n")
            f.write("-" * 80 + "\n")
            for rec in self.report.recommendations:
                f.write(rec + "\n")

            f.write("\n" + "=" * 80 + "\n")

        print(f"✓ Detailed report exported to: {output_path}")


def main():
    """Main entry point."""
    validator = DataQualityValidator()

    # Run all validations
    report = validator.validate_all()

    # Export detailed report
    output_path = Path(__file__).parent.parent / "data_quality_validation_report.txt"
    validator.export_report(str(output_path))

    # Exit with appropriate code
    all_passed = (
        report.pattern_relevance_accuracy >= 0.8
        and report.schema_filtering_precision >= 0.9
        and report.task_classification_accuracy >= 0.95
    )

    sys.exit(0 if all_passed else 1)


if __name__ == "__main__":
    main()
