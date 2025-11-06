#!/usr/bin/env python3
"""
Pre-Prompt-Submit Hook with Memory Management

This hook runs before every prompt submission to Claude Code.
It provides intelligent context injection using:
- Intent extraction from user prompts
- Memory retrieval based on intent
- Workspace state updates
- Relevant pattern injection

Flow:
1. Extract intent from user prompt
2. Query memory for relevant context
3. Rank memories by relevance
4. Update workspace state
5. Inject selected context into prompt
6. Return enhanced prompt to Claude

Performance Target: <100ms overhead
"""

import asyncio
import json
import logging
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from claude_hooks.lib.memory_client import get_memory_client
from claude_hooks.lib.intent_extractor import extract_intent, rank_memories_by_intent
from config import settings

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


async def get_workspace_state() -> Dict[str, Any]:
    """Collect current workspace state"""
    try:
        import subprocess

        # Get git information
        try:
            branch = subprocess.check_output(
                ['git', 'rev-parse', '--abbrev-ref', 'HEAD'],
                stderr=subprocess.DEVNULL,
                text=True
            ).strip()
        except:
            branch = "unknown"

        try:
            modified_files = subprocess.check_output(
                ['git', 'status', '--porcelain'],
                stderr=subprocess.DEVNULL,
                text=True
            ).strip().split('\n')
            modified_files = [f.strip() for f in modified_files if f.strip()]
        except:
            modified_files = []

        try:
            last_commit = subprocess.check_output(
                ['git', 'rev-parse', '--short', 'HEAD'],
                stderr=subprocess.DEVNULL,
                text=True
            ).strip()
        except:
            last_commit = "unknown"

        return {
            "branch": branch,
            "modified_files": modified_files[:10],  # Limit to 10 files
            "last_commit": last_commit,
            "timestamp": datetime.utcnow().isoformat(),
            "cwd": os.getcwd()
        }
    except Exception as e:
        logger.error(f"Failed to collect workspace state: {e}")
        return {
            "branch": "unknown",
            "modified_files": [],
            "last_commit": "unknown",
            "timestamp": datetime.utcnow().isoformat(),
            "cwd": os.getcwd()
        }


async def query_relevant_memories(intent: Any, max_tokens: int = 5000) -> Dict[str, Any]:
    """Query memory for items relevant to intent"""
    memory = get_memory_client()
    relevant_memories = {}

    try:
        # Get workspace state
        workspace_state = await memory.get_memory("workspace_state", "workspace")
        if workspace_state:
            relevant_memories["workspace_state"] = workspace_state

        # Get success patterns for task type
        if intent.task_type:
            pattern_key = f"success_patterns_{intent.task_type}"
            patterns = await memory.get_memory(pattern_key, "patterns")
            if patterns:
                relevant_memories[pattern_key] = patterns

        # Get execution history for entities
        for entity in intent.entities[:5]:  # Limit to 5 entities
            entity_key = f"execution_history_{entity.lower().replace(' ', '_')}"
            history = await memory.get_memory(entity_key, "execution_history")
            if history:
                relevant_memories[entity_key] = history

        # Get file context for mentioned files
        for file in intent.files[:5]:  # Limit to 5 files
            file_key = f"file_context_{file.replace('/', '_').replace('.', '_')}"
            file_ctx = await memory.get_memory(file_key, "workspace")
            if file_ctx:
                relevant_memories[file_key] = file_ctx

        # Rank by relevance and apply token budget
        if relevant_memories:
            ranked = await rank_memories_by_intent(
                relevant_memories,
                intent,
                max_tokens=max_tokens
            )
            return ranked

        return relevant_memories

    except Exception as e:
        logger.error(f"Failed to query memories: {e}")
        return {}


async def update_memory_with_workspace(workspace_state: Dict[str, Any]) -> None:
    """Update memory with current workspace state"""
    memory = get_memory_client()

    try:
        await memory.store_memory(
            key="workspace_state",
            value=workspace_state,
            category="workspace",
            metadata={"updated_by": "pre_prompt_submit_hook"}
        )
        logger.info("Updated workspace state in memory")
    except Exception as e:
        logger.error(f"Failed to update workspace state: {e}")


