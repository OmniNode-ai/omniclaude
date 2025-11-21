#!/usr/bin/env python3
"""
Interactive Node Generation Example

Demonstrates how to use the generation pipeline with interactive checkpoints
for human-in-the-loop validation.

Usage:
    # Interactive mode with checkpoints
    python examples/interactive_generation_example.py --interactive

    # Non-interactive mode (no checkpoints)
    python examples/interactive_generation_example.py

    # With session save/resume
    python examples/interactive_generation_example.py --interactive --session /tmp/my_session.json
"""

import argparse
import asyncio
import logging
import sys
from pathlib import Path


# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from agents.lib.generation_pipeline import GenerationPipeline


# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)


async def generate_node_interactive(
    prompt: str,
    output_dir: str,
    interactive: bool = False,
    session_file: Path | None = None,
):
    """
    Generate a node with optional interactive checkpoints.

    Args:
        prompt: Natural language prompt describing the node
        output_dir: Directory to write generated files
        interactive: Enable interactive checkpoints
        session_file: Optional session file for save/resume
    """
    print("\n" + "=" * 60)
    print("OMNINODE GENERATION PIPELINE")
    print("=" * 60)
    print(f"\nPrompt: {prompt}")
    print(f"Output directory: {output_dir}")
    print(f"Interactive mode: {interactive}")
    if session_file:
        print(f"Session file: {session_file}")
    print()

    # Create pipeline with interactive mode
    pipeline = GenerationPipeline(
        enable_compilation_testing=False,  # Disable for speed
        enable_intelligence_gathering=True,  # Enable RAG intelligence
        interactive_mode=interactive,
        session_file=session_file,
    )

    try:
        # Execute generation pipeline
        result = await pipeline.execute(
            prompt=prompt,
            output_directory=output_dir,
        )

        # Display results
        print("\n" + "=" * 60)
        print("GENERATION RESULTS")
        print("=" * 60)
        print(f"\nStatus: {result.status}")
        print(f"Duration: {result.duration_seconds:.2f}s")
        print(f"Node type: {result.node_type}")
        print(f"Service name: {result.service_name}")
        print(f"Domain: {result.domain}")
        print(f"Validation passed: {result.validation_passed}")

        if result.generated_files:
            print(f"\nGenerated files ({len(result.generated_files)}):")
            for file_path in result.generated_files[:5]:
                print(f"  - {file_path}")
            if len(result.generated_files) > 5:
                print(f"  ... and {len(result.generated_files) - 5} more")

        if result.error_summary:
            print(f"\nError: {result.error_summary}")

        return result

    except KeyboardInterrupt:
        print("\n\n⚠️  Generation interrupted by user")
        if interactive and session_file:
            print(f"Session saved to: {session_file}")
            print(f"Resume with: --session {session_file}")
        return None

    except Exception as e:
        print(f"\n\n❌ Generation failed: {e}")
        logging.exception("Pipeline execution failed")
        return None

    finally:
        # Cleanup async resources
        await pipeline.cleanup_async()


async def main():
    """Main entry point"""
    parser = argparse.ArgumentParser(
        description="Generate ONEX nodes with interactive validation"
    )
    parser.add_argument(
        "--prompt",
        type=str,
        default="Create an EFFECT node called EmailSender for sending notification emails",
        help="Natural language prompt describing the node",
    )
    parser.add_argument(
        "--output-dir",
        type=str,
        default="/tmp/generated_nodes",
        help="Output directory for generated files",
    )
    parser.add_argument(
        "--interactive",
        action="store_true",
        help="Enable interactive checkpoints",
    )
    parser.add_argument(
        "--session",
        type=Path,
        default=None,
        help="Session file for save/resume",
    )

    args = parser.parse_args()

    # Generate node
    result = await generate_node_interactive(
        prompt=args.prompt,
        output_dir=args.output_dir,
        interactive=args.interactive,
        session_file=args.session,
    )

    # Exit with status code
    if result and result.status == "success":
        print("\n✅ Generation completed successfully!")
        return 0
    else:
        print("\n❌ Generation failed or was interrupted")
        return 1


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)
