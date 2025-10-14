#!/usr/bin/env python3
"""
Test script to validate all agent configurations.
"""

import asyncio
import sys
from pathlib import Path

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent))

from agent_loader import AgentLoader, AgentLoadStatus


async def main():
    """Test loading all agent configurations."""
    print("🔧 Testing all agent configurations...\n")

    # Initialize loader
    loader = AgentLoader(enable_hot_reload=False)
    agents = await loader.initialize()

    # Get stats
    stats = loader.get_agent_stats()

    print(f"📊 Agent Loading Statistics:")
    print(f"   Total Agents: {stats['total_agents']}")
    print(f"   Successfully Loaded: {stats['loaded_agents']}")
    print(f"   Failed: {stats['failed_agents']}")
    print(f"   Capabilities Indexed: {stats['capabilities_indexed']}\n")

    # Show successful loads
    successful = [name for name, agent in agents.items() if agent.status == AgentLoadStatus.LOADED]
    if successful:
        print(f"✅ Successfully Loaded Agents ({len(successful)}):")
        for name in sorted(successful):
            agent = agents[name]
            print(f"   - {name} ({agent.load_time_ms:.2f}ms)")
        print()

    # Show failures
    failed = {name: agent for name, agent in agents.items() if agent.status == AgentLoadStatus.FAILED}
    if failed:
        print(f"❌ Failed Agents ({len(failed)}):")
        for name, agent in sorted(failed.items()):
            print(f"   - {name}")
            print(f"     Error: {agent.error}")
        print()

    # Cleanup
    await loader.cleanup()

    # Exit code based on results
    if failed:
        print(f"⚠️  {len(failed)} agent(s) failed validation")
        sys.exit(1)
    else:
        print("✨ All agents loaded successfully!")
        sys.exit(0)


if __name__ == "__main__":
    asyncio.run(main())
