#!/usr/bin/env python3
"""
Template Helpers

Utility functions for template generation with intelligence context.
"""

from typing import Any, Dict, List


def format_best_practices(practices: List[str], indent: int = 4) -> str:
    """
    Format best practices for template injection.

    Args:
        practices: List of best practice strings
        indent: Number of spaces for indentation

    Returns:
        Formatted string with bullet points
    """
    if not practices:
        return " " * indent + "- Standard ONEX patterns"

    indent_str = " " * indent
    return "\n".join(f"{indent_str}- {p}" for p in practices)


def format_error_scenarios(scenarios: List[str], indent: int = 4) -> str:
    """
    Format error scenarios for template injection.

    Args:
        scenarios: List of error scenario strings
        indent: Number of spaces for indentation

    Returns:
        Formatted string with bullet points
    """
    if not scenarios:
        return " " * indent + "- Standard error handling"

    indent_str = " " * indent
    return "\n".join(f"{indent_str}- {s}" for s in scenarios)


def format_performance_targets(targets: Dict[str, Any], indent: int = 4) -> str:
    """
    Format performance targets for template injection.

    Args:
        targets: Dictionary of performance targets
        indent: Number of spaces for indentation

    Returns:
        Formatted string with key-value pairs
    """
    if not targets:
        return " " * indent + "- Standard performance requirements"

    indent_str = " " * indent
    formatted = []
    for metric, target in targets.items():
        formatted.append(f"{indent_str}- {metric}: {target}")

    return "\n".join(formatted)


def format_domain_patterns(patterns: List[str], indent: int = 4) -> str:
    """
    Format domain-specific patterns for template injection.

    Args:
        patterns: List of domain pattern strings
        indent: Number of spaces for indentation

    Returns:
        Formatted string with bullet points
    """
    if not patterns:
        return " " * indent + "- Standard domain patterns"

    indent_str = " " * indent
    return "\n".join(f"{indent_str}- {p}" for p in patterns)


def detect_pattern_features(practices: List[str]) -> Dict[str, bool]:
    """
    Detect which patterns to include in template based on best practices.

    Args:
        practices: List of best practice strings

    Returns:
        Dictionary of feature flags
    """
    practices_lower = " ".join(practices).lower()

    return {
        "has_connection_pooling": "connection" in practices_lower
        and "pool" in practices_lower,
        "has_circuit_breaker": "circuit" in practices_lower
        and "breaker" in practices_lower,
        "has_retry_logic": "retry" in practices_lower,
        "has_transaction_support": "transaction" in practices_lower,
        "has_caching": "cache" in practices_lower or "caching" in practices_lower,
        "has_validation": "validat" in practices_lower,
        "has_timeout": "timeout" in practices_lower,
        "has_parallel_processing": "parallel" in practices_lower,
        "has_fsm": "fsm" in practices_lower or "state machine" in practices_lower,
        "has_event_sourcing": "event sourcing" in practices_lower,
        "has_lease_management": "lease" in practices_lower,
        "has_saga_pattern": "saga" in practices_lower,
    }


