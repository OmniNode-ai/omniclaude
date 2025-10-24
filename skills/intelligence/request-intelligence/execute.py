#!/usr/bin/env python3
"""
Request Intelligence Skill - Agent Intelligence Operations

Allows agents to request intelligence operations from the Omni Archon intelligence
adapter, including pattern discovery, code analysis, and quality assessment.

Usage:
  /request-intelligence --operation pattern-discovery --source-path "node_*_effect.py" --language python
  /request-intelligence --operation code-analysis --file path/to/file.py --language python
  /request-intelligence --operation quality-assessment --content "code here" --language python

Operations:
  pattern-discovery: Find similar code patterns in the codebase
  code-analysis: Analyze code for quality, compliance, and issues
  quality-assessment: Assess code quality and ONEX compliance

Options:
  --operation: Type of intelligence operation (required)
  --source-path: File pattern or path to analyze (required for pattern-discovery)
  --file: Specific file to analyze (required for code-analysis/quality-assessment)
  --content: Code content to analyze (alternative to --file)
  --language: Programming language (default: python)
  --timeout-ms: Request timeout in milliseconds (default: 10000)
  --include-metrics: Include detailed metrics in response (default: false)
  --correlation-id: Correlation ID for tracking (optional, auto-generated)
"""

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path
from typing import Any, Dict, Optional

# Add omniclaude agents/lib to path for IntelligenceEventClient
OMNICLAUDE_PATH = Path(
    os.environ.get("OMNICLAUDE_PATH", "/Volumes/PRO-G40/Code/omniclaude")
)
sys.path.insert(0, str(OMNICLAUDE_PATH / "agents" / "lib"))

try:
    from intelligence_event_client import IntelligenceEventClient
except ImportError as e:
    print(
        json.dumps(
            {
                "success": False,
                "error": f"Failed to import IntelligenceEventClient: {e}",
                "hint": "Set OMNICLAUDE_PATH environment variable or ensure omniclaude is in the expected location",
            }
        ),
        file=sys.stderr,
    )
    sys.exit(1)


# Add _shared to path for helper functions
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "_shared"))
from db_helper import get_correlation_id  # noqa: E402

OPERATION_TYPES = {
    "pattern-discovery": "PATTERN_EXTRACTION",
    "code-analysis": "CODE_ANALYSIS",
    "quality-assessment": "QUALITY_ASSESSMENT",
}


async def request_pattern_discovery(
    client: IntelligenceEventClient,
    source_path: str,
    language: str,
    timeout_ms: int,
    correlation_id: str,
) -> Dict[str, Any]:
    """Request pattern discovery from intelligence adapter."""
    try:
        patterns = await client.request_pattern_discovery(
            source_path=source_path,
            language=language,
            timeout_ms=timeout_ms,
        )

        return {
            "success": True,
            "operation": "pattern-discovery",
            "correlation_id": correlation_id,
            "source_path": source_path,
            "language": language,
            "patterns_found": len(patterns),
            "patterns": patterns,
        }

    except TimeoutError:
        return {
            "success": False,
            "operation": "pattern-discovery",
            "correlation_id": correlation_id,
            "error": f"Request timeout after {timeout_ms}ms",
            "hint": "Intelligence adapter may be down or overloaded. Try increasing timeout or check service health.",
        }

    except Exception as e:
        return {
            "success": False,
            "operation": "pattern-discovery",
            "correlation_id": correlation_id,
            "error": str(e),
            "error_type": type(e).__name__,
        }


async def request_code_analysis(
    client: IntelligenceEventClient,
    content: Optional[str],
    source_path: str,
    language: str,
    include_metrics: bool,
    timeout_ms: int,
    correlation_id: str,
) -> Dict[str, Any]:
    """Request code analysis from intelligence adapter."""
    try:
        # Read file content if not provided
        if content is None and source_path:
            file_path = Path(source_path)
            if not file_path.exists():
                return {
                    "success": False,
                    "operation": "code-analysis",
                    "correlation_id": correlation_id,
                    "error": f"File not found: {source_path}",
                }
            content = file_path.read_text()

        result = await client.request_code_analysis(
            content=content,
            source_path=source_path,
            language=language,
            options={
                "operation_type": "CODE_ANALYSIS",
                "include_metrics": include_metrics,
            },
            timeout_ms=timeout_ms,
        )

        return {
            "success": True,
            "operation": "code-analysis",
            "correlation_id": correlation_id,
            "source_path": source_path,
            "language": language,
            **result,
        }

    except TimeoutError:
        return {
            "success": False,
            "operation": "code-analysis",
            "correlation_id": correlation_id,
            "error": f"Request timeout after {timeout_ms}ms",
            "hint": "Intelligence adapter may be down or overloaded. Try increasing timeout or check service health.",
        }

    except Exception as e:
        return {
            "success": False,
            "operation": "code-analysis",
            "correlation_id": correlation_id,
            "error": str(e),
            "error_type": type(e).__name__,
        }


