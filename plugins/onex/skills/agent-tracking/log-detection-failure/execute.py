#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""
Log Detection Failure Skill - Track agent detection failures in PostgreSQL

Logs failures in agent detection, capturing critical observability gaps when
the routing system fails to identify the appropriate agent.

Usage:
  /log-detection-failure --prompt "user request text" --reason "no matching triggers" --candidates-evaluated 5

Options:
  --prompt: User prompt that failed detection (required)
  --reason: Reason for detection failure (required)
  --candidates-evaluated: Number of agents evaluated (required)
  --correlation-id: Correlation ID for tracking (optional, auto-generated)
  --status: Detection status (optional, default: no_detection)
            Valid: no_detection, low_confidence, wrong_agent, timeout, error
  --detected-agent: Agent that was detected (if any)
  --confidence: Detection confidence score 0.0-1.0 (optional)
  --expected-agent: Expected agent name (if known)
  --detection-method: Method used for detection (optional)
  --trigger-matches: JSON array of trigger match results (optional)
  --capability-scores: JSON object with capability scores (optional)
  --fuzzy-results: JSON array of fuzzy match results (optional)
  --metadata: Additional JSON metadata (optional)
"""

import argparse
import hashlib
import json
import sys
from pathlib import Path

# Add _shared to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "_shared"))
from db_helper import (
    execute_query,
    get_correlation_id,
    handle_db_error,
    parse_json_param,
)


def compute_prompt_hash(prompt: str) -> str:
    """Compute SHA-256 hash of prompt for deduplication."""
    return hashlib.sha256(prompt.encode("utf-8")).hexdigest()


def log_detection_failure(args):
    """Log a detection failure to the database."""

    # Get or generate correlation ID
    correlation_id = (
        args.correlation_id if args.correlation_id else get_correlation_id()
    )

    # Parse JSON parameters
    trigger_matches = (
        parse_json_param(args.trigger_matches)
        if hasattr(args, "trigger_matches") and args.trigger_matches
        else []
    )
    capability_scores = (
        parse_json_param(args.capability_scores)
        if hasattr(args, "capability_scores") and args.capability_scores
        else {}
    )
    fuzzy_results = (
        parse_json_param(args.fuzzy_results)
        if hasattr(args, "fuzzy_results") and args.fuzzy_results
        else []
    )
    metadata = (
        parse_json_param(args.metadata)
        if hasattr(args, "metadata") and args.metadata
        else {}
    )

    # Validate detection status
    valid_statuses = [
        "no_detection",
        "low_confidence",
        "wrong_agent",
        "timeout",
        "error",
    ]
    status = args.status if hasattr(args, "status") and args.status else "no_detection"
    if status not in valid_statuses:
        return handle_db_error(
            ValueError(
                f"Invalid status '{status}'. Must be one of: {', '.join(valid_statuses)}"
            ),
            "log_detection_failure",
        )

    # Validate confidence if provided
    confidence = None
    if hasattr(args, "confidence") and args.confidence:
        confidence = float(args.confidence)
        if confidence < 0.0 or confidence > 1.0:
            return handle_db_error(
                ValueError(
                    f"Confidence score must be between 0.0 and 1.0, got {confidence}"
                ),
                "log_detection_failure",
            )

    # Compute prompt hash
    prompt_hash = compute_prompt_hash(args.prompt)

    # Prepare SQL
    sql = """
    INSERT INTO agent_detection_failures (
        correlation_id,
        user_prompt,
        prompt_length,
        prompt_hash,
        detection_status,
        detected_agent,
        detection_confidence,
        detection_method,
        routing_duration_ms,
        failure_reason,
        expected_agent,
        trigger_matches,
        capability_scores,
        fuzzy_match_results,
        detection_metadata
    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
    RETURNING id, created_at
    """

    params = (
        correlation_id,
        args.prompt,
        len(args.prompt),
        prompt_hash,
        status,
        (
            args.detected_agent
            if hasattr(args, "detected_agent") and args.detected_agent
            else None
        ),
        confidence,
        (
            args.detection_method
            if hasattr(args, "detection_method") and args.detection_method
            else None
        ),
        None,  # routing_duration_ms - not available at detection failure time
        args.reason,
        (
            args.expected_agent
            if hasattr(args, "expected_agent") and args.expected_agent
            else None
        ),
        json.dumps(trigger_matches),
        json.dumps(capability_scores),
        json.dumps(fuzzy_results),
        json.dumps(metadata),
    )

    try:
        result = execute_query(sql, params, fetch=True)
        if result and len(result) > 0:
            row = result[0]
            output = {
                "success": True,
                "failure_id": row["id"],
                "correlation_id": correlation_id,
                "detection_status": status,
                "failure_reason": args.reason,
                "candidates_evaluated": int(args.candidates_evaluated),
                "prompt_length": len(args.prompt),
                "created_at": row["created_at"].isoformat(),
            }
            print(json.dumps(output, indent=2))
            return 0
        else:
            error = {"success": False, "error": "No result returned from database"}
            print(json.dumps(error), file=sys.stderr)
            return 1

    except Exception as e:
        error_info = handle_db_error(e, "log_detection_failure")
        print(json.dumps(error_info), file=sys.stderr)
        return 1


def main():
    parser = argparse.ArgumentParser(
        description="Log agent detection failure to PostgreSQL",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )

    # Required arguments
    parser.add_argument(
        "--prompt", required=True, help="User prompt that failed detection"
    )
    parser.add_argument("--reason", required=True, help="Reason for detection failure")
    parser.add_argument(
        "--candidates-evaluated",
        required=True,
        type=int,
        help="Number of agents evaluated",
    )

    # Optional arguments
    parser.add_argument("--correlation-id", help="Correlation ID for tracking")
    parser.add_argument("--status", help="Detection status (default: no_detection)")
    parser.add_argument("--detected-agent", help="Agent that was detected (if any)")
    parser.add_argument(
        "--confidence", type=float, help="Detection confidence score (0.0-1.0)"
    )
    parser.add_argument("--expected-agent", help="Expected agent name (if known)")
    parser.add_argument("--detection-method", help="Method used for detection")
    parser.add_argument("--trigger-matches", help="JSON array of trigger match results")
    parser.add_argument(
        "--capability-scores", help="JSON object with capability scores"
    )
    parser.add_argument("--fuzzy-results", help="JSON array of fuzzy match results")
    parser.add_argument("--metadata", help="Additional JSON metadata")

    args = parser.parse_args()

    return log_detection_failure(args)


if __name__ == "__main__":
    sys.exit(main())
