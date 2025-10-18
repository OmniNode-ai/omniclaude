"""
Test script for dynamic agent loader validation.

Tests:
- Loading all 50+ agent configurations
- Pydantic schema validation
- Capability indexing
- Trigger matching
- Hot-reload simulation
- Integration with ParallelCoordinator
"""

import asyncio
import sys
from pathlib import Path
from typing import Dict, Any

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent))

from agent_loader import AgentLoader, AgentLoadStatus
from agent_dispatcher import ParallelCoordinator
from agent_model import AgentTask


class AgentLoaderValidator:
    """Comprehensive validation for agent loader."""

    def __init__(self):
        self.results: Dict[str, Any] = {}
        self.passed_tests = 0
        self.failed_tests = 0

    async def run_all_tests(self):
        """Run all validation tests."""
        print("=" * 80)
        print("AGENT LOADER VALIDATION SUITE")
        print("=" * 80)
        print()

        # Test 1: Basic loader initialization
        await self.test_loader_initialization()

        # Test 2: Load all agent configs
        await self.test_load_all_configs()

        # Test 3: Validate agent configurations
        await self.test_config_validation()

        # Test 4: Test capability indexing
        await self.test_capability_indexing()

        # Test 5: Test trigger matching
        await self.test_trigger_matching()

        # Test 6: Test agent selection
        await self.test_agent_selection()

        # Test 7: Test hot-reload simulation
        await self.test_hot_reload()

        # Test 8: Test coordinator integration
        await self.test_coordinator_integration()

        # Summary
        self.print_summary()

    async def test_loader_initialization(self):
        """Test basic loader initialization."""
        test_name = "Loader Initialization"
        print(f"[TEST] {test_name}")

        try:
            loader = AgentLoader(enable_hot_reload=False)
            loaded_agents = await loader.initialize()

            if len(loaded_agents) > 0:
                print(f"  ✅ Loaded {len(loaded_agents)} agent configurations")
                self.results[test_name] = {"status": "PASSED", "count": len(loaded_agents)}
                self.passed_tests += 1
            else:
                print("  ❌ No agents loaded")
                self.results[test_name] = {"status": "FAILED", "error": "No agents loaded"}
                self.failed_tests += 1

            await loader.cleanup()

        except Exception as e:
            print(f"  ❌ Error: {str(e)}")
            self.results[test_name] = {"status": "FAILED", "error": str(e)}
            self.failed_tests += 1

        print()

    async def test_load_all_configs(self):
        """Test loading all 50+ agent configurations."""
        test_name = "Load All Configurations"
        print(f"[TEST] {test_name}")

        try:
            loader = AgentLoader(enable_hot_reload=False)
            await loader.initialize()

            stats = loader.get_agent_stats()
            total = stats["total_agents"]
            loaded = stats["loaded_agents"]
            failed = stats["failed_agents"]

            print(f"  📊 Total agents: {total}")
            print(f"  ✅ Successfully loaded: {loaded}")
            print(f"  ❌ Failed to load: {failed}")

            if failed > 0:
                print("\n  Failed agents:")
                for name, agent in loader.agents.items():
                    if agent.status == AgentLoadStatus.FAILED:
                        print(f"    - {name}: {agent.error}")

            if loaded >= 45:  # Allow up to 5 failures
                self.results[test_name] = {"status": "PASSED", "loaded": loaded, "failed": failed}
                self.passed_tests += 1
            else:
                self.results[test_name] = {"status": "FAILED", "loaded": loaded, "failed": failed}
                self.failed_tests += 1

            await loader.cleanup()

        except Exception as e:
            print(f"  ❌ Error: {str(e)}")
            self.results[test_name] = {"status": "FAILED", "error": str(e)}
            self.failed_tests += 1

        print()

    async def test_config_validation(self):
        """Test Pydantic schema validation."""
        test_name = "Configuration Validation"
        print(f"[TEST] {test_name}")

        try:
            loader = AgentLoader(enable_hot_reload=False)
            loaded_agents = await loader.initialize()

            validation_results = []

            for name, agent in loaded_agents.items():
                if agent.status == AgentLoadStatus.LOADED:
                    config = agent.config

                    # Validate required fields
                    required_fields = ["agent_domain", "agent_purpose", "agent_title", "agent_description", "triggers"]

                    missing_fields = [field for field in required_fields if not getattr(config, field, None)]

                    if missing_fields:
                        validation_results.append({"agent": name, "status": "INVALID", "missing": missing_fields})
                    else:
                        validation_results.append({"agent": name, "status": "VALID"})

            valid_count = sum(1 for r in validation_results if r["status"] == "VALID")
            invalid_count = sum(1 for r in validation_results if r["status"] == "INVALID")

            print(f"  ✅ Valid configurations: {valid_count}")
            print(f"  ❌ Invalid configurations: {invalid_count}")

            if invalid_count > 0:
                print("\n  Invalid agents:")
                for result in validation_results:
                    if result["status"] == "INVALID":
                        print(f"    - {result['agent']}: Missing {result['missing']}")

            if invalid_count == 0:
                self.results[test_name] = {"status": "PASSED", "valid": valid_count}
                self.passed_tests += 1
            else:
                self.results[test_name] = {"status": "FAILED", "valid": valid_count, "invalid": invalid_count}
                self.failed_tests += 1

            await loader.cleanup()

        except Exception as e:
            print(f"  ❌ Error: {str(e)}")
            self.results[test_name] = {"status": "FAILED", "error": str(e)}
            self.failed_tests += 1

        print()

    async def test_capability_indexing(self):
        """Test capability indexing functionality."""
        test_name = "Capability Indexing"
        print(f"[TEST] {test_name}")

        try:
            loader = AgentLoader(enable_hot_reload=False)
            await loader.initialize()

            stats = loader.get_agent_stats()
            capabilities_indexed = stats["capabilities_indexed"]

            print(f"  📊 Total capabilities indexed: {capabilities_indexed}")

            # Test specific capability lookups
            test_capabilities = [
                "quality_intelligence",
                "template_system",
                "mandatory_functions",
                "onex_compliance_validation",
            ]

            for capability in test_capabilities:
                agents = loader.get_agents_by_capability(capability)
                print(f"  ✅ '{capability}': {len(agents)} agents")

            if capabilities_indexed > 0:
                self.results[test_name] = {"status": "PASSED", "count": capabilities_indexed}
                self.passed_tests += 1
            else:
                self.results[test_name] = {"status": "FAILED", "count": 0}
                self.failed_tests += 1

            await loader.cleanup()

        except Exception as e:
            print(f"  ❌ Error: {str(e)}")
            self.results[test_name] = {"status": "FAILED", "error": str(e)}
            self.failed_tests += 1

        print()

    async def test_trigger_matching(self):
        """Test trigger-based agent matching."""
        test_name = "Trigger Matching"
        print(f"[TEST] {test_name}")

        try:
            loader = AgentLoader(enable_hot_reload=False)
            await loader.initialize()

            # Test specific trigger lookups
            test_triggers = [
                ("debug", "agent-debug-intelligence"),
                ("generate", "agent-contract-driven-generator"),
                ("api", "agent-api-architect"),
                ("investigate", "agent-debug-intelligence"),
            ]

            matched = 0
            for trigger, expected_agent in test_triggers:
                agents = loader.get_agents_by_trigger(trigger)
                if agents and expected_agent in agents:
                    print(f"  ✅ Trigger '{trigger}' -> {expected_agent}")
                    matched += 1
                else:
                    print(f"  ⚠️  Trigger '{trigger}' -> {agents if agents else 'No match'}")

            if matched >= len(test_triggers) * 0.75:  # 75% match rate
                self.results[test_name] = {"status": "PASSED", "matched": matched}
                self.passed_tests += 1
            else:
                self.results[test_name] = {"status": "FAILED", "matched": matched}
                self.failed_tests += 1

            await loader.cleanup()

        except Exception as e:
            print(f"  ❌ Error: {str(e)}")
            self.results[test_name] = {"status": "FAILED", "error": str(e)}
            self.failed_tests += 1

        print()

    async def test_agent_selection(self):
        """Test dynamic agent selection in coordinator."""
        test_name = "Agent Selection"
        print(f"[TEST] {test_name}")

        try:
            coordinator = ParallelCoordinator(enable_hot_reload=False, use_dynamic_loading=True)
            await coordinator.initialize()

            # Test task-based agent selection
            test_tasks = [
                ("Debug the authentication bug", "agent-debug-intelligence"),
                ("Generate contract-driven code", "agent-contract-driven-generator"),
                ("Design REST API", "agent-api-architect"),
            ]

            matched = 0
            for description, expected_agent in test_tasks:
                task = AgentTask(task_id=f"test-{matched}", description=description, dependencies=[])

                selected_agent = coordinator._select_agent_for_task(task)
                if selected_agent == expected_agent:
                    print(f"  ✅ '{description}' -> {selected_agent}")
                    matched += 1
                else:
                    print(f"  ⚠️  '{description}' -> {selected_agent} (expected {expected_agent})")

            if matched >= len(test_tasks) * 0.66:  # 66% match rate
                self.results[test_name] = {"status": "PASSED", "matched": matched}
                self.passed_tests += 1
            else:
                self.results[test_name] = {"status": "FAILED", "matched": matched}
                self.failed_tests += 1

            await coordinator.cleanup()

        except Exception as e:
            print(f"  ❌ Error: {str(e)}")
            self.results[test_name] = {"status": "FAILED", "error": str(e)}
            self.failed_tests += 1

        print()

    async def test_hot_reload(self):
        """Test hot-reload simulation (without actual file changes)."""
        test_name = "Hot-Reload Capability"
        print(f"[TEST] {test_name}")

        try:
            loader = AgentLoader(enable_hot_reload=False)
            await loader.initialize()

            # Test reload_agent method
            agent_name = "agent-debug-intelligence"
            initial_load_time = loader.agents[agent_name].load_time_ms

            # Simulate reload
            reloaded_agent = await loader.reload_agent(agent_name)

            if reloaded_agent and reloaded_agent.status == AgentLoadStatus.LOADED:
                print(f"  ✅ Agent '{agent_name}' reloaded successfully")
                print(f"  📊 Initial load: {initial_load_time:.2f}ms")
                print(f"  📊 Reload time: {reloaded_agent.load_time_ms:.2f}ms")
                self.results[test_name] = {"status": "PASSED"}
                self.passed_tests += 1
            else:
                print(f"  ❌ Failed to reload agent '{agent_name}'")
                self.results[test_name] = {"status": "FAILED"}
                self.failed_tests += 1

            await loader.cleanup()

        except Exception as e:
            print(f"  ❌ Error: {str(e)}")
            self.results[test_name] = {"status": "FAILED", "error": str(e)}
            self.failed_tests += 1

        print()

    async def test_coordinator_integration(self):
        """Test full integration with ParallelCoordinator."""
        test_name = "Coordinator Integration"
        print(f"[TEST] {test_name}")

        try:
            # Test with dynamic loading
            coordinator = ParallelCoordinator(enable_hot_reload=False, use_dynamic_loading=True)
            await coordinator.initialize()

            stats = coordinator.get_agent_registry_stats()
            print(f"  📊 Registry stats: {stats}")

            if stats.get("loaded_agents", 0) > 0:
                print(f"  ✅ Coordinator initialized with {stats['loaded_agents']} agents")
                self.results[test_name] = {"status": "PASSED", "stats": stats}
                self.passed_tests += 1
            else:
                print("  ❌ No agents loaded in coordinator")
                self.results[test_name] = {"status": "FAILED", "stats": stats}
                self.failed_tests += 1

            await coordinator.cleanup()

        except Exception as e:
            print(f"  ❌ Error: {str(e)}")
            self.results[test_name] = {"status": "FAILED", "error": str(e)}
            self.failed_tests += 1

        print()

    def print_summary(self):
        """Print test summary."""
        print("=" * 80)
        print("TEST SUMMARY")
        print("=" * 80)
        print(f"Total tests: {self.passed_tests + self.failed_tests}")
        print(f"✅ Passed: {self.passed_tests}")
        print(f"❌ Failed: {self.failed_tests}")
        print()

        if self.failed_tests == 0:
            print("🎉 ALL TESTS PASSED! Dynamic agent loading is ready for production.")
        else:
            print("⚠️  Some tests failed. Review the output above for details.")

        print("=" * 80)


async def main():
    """Run validation suite."""
    validator = AgentLoaderValidator()
    await validator.run_all_tests()


if __name__ == "__main__":
    asyncio.run(main())
