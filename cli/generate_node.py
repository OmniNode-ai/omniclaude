#!/usr/bin/env python3
"""
Node Generation CLI - POC Phase 1

Command-line interface for autonomous ONEX node generation from natural
language prompts.

**Phase 1 (POC)**: Direct synchronous calls to GenerationPipeline
**Phase 4 (Future)**: Event bus publish/subscribe pattern

Usage:
    # Direct prompt (default balanced mode)
    poetry run python cli/generate_node.py "Create EFFECT node for database writes"

    # Interactive mode
    poetry run python cli/generate_node.py --interactive

    # With custom output directory
    poetry run python cli/generate_node.py --prompt "..." --output ./nodes

    # Debug mode with verbose logging
    poetry run python cli/generate_node.py --prompt "..." --debug

    # Fast mode (no validation, ~0.7s)
    poetry run python cli/generate_node.py --mode fast "Create EFFECT node..."

    # Strict mode (all validation, ~18s)
    poetry run python cli/generate_node.py --mode strict "Create EFFECT node..."

Examples:
    # Generate PostgreSQL writer node (default balanced mode: 7s, 85% confidence)
    poetry run python cli/generate_node.py \\
        "Create EFFECT node for PostgreSQL database write operations"

    # Generate with strict validation for production (18s, 97% confidence)
    poetry run python cli/generate_node.py \\
        --mode strict \\
        --prompt "Create EFFECT node for Redis cache operations" \\
        --output ./generated_nodes

    # Fast development iteration (0.7s, 70% confidence)
    poetry run python cli/generate_node.py \\
        --mode fast \\
        "Create COMPUTE node for price calculation"

    # Interactive mode for guided generation
    poetry run python cli/generate_node.py --interactive
"""

import argparse
import asyncio
import logging
import sys
from pathlib import Path
from typing import Optional

# Load environment variables from .env file
from dotenv import load_dotenv

load_dotenv()  # Load .env file before any other imports

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from agents.lib.models.pipeline_models import PipelineResult  # noqa: E402
from agents.lib.models.quorum_config import QuorumConfig  # noqa: E402
from cli.lib import CLIHandler  # noqa: E402


def setup_logging(debug: bool = False) -> None:
    """
    Configure logging for CLI.

    Args:
        debug: Enable debug-level logging
    """
    level = logging.DEBUG if debug else logging.INFO

    # Configure root logger
    logging.basicConfig(
        level=level,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    # Reduce noise from third-party libraries
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)


def print_banner() -> None:
    """Print CLI banner."""
    print(
        """
╔════════════════════════════════════════════════════════════════╗
║                 ONEX Node Generation CLI                       ║
║                 Autonomous Code Generation POC                 ║
╚════════════════════════════════════════════════════════════════╝
"""
    )


def print_stage_header(stage_name: str) -> None:
    """
    Print stage execution header.

    Args:
        stage_name: Name of stage starting
    """
    print(f"\n{'─' * 60}")
    print(f"  {stage_name}")
    print(f"{'─' * 60}")


def print_success(result: PipelineResult) -> None:
    """
    Print success message and summary.

    Args:
        result: Pipeline execution result
    """
    print("\n" + "=" * 60)
    print("✅ SUCCESS - Node generation completed!")
    print("=" * 60)
    print()
    print(result.to_summary())
    print()
    print(f"📁 Output directory: {result.output_path}")
    print(f"📄 Generated {len(result.generated_files)} files:")
    for file_path in result.generated_files[:10]:  # Show first 10 files
        print(f"   - {Path(file_path).name}")
    if len(result.generated_files) > 10:
        print(f"   ... and {len(result.generated_files) - 10} more")
    print()


def print_failure(result: PipelineResult) -> None:
    """
    Print failure message and error details.

    Args:
        result: Pipeline execution result
    """
    print("\n" + "=" * 60)
    print("❌ FAILED - Node generation failed")
    print("=" * 60)
    print()
    print(result.to_summary())
    print()

    # Show failed gates
    failed_gates = result.get_failed_gates()
    if failed_gates:
        print(f"Failed validation gates ({len(failed_gates)}):")
        for gate in failed_gates:
            print(f"  ❌ {gate.gate_id} - {gate.name}")
            print(f"     {gate.message}")
        print()

    # Show error summary
    if result.error_summary:
        print(f"Error: {result.error_summary}")
        print()


def print_warnings(result: PipelineResult) -> None:
    """
    Print warning gates if any.

    Args:
        result: Pipeline execution result
    """
    warnings = result.get_warning_gates()
    if warnings:
        print(f"\n⚠️  Warnings ({len(warnings)}):")
        for gate in warnings:
            print(f"  ⚠️  {gate.gate_id} - {gate.name}")
            print(f"     {gate.message}")
        print()