def format_context_for_injection(
    intent: Any,
    memories: Dict[str, Any],
    workspace_state: Dict[str, Any]
) -> str:
    """Format memory context for injection into prompt"""

    lines = []
    lines.append("\n" + "=" * 70)
    lines.append("CONTEXT FROM MEMORY (Intent-Driven Retrieval)")
    lines.append("=" * 70)
    lines.append("")

    # Intent summary
    lines.append("## Detected Intent")
    lines.append(f"- Task Type: {intent.task_type or 'unknown'}")
    if intent.entities:
        lines.append(f"- Entities: {', '.join(intent.entities[:5])}")
    if intent.files:
        lines.append(f"- Files: {', '.join(intent.files[:5])}")
    if intent.operations:
        lines.append(f"- Operations: {', '.join(intent.operations)}")
    lines.append("")

    # Workspace state
    lines.append("## Current Workspace")
    lines.append(f"- Branch: {workspace_state.get('branch', 'unknown')}")
    if workspace_state.get('modified_files'):
        lines.append(f"- Modified Files: {len(workspace_state['modified_files'])} files")
        for f in workspace_state['modified_files'][:5]:
            lines.append(f"  - {f}")
    lines.append("")

    # Relevant memories
    if memories:
        lines.append(f"## Relevant Context ({len(memories)} items)")
        lines.append("")

        for key, value in memories.items():
            lines.append(f"### {key}")

            # Format value based on type
            if isinstance(value, dict):
                # Pretty print dict
                lines.append("```json")
                lines.append(json.dumps(value, indent=2)[:500])  # Truncate if too long
                if len(json.dumps(value)) > 500:
                    lines.append("... (truncated)")
                lines.append("```")
            elif isinstance(value, list):
                lines.append(f"- {len(value)} items")
                for item in value[:3]:  # Show first 3
                    lines.append(f"  - {str(item)[:100]}")
                if len(value) > 3:
                    lines.append(f"  ... and {len(value) - 3} more")
            else:
                lines.append(str(value)[:200])

            lines.append("")
    else:
        lines.append("## Relevant Context")
        lines.append("No relevant context found in memory for this intent.")
        lines.append("")

    lines.append("=" * 70)
    lines.append("")

    return "\n".join(lines)


async def main(user_prompt: str) -> str:
    """
    Main hook execution

    Args:
        user_prompt: The user's input prompt

    Returns:
        Enhanced prompt with memory context injected
    """
    start_time = datetime.utcnow()

    try:
        # Check if memory client is enabled
        if not settings.enable_memory_client:
            logger.info("Memory client disabled, skipping enhancement")
            return user_prompt

        # Extract intent from prompt
        intent = await extract_intent(user_prompt, use_llm=settings.enable_intent_extraction)
        logger.info(f"Extracted intent: task_type={intent.task_type}, "
                   f"entities={intent.entities[:3]}, "
                   f"confidence={intent.confidence}")

        # Collect workspace state
        workspace_state = await get_workspace_state()

        # Update memory with workspace state (non-blocking)
        asyncio.create_task(update_memory_with_workspace(workspace_state))

        # Query relevant memories
        relevant_memories = await query_relevant_memories(
            intent,
            max_tokens=settings.memory_max_tokens
        )
        logger.info(f"Retrieved {len(relevant_memories)} relevant memory items")

        # Format context for injection
        context = format_context_for_injection(intent, relevant_memories, workspace_state)

        # Inject context into prompt
        enhanced_prompt = f"{context}\n\n{user_prompt}"

        # Log performance
        duration_ms = (datetime.utcnow() - start_time).total_seconds() * 1000
        logger.info(f"Hook completed in {duration_ms:.0f}ms")

        if duration_ms > 100:
            logger.warning(f"Hook exceeded 100ms target: {duration_ms:.0f}ms")

        return enhanced_prompt

    except Exception as e:
        logger.error(f"Hook failed: {e}", exc_info=True)
        # Return original prompt on error (graceful degradation)
        return user_prompt


if __name__ == "__main__":
    # Read prompt from stdin or args
    if len(sys.argv) > 1:
        prompt = " ".join(sys.argv[1:])
    else:
        prompt = sys.stdin.read().strip()

    if not prompt:
        logger.error("No prompt provided")
        sys.exit(1)

    # Run async main
    enhanced = asyncio.run(main(prompt))

    # Output enhanced prompt
    print(enhanced)
