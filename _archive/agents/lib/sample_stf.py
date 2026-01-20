"""
Sample STF (State-Transformation Function) for testing real code loading.

This demonstrates how real STF functions can be loaded and executed.
"""


def fix_validation_error(error_type: str, context: dict) -> dict:
    """
    Fix validation errors by providing corrective suggestions.

    Args:
        error_type: Type of validation error
        context: Additional context about the error

    Returns:
        Dictionary with fix suggestions and confidence
    """
    suggestions = []
    confidence = 0.8

    if error_type == "VALIDATION_ERROR":
        if "task_breakdown" in str(context).lower():
            suggestions.append("Review task breakdown for completeness")
            suggestions.append("Ensure all required fields are present")
            suggestions.append("Validate task dependencies")
            confidence = 0.9
        elif "quorum" in str(context).lower():
            suggestions.append("Increase quorum confidence threshold")
            suggestions.append("Add more validation criteria")
            suggestions.append("Review quorum decision logic")
            confidence = 0.85
        else:
            suggestions.append("Review validation criteria")
            suggestions.append("Check input data format")
            confidence = 0.7

    return {
        "fixed": True,
        "suggestions": suggestions,
        "confidence": confidence,
        "applied_fixes": len(suggestions),
        "error_type": error_type,
        "context_analyzed": True,
    }


def optimize_performance(metrics: dict) -> dict:
    """
    Optimize performance based on metrics.

    Args:
        metrics: Performance metrics dictionary

    Returns:
        Dictionary with optimization recommendations
    """
    optimizations = []
    expected_improvement = 0.0

    if metrics.get("duration_ms", 0) > 1000:
        optimizations.append("Consider caching frequently accessed data")
        optimizations.append("Implement batch processing")
        expected_improvement += 0.3

    if metrics.get("memory_usage", 0) > 0.8:
        optimizations.append("Implement memory pooling")
        optimizations.append("Reduce object creation")
        expected_improvement += 0.2

    if metrics.get("error_rate", 0) > 0.1:
        optimizations.append("Add retry logic with exponential backoff")
        optimizations.append("Implement circuit breaker pattern")
        expected_improvement += 0.4

    return {
        "optimized": True,
        "optimizations": optimizations,
        "expected_improvement": expected_improvement,
        "priority": "high" if expected_improvement > 0.5 else "medium",
    }


def enhance_security(security_context: dict) -> dict:
    """
    Enhance security based on context.

    Args:
        security_context: Security-related context

    Returns:
        Dictionary with security enhancements
    """
    enhancements = []
    risk_level = "low"

    if security_context.get("has_pii", False):
        enhancements.append("Implement PII redaction")
        enhancements.append("Add data encryption")
        risk_level = "high"

    if security_context.get("external_api", False):
        enhancements.append("Add API rate limiting")
        enhancements.append("Implement request validation")
        risk_level = "medium"

    if security_context.get("user_input", False):
        enhancements.append("Add input sanitization")
        enhancements.append("Implement SQL injection protection")
        risk_level = "medium"

    return {
        "secured": True,
        "enhancements": enhancements,
        "risk_level": risk_level,
        "compliance_improved": len(enhancements) > 0,
    }