async def request_quality_assessment(
    client: IntelligenceEventClient,
    content: Optional[str],
    source_path: str,
    language: str,
    include_metrics: bool,
    timeout_ms: int,
    correlation_id: str,
) -> Dict[str, Any]:
    """Request quality assessment from intelligence adapter."""
    try:
        # Read file content if not provided
        if content is None and source_path:
            file_path = Path(source_path)
            if not file_path.exists():
                return {
                    "success": False,
                    "operation": "quality-assessment",
                    "correlation_id": correlation_id,
                    "error": f"File not found: {source_path}",
                }
            content = file_path.read_text()

        result = await client.request_code_analysis(
            content=content,
            source_path=source_path,
            language=language,
            options={
                "operation_type": "QUALITY_ASSESSMENT",
                "include_metrics": include_metrics,
                "include_onex_compliance": True,
            },
            timeout_ms=timeout_ms,
        )

        return {
            "success": True,
            "operation": "quality-assessment",
            "correlation_id": correlation_id,
            "source_path": source_path,
            "language": language,
            **result,
        }

    except TimeoutError:
        return {
            "success": False,
            "operation": "quality-assessment",
            "correlation_id": correlation_id,
            "error": f"Request timeout after {timeout_ms}ms",
            "hint": "Intelligence adapter may be down or overloaded. Try increasing timeout or check service health.",
        }

    except Exception as e:
        return {
            "success": False,
            "operation": "quality-assessment",
            "correlation_id": correlation_id,
            "error": str(e),
            "error_type": type(e).__name__,
        }


async def main():
    """Main execution function."""
    parser = argparse.ArgumentParser(
        description="Request intelligence operations from Omni Archon intelligence adapter",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )

    # Required arguments
    parser.add_argument(
        "--operation",
        required=True,
        choices=list(OPERATION_TYPES.keys()),
        help="Type of intelligence operation to request",
    )

    # Operation-specific arguments
    parser.add_argument("--source-path", help="File pattern or path to analyze")
    parser.add_argument("--file", help="Specific file to analyze")
    parser.add_argument(
        "--content", help="Code content to analyze (alternative to --file)"
    )
    parser.add_argument(
        "--language", default="python", help="Programming language (default: python)"
    )

    # Optional arguments
    parser.add_argument(
        "--timeout-ms",
        type=int,
        default=10000,
        help="Request timeout in milliseconds (default: 10000)",
    )
    parser.add_argument(
        "--include-metrics",
        action="store_true",
        help="Include detailed metrics in response",
    )
    parser.add_argument("--correlation-id", help="Correlation ID for tracking")

    # Intelligence adapter configuration
    parser.add_argument(
        "--kafka-brokers",
        default=os.environ.get("KAFKA_BROKERS", "localhost:29102"),
        help="Kafka bootstrap servers (default: localhost:29102)",
    )

    args = parser.parse_args()

    # Get or generate correlation ID
    correlation_id = (
        args.correlation_id if args.correlation_id else get_correlation_id()
    )

    # Validate operation-specific arguments
    if args.operation == "pattern-discovery":
        if not args.source_path:
            print(
                json.dumps(
                    {
                        "success": False,
                        "error": "--source-path is required for pattern-discovery operation",
                    }
                ),
                file=sys.stderr,
            )
            return 1
    elif args.operation in ("code-analysis", "quality-assessment"):
        if not args.file and not args.content and not args.source_path:
            print(
                json.dumps(
                    {
                        "success": False,
                        "error": "Either --file, --content, or --source-path is required for this operation",
                    }
                ),
                file=sys.stderr,
            )
            return 1

    # Determine source_path
    source_path = args.source_path or args.file or "inline"

    # Create intelligence event client
    client = IntelligenceEventClient(
        bootstrap_servers=args.kafka_brokers,
        enable_intelligence=True,
        request_timeout_ms=args.timeout_ms,
    )

    try:
        # Start client
        await client.start()

        # Health check
        if not await client.health_check():
            print(
                json.dumps(
                    {
                        "success": False,
                        "error": "Intelligence adapter health check failed",
                        "hint": "Ensure Kafka broker is running and intelligence adapter is healthy",
                        "kafka_brokers": args.kafka_brokers,
                    }
                ),
                file=sys.stderr,
            )
            return 1

        # Dispatch operation
        if args.operation == "pattern-discovery":
            result = await request_pattern_discovery(
                client=client,
                source_path=args.source_path,
                language=args.language,
                timeout_ms=args.timeout_ms,
                correlation_id=correlation_id,
            )
        elif args.operation == "code-analysis":
            result = await request_code_analysis(
                client=client,
                content=args.content,
                source_path=source_path,
                language=args.language,
                include_metrics=args.include_metrics,
                timeout_ms=args.timeout_ms,
                correlation_id=correlation_id,
            )
        elif args.operation == "quality-assessment":
            result = await request_quality_assessment(
                client=client,
                content=args.content,
                source_path=source_path,
                language=args.language,
                include_metrics=args.include_metrics,
                timeout_ms=args.timeout_ms,
                correlation_id=correlation_id,
            )
        else:
            print(
                json.dumps(
                    {
                        "success": False,
                        "error": f"Unknown operation: {args.operation}",
                    }
                ),
                file=sys.stderr,
            )
            return 1

        # Output result
        print(json.dumps(result, indent=2))
        return 0 if result.get("success", False) else 1

    finally:
        # Always stop client
        await client.stop()


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
