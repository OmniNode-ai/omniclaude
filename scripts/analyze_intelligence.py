#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""
Intelligence Analysis Script

Queries the omniclaude knowledge base via the intelligence event client
to discover code quality, patterns, and architectural insights.

Usage:
    poetry run python analyze_intelligence.py
"""

import asyncio
import json
import sys
from datetime import UTC, datetime
from enum import Enum
from pathlib import Path
from typing import Any

# NOTE: sys.path modification required for standalone script execution
# This script runs from project root and needs to import from agents/lib
# which is not in a standard Python package structure. This allows the script
# to function as a standalone analysis tool without requiring package installation.
# Alternative: Convert to proper package with pyproject.toml entry point.
sys.path.insert(0, str(Path(__file__).parent / "agents" / "lib"))

from intelligence_event_client import IntelligenceEventClient


class OperationType(str, Enum):
    """Operation types for intelligence requests."""

    QUALITY_ASSESSMENT = "QUALITY_ASSESSMENT"
    PATTERN_EXTRACTION = "PATTERN_EXTRACTION"


async def analyze_code_quality(
    client: IntelligenceEventClient, paths: list[str]
) -> dict[str, Any]:
    """
    Analyze code quality for specified paths.

    Args:
        client: IntelligenceEventClient instance for making requests
        paths: List of file paths to analyze

    Returns:
        Dictionary mapping file paths to quality analysis results

    Raises:
        Exception: If analysis fails for any reason

    Example:
        >>> results = await analyze_code_quality(client, ["path/to/file.py"])
        >>> print(results["path/to/file.py"]["quality_score"])
    """
    results = {}

    for path in paths:
        try:
            print(f"\n🔍 Analyzing quality: {path}")

            # Read file content
            file_path = Path(path)
            if not file_path.exists():
                print(f"  ⚠️  File not found: {path}")
                results[path] = {"error": "file_not_found"}
                continue

            content = file_path.read_text(encoding="utf-8")

            result = await client.request_code_analysis(
                content=content,  # Provide actual file content
                source_path=path,
                language="python",
                options={
                    "operation_type": OperationType.QUALITY_ASSESSMENT.value,
                    "include_metrics": True,
                    "include_recommendations": True,
                },
                timeout_ms=10000,
            )
            results[path] = result

            # Display summary
            quality_score = result.get("quality_score", 0.0)
            onex_compliance = result.get("onex_compliance", 0.0)
            print(f"  ✓ Quality Score: {quality_score:.2f}")
            print(f"  ✓ ONEX Compliance: {onex_compliance:.2f}")

            issues = result.get("issues", [])
            if issues:
                print(f"  ⚠️  Issues found: {len(issues)}")
                for issue in issues[:3]:  # Show first 3
                    print(f"     - {issue.get('message', 'Unknown issue')}")

        except TimeoutError:
            print(f"  ⏱️  Timeout analyzing {path}")
            results[path] = {"error": "timeout"}
        except Exception as e:
            print(f"  ❌ Error analyzing {path}: {e}")
            results[path] = {"error": str(e)}

    return results


async def discover_patterns(
    client: IntelligenceEventClient, patterns: list[str]
) -> dict[str, Any]:
    """
    Discover architectural patterns in the codebase.

    Args:
        client: IntelligenceEventClient instance for making requests
        patterns: List of pattern paths or glob patterns to search

    Returns:
        Dictionary mapping pattern searches to discovery results

    Raises:
        Exception: If pattern discovery fails for any reason

    Example:
        >>> results = await discover_patterns(client, ["agents/lib/*.py"])
        >>> print(len(results["agents/lib/*.py"]))
    """
    results = {}

    for pattern in patterns:
        try:
            print(f"\n🔎 Discovering pattern: {pattern}")
            result = await client.request_pattern_discovery(
                source_path=pattern,
                language="python",
                timeout_ms=10000,
            )
            results[pattern] = result

            if isinstance(result, list):
                print(f"  ✓ Found {len(result)} matches")
                for item in result[:5]:  # Show first 5
                    file_path = item.get("file_path", "unknown")
                    confidence = item.get("confidence", 0.0)
                    print(f"     - {file_path} (confidence: {confidence:.2f})")
            elif isinstance(result, dict):
                patterns_found = result.get("patterns", [])
                print(f"  ✓ Found {len(patterns_found)} patterns")

        except TimeoutError:
            print(f"  ⏱️  Timeout discovering pattern {pattern}")
            results[pattern] = {"error": "timeout"}
        except Exception as e:
            print(f"  ❌ Error discovering pattern {pattern}: {e}")
            results[pattern] = {"error": str(e)}

    return results


async def extract_insights(
    client: IntelligenceEventClient, paths: list[str]
) -> dict[str, Any]:
    """
    Extract architectural insights and recommendations.

    Args:
        client: IntelligenceEventClient instance for making requests
        paths: List of file or directory paths to analyze

    Returns:
        Dictionary mapping paths to extracted insights and recommendations

    Raises:
        Exception: If insight extraction fails for any reason

    Example:
        >>> results = await extract_insights(client, ["agents/"])
        >>> print(results["agents/"]["recommendations"])
    """
    results = {}

    for path in paths:
        try:
            print(f"\n💡 Extracting insights: {path}")

            # Check if path is a directory
            path_obj = Path(path)
            if path_obj.is_dir():
                # For directories, aggregate analysis from key files
                py_files = list(path_obj.glob("**/*.py"))[:5]  # Limit to 5 files
                if not py_files:
                    print(f"  ⚠️  No Python files found in {path}")
                    results[path] = {"error": "no_files"}
                    continue

                # Analyze first file as representative
                content = py_files[0].read_text(encoding="utf-8")
                source_path = str(py_files[0])
                print(f"  📄 Analyzing representative file: {py_files[0].name}")
            else:
                if not path_obj.exists():
                    print(f"  ⚠️  File not found: {path}")
                    results[path] = {"error": "file_not_found"}
                    continue
                content = path_obj.read_text(encoding="utf-8")
                source_path = path

            result = await client.request_code_analysis(
                content=content,
                source_path=source_path,
                language="python",
                options={
                    "operation_type": OperationType.PATTERN_EXTRACTION.value,
                    "include_patterns": True,
                    "include_metrics": True,
                    "include_recommendations": True,
                },
                timeout_ms=10000,
            )
            results[path] = result

            # Display insights
            recommendations = result.get("recommendations", [])
            if recommendations:
                print(f"  ✓ Recommendations: {len(recommendations)}")
                for rec in recommendations[:3]:  # Show first 3
                    print(f"     - {rec.get('message', 'Unknown recommendation')}")

            patterns = result.get("patterns", [])
            if patterns:
                print(f"  ✓ Patterns found: {len(patterns)}")

        except TimeoutError:
            print(f"  ⏱️  Timeout extracting insights from {path}")
            results[path] = {"error": "timeout"}
        except Exception as e:
            print(f"  ❌ Error extracting insights from {path}: {e}")
            results[path] = {"error": str(e)}

    return results


async def main():
    """
    Main analysis workflow.

    Returns:
        Exit code (0 for success, 1 for failure)

    Raises:
        Exception: If analysis workflow fails

    Example:
        >>> exit_code = await main()
        >>> sys.exit(exit_code)
    """
    print("=" * 80)
    print("OMNICLAUDE INTELLIGENCE ANALYSIS")
    print("=" * 80)
    print("\nConnecting to intelligence services...")

    # Initialize client
    client = IntelligenceEventClient(
        bootstrap_servers="localhost:9092",  # Redpanda external port
        enable_intelligence=True,
        request_timeout_ms=10000,
    )

    try:
        # Start client
        await client.start()
        print("✓ Connected to intelligence event bus")

        # Check health
        if not await client.health_check():
            print("⚠️  Intelligence services may be unavailable")
            print("   Continuing with best effort...")
        else:
            print("✓ Intelligence services healthy")

        # 1. Code Quality Assessment
        print("\n" + "=" * 80)
        print("1. CODE QUALITY ASSESSMENT")
        print("=" * 80)

        quality_paths = [
            "agents/lib/enhanced_router.py",
            "agents/lib/intelligence_event_client.py",
            "hooks/pre_write.py",
            "skills/agent-tracking/log-routing-decision/execute_kafka.py",
        ]

        quality_results = await analyze_code_quality(client, quality_paths)

        # 2. Pattern Discovery
        print("\n" + "=" * 80)
        print("2. ARCHITECTURAL PATTERN DISCOVERY")
        print("=" * 80)

        pattern_searches = [
            "agents/lib/*.py",
            "hooks/*.py",
            "skills/**/execute_kafka.py",
            "omnibase_*/models/model_*.py",
        ]

        pattern_results = await discover_patterns(client, pattern_searches)

        # 3. Insights Extraction
        print("\n" + "=" * 80)
        print("3. ARCHITECTURAL INSIGHTS")
        print("=" * 80)

        insight_paths = [
            "agents/",
            "omnibase_core/",
            "hooks/",
        ]

        insight_results = await extract_insights(client, insight_paths)

        # 4. Generate Summary Report
        print("\n" + "=" * 80)
        print("4. SUMMARY REPORT")
        print("=" * 80)

        # Calculate overall quality score
        valid_quality_scores = []
        for path, result in quality_results.items():
            if isinstance(result, dict) and "quality_score" in result:
                valid_quality_scores.append(result["quality_score"])

        if valid_quality_scores:
            avg_quality = sum(valid_quality_scores) / len(valid_quality_scores)
            print(f"\n📊 Average Quality Score: {avg_quality:.2f}")

        # Calculate ONEX compliance
        valid_onex_scores = []
        for path, result in quality_results.items():
            if isinstance(result, dict) and "onex_compliance" in result:
                valid_onex_scores.append(result["onex_compliance"])

        if valid_onex_scores:
            avg_onex = sum(valid_onex_scores) / len(valid_onex_scores)
            print(f"📊 Average ONEX Compliance: {avg_onex:.2f}")

        # Count patterns discovered
        total_patterns = 0
        for pattern, result in pattern_results.items():
            if isinstance(result, list):
                total_patterns += len(result)
            elif isinstance(result, dict) and "patterns" in result:
                total_patterns += len(result["patterns"])

        print(f"🔍 Total Patterns Discovered: {total_patterns}")

        # Count recommendations
        total_recommendations = 0
        for path, result in {**quality_results, **insight_results}.items():
            if isinstance(result, dict) and "recommendations" in result:
                total_recommendations += len(result["recommendations"])

        print(f"💡 Total Recommendations: {total_recommendations}")

        # Save detailed results
        output_file = Path("intelligence_analysis_results.json")
        full_results = {
            "timestamp": datetime.now(UTC).isoformat(),
            "quality_assessment": quality_results,
            "pattern_discovery": pattern_results,
            "insights": insight_results,
        }

        with open(output_file, "w") as f:
            json.dump(full_results, f, indent=2)

        print(f"\n💾 Detailed results saved to: {output_file}")

        print("\n" + "=" * 80)
        print("ANALYSIS COMPLETE")
        print("=" * 80)

    except Exception as e:
        print(f"\n❌ Analysis failed: {e}")
        import traceback

        traceback.print_exc()
        return 1

    finally:
        # Stop client
        await client.stop()
        print("\n✓ Disconnected from intelligence services")

    return 0


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)
