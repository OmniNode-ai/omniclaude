"""Input validation utilities for CLI commands."""

import json
from typing import Any

import click


def validate_confidence_score(confidence: float) -> float:
    """Validate confidence score is between 0 and 1.

    Args:
        confidence: Confidence score to validate

    Returns:
        float: Validated confidence score

    Raises:
        click.BadParameter: If confidence not in valid range
    """
    if not 0.0 <= confidence <= 1.0:
        raise click.BadParameter("Confidence score must be between 0.0 and 1.0")
    return confidence


def validate_agent_name(agent_name: str) -> str:
    """Validate agent name format.

    Args:
        agent_name: Agent name to validate

    Returns:
        str: Validated agent name

    Raises:
        click.BadParameter: If agent name is invalid
    """
    if not agent_name:
        raise click.BadParameter("Agent name cannot be empty")

    # Allow alphanumeric, hyphens, underscores
    if not all(c.isalnum() or c in ["-", "_"] for c in agent_name):
        raise click.BadParameter(
            "Agent name can only contain alphanumeric characters, hyphens, and underscores"
        )

    return agent_name


def validate_json_string(json_str: str) -> dict[str, Any]:
    """Validate and parse JSON string.

    Args:
        json_str: JSON string to validate

    Returns:
        dict: Parsed JSON object

    Raises:
        click.BadParameter: If JSON is invalid
    """
    try:
        parsed = json.loads(json_str)
        if not isinstance(parsed, dict):
            raise click.BadParameter("JSON must be an object/dictionary")
        return parsed
    except json.JSONDecodeError as e:
        raise click.BadParameter(f"Invalid JSON: {e}")


def validate_json_array(json_str: str) -> list:
    """Validate and parse JSON array string.

    Args:
        json_str: JSON array string to validate

    Returns:
        list: Parsed JSON array

    Raises:
        click.BadParameter: If JSON array is invalid
    """
    try:
        parsed = json.loads(json_str)
        if not isinstance(parsed, list):
            raise click.BadParameter("JSON must be an array/list")
        return parsed
    except json.JSONDecodeError as e:
        raise click.BadParameter(f"Invalid JSON: {e}")


def validate_routing_strategy(strategy: str) -> str:
    """Validate routing strategy value.

    Args:
        strategy: Routing strategy to validate

    Returns:
        str: Validated routing strategy

    Raises:
        click.BadParameter: If strategy is invalid
    """
    valid_strategies = [
        "enhanced_fuzzy_matching",
        "exact_match",
        "capability_based",
        "historical_performance",
        "fallback",
        "manual",
    ]

    if strategy not in valid_strategies:
        raise click.BadParameter(
            f"Invalid routing strategy. Must be one of: {', '.join(valid_strategies)}"
        )

    return strategy


def validate_positive_integer(value: int, param_name: str = "value") -> int:
    """Validate value is a positive integer.

    Args:
        value: Value to validate
        param_name: Parameter name for error messages

    Returns:
        int: Validated value

    Raises:
        click.BadParameter: If value is not positive
    """
    if value <= 0:
        raise click.BadParameter(f"{param_name} must be a positive integer")
    return value


def validate_non_negative_integer(value: int, param_name: str = "value") -> int:
    """Validate value is a non-negative integer.

    Args:
        value: Value to validate
        param_name: Parameter name for error messages

    Returns:
        int: Validated value

    Raises:
        click.BadParameter: If value is negative
    """
    if value < 0:
        raise click.BadParameter(f"{param_name} must be non-negative")
    return value


def validate_trigger_match_strategy(strategy: str) -> str:
    """Validate trigger match strategy value.

    Args:
        strategy: Trigger match strategy to validate

    Returns:
        str: Validated strategy

    Raises:
        click.BadParameter: If strategy is invalid
    """
    valid_strategies = [
        "exact_substring",
        "fuzzy_similarity",
        "keyword_overlap",
        "capability_alignment",
        "combined",
    ]

    if strategy not in valid_strategies:
        raise click.BadParameter(
            f"Invalid trigger match strategy. Must be one of: {', '.join(valid_strategies)}"
        )

    return strategy


def validate_required_field(value: str | None, field_name: str) -> str:
    """Validate that a required field is not empty.

    Args:
        value: Field value to validate
        field_name: Name of the field for error messages

    Returns:
        str: Validated field value

    Raises:
        click.BadParameter: If field is empty
    """
    if not value or not value.strip():
        raise click.BadParameter(f"{field_name} is required and cannot be empty")
    return value.strip()