async def generate_node_interactive(handler: CLIHandler) -> Optional[PipelineResult]:
    """
    Interactive mode for node generation.

    Args:
        handler: CLI handler instance

    Returns:
        Pipeline result or None if cancelled
    """
    print("\n📝 Interactive Node Generation")
    print("=" * 60)

    # Get prompt
    print("\nDescribe the node you want to generate:")
    print("(Example: Create EFFECT node for PostgreSQL database write operations)")
    print()
    prompt = input("Prompt: ").strip()

    if not prompt:
        print("❌ Prompt cannot be empty")
        return None

    # Get output directory
    print("\nOutput directory (default: ./output):")
    output_dir = input("Directory: ").strip() or "./output"

    # Confirm
    print("\n" + "─" * 60)
    print("Configuration:")
    print(f"  Prompt: {prompt}")
    print(f"  Output: {output_dir}")
    print("─" * 60)
    confirm = input("\nProceed with generation? [Y/n]: ").strip().lower()

    if confirm and confirm != "y":
        print("❌ Cancelled")
        return None

    # Generate
    print("\n🚀 Starting generation...")
    result = await handler.generate_node(
        prompt=prompt,
        output_directory=output_dir,
    )

    return result


async def generate_node_direct(
    handler: CLIHandler,
    prompt: str,
    output_dir: str,
) -> PipelineResult:
    """
    Direct mode for node generation.

    Args:
        handler: CLI handler instance
        prompt: Node generation prompt
        output_dir: Output directory

    Returns:
        Pipeline execution result
    """
    print("\n🚀 Generating node from prompt...")
    print(f"📝 Prompt: {prompt}")
    print(f"📁 Output: {output_dir}")
    print()

    result = await handler.generate_node(
        prompt=prompt,
        output_directory=output_dir,
    )

    return result


async def main() -> int:
    """
    Main CLI entry point.

    Returns:
        Exit code (0 for success, 1 for failure)
    """
    # Parse arguments
    parser = argparse.ArgumentParser(
        description="Generate ONEX nodes from natural language prompts",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Direct prompt
  %(prog)s "Create EFFECT node for database writes"

  # Interactive mode
  %(prog)s --interactive

  # Custom output directory
  %(prog)s --prompt "Create EFFECT node for Redis cache" --output ./nodes

  # Debug mode
  %(prog)s --prompt "..." --debug
        """,
    )

    parser.add_argument(
        "prompt",
        nargs="?",
        help="Node generation prompt (natural language description)",
    )
    parser.add_argument(
        "--interactive",
        "-i",
        action="store_true",
        help="Interactive mode with guided prompts",
    )
    parser.add_argument(
        "--prompt",
        "-p",
        help="Node generation prompt (alternative to positional arg)",
    )
    parser.add_argument(
        "--output",
        "-o",
        default="./output",
        help="Output directory for generated files (default: ./output)",
    )
    parser.add_argument(
        "--debug",
        "-d",
        action="store_true",
        help="Enable debug logging",
    )
    parser.add_argument(
        "--no-compile",
        action="store_true",
        help="Skip compilation testing (Stage 6)",
    )
    parser.add_argument(
        "--mode",
        "-m",
        choices=["fast", "balanced", "standard", "strict"],
        default="balanced",
        help=(
            "Execution mode (speed vs quality tradeoff). "
            "fast: No validation (0.7s, 70%% confidence), "
            "balanced: PRD + Contract validation (7s, 85%% confidence) [DEFAULT], "
            "standard: Most stages validated (10s, 92%% confidence), "
            "strict: All stages validated (18s, 97%% confidence)"
        ),
    )
    parser.add_argument(
        "--interactive-checkpoints",
        action="store_true",
        help="Enable interactive checkpoints during pipeline execution",
    )

    args = parser.parse_args()

    # Setup logging
    setup_logging(debug=args.debug)

    # Print banner
    print_banner()

    # Validate arguments
    prompt = args.prompt or args.prompt  # Use --prompt if provided
    if not args.interactive and not prompt:
        parser.print_help()
        print("\n❌ Error: Either provide a prompt or use --interactive mode")
        return 1

    # Create quorum config from execution mode
    quorum_config = QuorumConfig.from_mode(args.mode)

    # Show mode info
    print(f"\n⚙️  Execution Mode: {args.mode}")
    print("   Validation stages: ", end="")
    stages = []
    if quorum_config.validate_prd_analysis:
        stages.append("PRD")
    if quorum_config.validate_intelligence:
        stages.append("Intelligence")
    if quorum_config.validate_contract:
        stages.append("Contract")
    if quorum_config.validate_node_code:
        stages.append("Node Code")
    print(", ".join(stages) if stages else "None (fast mode)")
    if args.interactive_checkpoints:
        print("   Interactive checkpoints: ENABLED")
    print()

    # Initialize CLI handler with async context manager for proper cleanup
    async with CLIHandler(
        enable_compilation_testing=not args.no_compile,
        quorum_config=quorum_config,
        interactive_mode=args.interactive_checkpoints,
    ) as handler:
        try:
            # Validate output directory
            handler.validate_output_directory(args.output)

            # Generate node
            if args.interactive:
                result = await generate_node_interactive(handler)
                if result is None:
                    return 1  # Cancelled
            else:
                result = await generate_node_direct(
                    handler=handler,
                    prompt=prompt,
                    output_dir=args.output,
                )

            # Display results
            if result.success:
                print_success(result)
                print_warnings(result)  # Show warnings even on success
                return 0
            else:
                print_failure(result)
                return 1

        except KeyboardInterrupt:
            print("\n\n❌ Cancelled by user")
            return 1

        except Exception as e:
            print(f"\n❌ Unexpected error: {e}")
            if args.debug:
                import traceback

                traceback.print_exc()
            return 1


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)
