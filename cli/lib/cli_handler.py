#!/usr/bin/env python3
"""
CLI Handler - Abstraction layer for node generation CLI.

This module provides a stable interface for CLI operations that works
across both Phase 1 (direct calls) and Phase 4 (event bus).

**Architecture**:
- Phase 1 (POC): Direct synchronous calls to GenerationPipeline
- Phase 4 (Future): Async event bus publish/subscribe pattern

The interface remains unchanged; only the implementation swaps.
"""

import logging
from pathlib import Path
from typing import Optional
from uuid import UUID, uuid4

# Phase 1: Import GenerationPipeline directly
from agents.lib.generation_pipeline import GenerationPipeline
from agents.lib.models.pipeline_models import PipelineResult

logger = logging.getLogger(__name__)


class CLIHandler:
    """
    CLI handler for node generation operations.

    Provides a stable interface for CLI operations with swappable
    implementation for Phase 1 (direct calls) vs Phase 4 (event bus).
    """

    def __init__(self, enable_compilation_testing: bool = True):
        """
        Initialize CLI handler.

        Args:
            enable_compilation_testing: Enable Stage 6 compilation testing
        """
        self.logger = logging.getLogger(__name__)

        # Phase 1: Direct pipeline instantiation
        self.pipeline = GenerationPipeline(
            enable_compilation_testing=enable_compilation_testing
        )

        # Phase 4: Event bus client (commented for POC)
        # self.event_bus = EventBusClient()
        # self.event_subscriber = EventBusSubscriber()

    async def generate_node(
        self,
        prompt: str,
        output_directory: str,
        correlation_id: Optional[UUID] = None,
    ) -> PipelineResult:
        """
        Generate ONEX node from natural language prompt.

        **Phase 1 (POC)**: Direct call to GenerationPipeline.execute()
        **Phase 4 (Future)**: Publish PromptSubmitted event, subscribe to result

        Args:
            prompt: Natural language description of node to generate
            output_directory: Target directory for generated files
            correlation_id: Optional correlation ID for tracking

        Returns:
            PipelineResult with comprehensive execution metadata

        Raises:
            OnexError: If generation fails at any stage
        """
        correlation_id = correlation_id or uuid4()

        self.logger.info(f"Starting node generation (correlation_id={correlation_id})")

        # =====================================================================
        # Phase 1 (POC): Direct synchronous call
        # =====================================================================
        result = await self.pipeline.execute(
            prompt=prompt,
            output_directory=output_directory,
            correlation_id=correlation_id,
        )

        self.logger.info(
            f"Node generation completed: {result.status} "
            f"(duration={result.duration_seconds:.2f}s)"
        )

        return result

        # =====================================================================
        # Phase 4 (Future): Event bus publish/subscribe
        # =====================================================================
        # Note: Commented code shows Phase 4 implementation pattern
        #
        # # Publish PromptSubmitted event
        # event = ModelPromptSubmitted(
        #     event_type="PromptSubmitted",
        #     event_id=uuid4(),
        #     correlation_id=correlation_id,
        #     timestamp=datetime.utcnow(),
        #     stage="parsing",
        #     status="started",
        #     payload={
        #         "prompt_text": prompt,
        #         "output_directory": output_directory,
        #         "requested_by": "cli_user",
        #     },
        # )
        #
        # # Publish to event bus
        # await self.event_bus.publish(
        #     topic="generation.pipeline.prompt_submitted",
        #     event=event,
        # )
        #
        # # Subscribe to result events
        # result_future = asyncio.Future()
        #
        # async def handle_result(event: Union[ModelPipelineCompleted, ModelPipelineFailed]):
        #     if event.correlation_id == correlation_id:
        #         if event.event_type == "PipelineCompleted":
        #             result_future.set_result(event.to_pipeline_result())
        #         elif event.event_type == "PipelineFailed":
        #             result_future.set_exception(
        #                 OnexError(
        #                     code=EnumCoreErrorCode.OPERATION_FAILED,
        #                     message=event.payload["error_message"],
        #                 )
        #             )
        #
        # # Subscribe to completion/failure events
        # await self.event_subscriber.subscribe(
        #     topics=[
        #         "generation.pipeline.completed",
        #         "generation.pipeline.failed",
        #     ],
        #     handler=handle_result,
        # )
        #
        # # Wait for result (with timeout)
        # result = await asyncio.wait_for(result_future, timeout=300)  # 5 min
        #
        # return result

    def validate_output_directory(self, output_dir: str) -> Path:
        """
        Validate output directory exists and is writable.

        Args:
            output_dir: Output directory path

        Returns:
            Resolved Path object

        Raises:
            ValueError: If directory is invalid or not writable
        """
        path = Path(output_dir).resolve()

        # Create directory if it doesn't exist
        if not path.exists():
            try:
                path.mkdir(parents=True, exist_ok=True)
                self.logger.info(f"Created output directory: {path}")
            except Exception as e:
                raise ValueError(f"Cannot create output directory: {e}")

        # Check if writable
        if not path.is_dir():
            raise ValueError(f"Output path is not a directory: {path}")

        # Test write permissions
        test_file = path / ".write_test"
        try:
            test_file.touch()
            test_file.unlink()
        except Exception as e:
            raise ValueError(f"Output directory not writable: {e}")

        return path

    def format_result_summary(self, result: PipelineResult) -> str:
        """
        Format pipeline result as human-readable summary.

        Args:
            result: Pipeline execution result

        Returns:
            Formatted summary string
        """
        # Use built-in summary method
        return result.to_summary()

    def format_progress_update(
        self, stage_name: str, progress_percent: int, message: str = ""
    ) -> str:
        """
        Format progress update for display.

        Args:
            stage_name: Current stage name
            progress_percent: Progress percentage (0-100)
            message: Optional progress message

        Returns:
            Formatted progress string
        """
        bar_length = 30
        filled = int(bar_length * progress_percent / 100)
        bar = "█" * filled + "░" * (bar_length - filled)

        output = f"[{bar}] {progress_percent}% - {stage_name}"
        if message:
            output += f": {message}"

        return output

    async def cleanup_async(self, timeout: float = 5.0):
        """
        Cleanup async resources (pipeline).

        Args:
            timeout: Maximum time to wait for cleanup (seconds)
        """
        if self.pipeline:
            await self.pipeline.cleanup_async(timeout)
            self.logger.debug("Pipeline cleanup complete")

    async def __aenter__(self):
        """Async context manager entry."""
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit - cleanup resources."""
        await self.cleanup_async()
        return False