def generate_pattern_code_blocks(
    practices: List[str], node_type: str, indent: int = 12
) -> str:
    """
    Generate code block comments for detected patterns.

    Args:
        practices: List of best practice strings
        node_type: Node type (EFFECT, COMPUTE, REDUCER, ORCHESTRATOR)
        indent: Number of spaces for indentation

    Returns:
        Generated code block comments
    """
    features = detect_pattern_features(practices)
    indent_str = " " * indent
    blocks = []

    if features["has_connection_pooling"]:
        blocks.append(
            f"{indent_str}# Apply connection pooling pattern (from intelligence)"
        )
        blocks.append(f"{indent_str}# TODO: Implement connection pool acquisition\n")

    if features["has_circuit_breaker"]:
        blocks.append(
            f"{indent_str}# Apply circuit breaker pattern (from intelligence)"
        )
        blocks.append(f"{indent_str}# TODO: Implement circuit breaker logic\n")

    if features["has_retry_logic"]:
        blocks.append(f"{indent_str}# Apply retry logic (from intelligence)")
        blocks.append(f"{indent_str}# TODO: Implement exponential backoff retry\n")

    if features["has_transaction_support"]:
        blocks.append(f"{indent_str}# Apply transaction management (from intelligence)")
        blocks.append(f"{indent_str}# TODO: Implement transaction context\n")

    if features["has_caching"] and node_type == "COMPUTE":
        blocks.append(f"{indent_str}# Apply caching pattern (from intelligence)")
        blocks.append(f"{indent_str}# TODO: Implement computation result caching\n")

    if features["has_parallel_processing"] and node_type == "COMPUTE":
        blocks.append(f"{indent_str}# Apply parallel processing (from intelligence)")
        blocks.append(f"{indent_str}# TODO: Implement batch parallel processing\n")

    if features["has_fsm"] and node_type == "REDUCER":
        blocks.append(f"{indent_str}# Apply FSM pattern (from intelligence)")
        blocks.append(f"{indent_str}# TODO: Implement state machine transitions\n")

    if features["has_event_sourcing"] and node_type == "REDUCER":
        blocks.append(f"{indent_str}# Apply event sourcing (from intelligence)")
        blocks.append(f"{indent_str}# TODO: Implement event store integration\n")

    if features["has_lease_management"] and node_type == "ORCHESTRATOR":
        blocks.append(f"{indent_str}# Apply lease management (from intelligence)")
        blocks.append(f"{indent_str}# TODO: Implement lease acquisition and renewal\n")

    if features["has_saga_pattern"] and node_type == "ORCHESTRATOR":
        blocks.append(f"{indent_str}# Apply saga pattern (from intelligence)")
        blocks.append(f"{indent_str}# TODO: Implement compensating transactions\n")

    if features["has_timeout"]:
        blocks.append(f"{indent_str}# Apply timeout mechanism (from intelligence)")
        blocks.append(f"{indent_str}# TODO: Implement operation timeout\n")

    return "\n".join(blocks) if blocks else ""


def generate_testing_section(
    recommendations: List[str], node_type: str, indent: int = 4
) -> str:
    """
    Generate testing recommendations section.

    Args:
        recommendations: List of testing recommendation strings
        node_type: Node type (EFFECT, COMPUTE, REDUCER, ORCHESTRATOR)
        indent: Number of spaces for indentation

    Returns:
        Formatted testing section
    """
    if not recommendations:
        # Default testing recommendations based on node type
        if node_type == "EFFECT":
            recommendations = [
                "Mock external dependencies",
                "Test error handling for I/O failures",
                "Verify retry logic",
            ]
        elif node_type == "COMPUTE":
            recommendations = [
                "Test with edge cases and boundary values",
                "Verify determinism and purity",
                "Performance benchmarks",
            ]
        elif node_type == "REDUCER":
            recommendations = [
                "Test state aggregation across events",
                "Verify intent emission logic",
                "Test FSM transitions",
            ]
        elif node_type == "ORCHESTRATOR":
            recommendations = [
                "Test workflow coordination",
                "Verify lease management",
                "Test compensating transactions",
            ]

    indent_str = " " * indent
    return "\n".join(f"{indent_str}- {r}" for r in recommendations)


def generate_security_section(
    considerations: List[str], node_type: str, indent: int = 4
) -> str:
    """
    Generate security considerations section.

    Args:
        considerations: List of security consideration strings
        node_type: Node type (EFFECT, COMPUTE, REDUCER, ORCHESTRATOR)
        indent: Number of spaces for indentation

    Returns:
        Formatted security section
    """
    if not considerations:
        # Default security considerations based on node type
        if node_type == "EFFECT":
            considerations = [
                "Validate all inputs",
                "Use parameterized queries",
                "Implement rate limiting",
            ]
        elif node_type == "COMPUTE":
            considerations = [
                "Validate computational inputs",
                "Prevent resource exhaustion",
                "Sanitize outputs",
            ]
        elif node_type == "REDUCER":
            considerations = [
                "Validate event sources",
                "Prevent state pollution",
                "Implement event authentication",
            ]
        elif node_type == "ORCHESTRATOR":
            considerations = [
                "Implement workflow authentication",
                "Validate workflow inputs",
                "Prevent unauthorized workflow execution",
            ]

    indent_str = " " * indent
    return "\n".join(f"{indent_str}- {c}" for c in considerations)
