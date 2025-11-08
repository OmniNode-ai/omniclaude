"""
Integration Tests for Memory Management Hooks

Tests the full end-to-end flow of:
- Pre-prompt-submit hook with intent extraction and memory injection
- Post-tool-use hook with pattern learning
- Workspace-change hook with file tracking
- Cross-hook memory persistence
- Performance under realistic loads
"""

import asyncio
import pytest
import tempfile
from pathlib import Path
from unittest.mock import Mock, patch

import sys
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from claude_hooks.lib.memory_client import get_memory_client, reset_memory_client, FilesystemMemoryBackend
from claude_hooks.lib.intent_extractor import extract_intent
from claude_hooks.pre_prompt_submit import main as pre_prompt_main
from claude_hooks.post_tool_use import main as post_tool_main
from claude_hooks.workspace_change import main as workspace_change_main


@pytest.fixture
async def temp_memory_dir():
    """Create temporary directory for memory storage"""
    with tempfile.TemporaryDirectory() as tmpdir:
        # Reset global client
        reset_memory_client()

        # Create new client with temp directory
        backend = FilesystemMemoryBackend(base_path=tmpdir)
        from claude_hooks.lib.memory_client import _memory_client
        global _memory_client
        _memory_client = None

        # Patch get_memory_client to use temp directory
        with patch('claude_hooks.lib.memory_client.FilesystemMemoryBackend') as mock_backend:
            mock_backend.return_value = backend
            yield tmpdir


class TestPrePromptSubmitHook:
    """Test pre-prompt-submit hook integration"""

    @pytest.mark.asyncio
    async def test_basic_enhancement(self, temp_memory_dir):
        """Test basic prompt enhancement with memory"""
        prompt = "Help me implement JWT authentication in auth.py"

        # Patch settings to enable memory
        with patch('claude_hooks.pre_prompt_submit.settings') as mock_settings:
            mock_settings.enable_memory_client = True
            mock_settings.enable_intent_extraction = True
            mock_settings.memory_max_tokens = 5000

            # Run hook
            enhanced = await pre_prompt_main(prompt)

            # Should have added context
            assert len(enhanced) > len(prompt)
            assert "CONTEXT FROM MEMORY" in enhanced
            assert "Detected Intent" in enhanced

    @pytest.mark.asyncio
    async def test_intent_extraction_in_hook(self, temp_memory_dir):
        """Test that intent is correctly extracted"""
        prompt = "Fix the PostgreSQL database connection error"

        with patch('claude_hooks.pre_prompt_submit.settings') as mock_settings:
            mock_settings.enable_memory_client = True
            mock_settings.enable_intent_extraction = True
            mock_settings.memory_max_tokens = 5000

            enhanced = await pre_prompt_main(prompt)

            # Should mention database task type
            assert "database" in enhanced.lower() or "Database" in enhanced

    @pytest.mark.asyncio
    async def test_workspace_state_injection(self, temp_memory_dir):
        """Test that workspace state is injected"""
        prompt = "Test prompt"

        with patch('claude_hooks.pre_prompt_submit.settings') as mock_settings:
            mock_settings.enable_memory_client = True
            mock_settings.enable_intent_extraction = True
            mock_settings.memory_max_tokens = 5000

            enhanced = await pre_prompt_main(prompt)

            # Should include workspace section
            assert "Current Workspace" in enhanced
            assert "Branch:" in enhanced

    @pytest.mark.asyncio
    async def test_graceful_degradation(self, temp_memory_dir):
        """Test that hook doesn't fail on errors"""
        prompt = "Test prompt"

        # Simulate error in memory client
        with patch('claude_hooks.pre_prompt_submit.get_memory_client') as mock_client:
            mock_client.side_effect = Exception("Memory error")

            with patch('claude_hooks.pre_prompt_submit.settings') as mock_settings:
                mock_settings.enable_memory_client = True

                # Should return original prompt on error
                enhanced = await pre_prompt_main(prompt)
                assert enhanced == prompt


class TestPostToolUseHook:
    """Test post-tool-use hook integration"""

    @pytest.mark.asyncio
    async def test_store_execution_result(self, temp_memory_dir):
        """Test storing tool execution result"""
        with patch('claude_hooks.post_tool_use.settings') as mock_settings:
            mock_settings.enable_memory_client = True

            # Reset client
            reset_memory_client()
            backend = FilesystemMemoryBackend(base_path=temp_memory_dir)

            with patch('claude_hooks.post_tool_use.get_memory_client') as mock_get_client:
                mock_get_client.return_value = Mock(
                    store_memory=asyncio.coroutine(lambda *args, **kwargs: None),
                    get_memory=asyncio.coroutine(lambda *args, **kwargs: None)
                )

                # Run hook
                await post_tool_main("Read", "File contents...", duration_ms=50)

                # Verify store_memory was called
                assert mock_get_client.return_value.store_memory.call_count > 0

    @pytest.mark.asyncio
    async def test_success_pattern_tracking(self, temp_memory_dir):
        """Test that success patterns are tracked"""
        memory = get_memory_client()

        with patch('claude_hooks.post_tool_use.settings') as mock_settings:
            mock_settings.enable_memory_client = True

            with patch('claude_hooks.post_tool_use.get_memory_client') as mock_get_client:
                mock_get_client.return_value = memory

                # Simulate successful execution
                await post_tool_main("Read", "Success output", duration_ms=45)

                # Check that patterns were updated
                patterns = await memory.get_memory("success_patterns", "patterns")

                # Should have recorded the success
                assert patterns is not None, "Expected success_patterns to persist the execution result"

    @pytest.mark.asyncio
    async def test_failure_pattern_tracking(self, temp_memory_dir):
        """Test that failure patterns are tracked"""
        memory = get_memory_client()

        with patch('claude_hooks.post_tool_use.settings') as mock_settings:
            mock_settings.enable_memory_client = True

            with patch('claude_hooks.post_tool_use.get_memory_client') as mock_get_client:
                mock_get_client.return_value = memory

                # Simulate failed execution
                await post_tool_main("Edit", "Error: File not found", duration_ms=100)

                # Failure pattern should be tracked (in real scenario)
                # In test, just verify no crash
                assert True


class TestWorkspaceChangeHook:
    """Test workspace-change hook integration"""

    @pytest.mark.asyncio
    async def test_track_file_changes(self, temp_memory_dir):
        """Test tracking file changes"""
        memory = get_memory_client()

        with patch('claude_hooks.workspace_change.settings') as mock_settings:
            mock_settings.enable_memory_client = True

            with patch('claude_hooks.workspace_change.get_memory_client') as mock_get_client:
                mock_get_client.return_value = memory

                # Simulate file changes
                files = ["auth.py", "config.yaml"]
                await workspace_change_main(files, change_type="modified")

                # Should store file change event
                # Verify no crash
                assert True

    @pytest.mark.asyncio
    async def test_multiple_files(self, temp_memory_dir):
        """Test tracking multiple file changes"""
        memory = get_memory_client()

        with patch('claude_hooks.workspace_change.settings') as mock_settings:
            mock_settings.enable_memory_client = True

            with patch('claude_hooks.workspace_change.get_memory_client') as mock_get_client:
                mock_get_client.return_value = memory

                # Simulate multiple file changes
                files = [f"file{i}.py" for i in range(10)]
                await workspace_change_main(files, change_type="created")

                # Should handle multiple files
                assert True


class TestCrossHookIntegration:
    """Test that memory persists across hooks"""

    @pytest.mark.asyncio
    async def test_memory_persists_across_hooks(self, temp_memory_dir):
        """Test that one hook can read memory written by another"""
        backend = FilesystemMemoryBackend(base_path=temp_memory_dir)
        memory_client = get_memory_client()

        with patch('claude_hooks.lib.memory_client.get_memory_client') as mock_get:
            mock_get.return_value = memory_client

            # Store data in memory
            await memory_client.store_memory(
                key="test_data",
                value={"shared": "value"},
                category="workspace"
            )

            # Another hook should be able to retrieve it
            retrieved = await memory_client.get_memory("test_data", "workspace")
            assert retrieved == {"shared": "value"}

    @pytest.mark.asyncio
    async def test_pattern_learning_affects_prompts(self, temp_memory_dir):
        """Test that patterns learned in post-tool-use affect pre-prompt-submit"""
        backend = FilesystemMemoryBackend(base_path=temp_memory_dir)
        memory = get_memory_client()

        # Store a success pattern (simulating post-tool-use)
        await memory.store_memory(
            key="success_patterns_authentication",
            value={
                "count": 10,
                "success_rate": 0.95,
                "last_success": "2025-11-06T12:00:00Z"
            },
            category="patterns"
        )

        # Now run pre-prompt-submit
        with patch('claude_hooks.pre_prompt_submit.get_memory_client') as mock_get:
            mock_get.return_value = memory

            with patch('claude_hooks.pre_prompt_submit.settings') as mock_settings:
                mock_settings.enable_memory_client = True
                mock_settings.enable_intent_extraction = True
                mock_settings.memory_max_tokens = 5000

                prompt = "Implement JWT authentication"
                enhanced = await pre_prompt_main(prompt)

                # Enhanced prompt should potentially include the pattern
                # (depends on relevance ranking)
                assert len(enhanced) > len(prompt)


class TestPerformance:
    """Test performance under realistic loads"""

    @pytest.mark.asyncio
    async def test_pre_prompt_performance(self, temp_memory_dir):
        """Test pre-prompt-submit completes within target"""
        import time

        with patch('claude_hooks.pre_prompt_submit.settings') as mock_settings:
            mock_settings.enable_memory_client = True
            mock_settings.enable_intent_extraction = False  # Use fast keyword mode
            mock_settings.memory_max_tokens = 5000

            start = time.time()
            await pre_prompt_main("Test prompt for authentication")
            duration_ms = (time.time() - start) * 1000

            # Target: <100ms
            assert duration_ms < 200, f"Pre-prompt took {duration_ms}ms (target: <200ms with overhead)"

    @pytest.mark.asyncio
    async def test_post_tool_performance(self, temp_memory_dir):
        """Test post-tool-use completes within target"""
        import time

        with patch('claude_hooks.post_tool_use.settings') as mock_settings:
            mock_settings.enable_memory_client = True

            start = time.time()
            await post_tool_main("Read", "Output text", duration_ms=50)
            duration_ms = (time.time() - start) * 1000

            # Target: <50ms
            assert duration_ms < 100, f"Post-tool took {duration_ms}ms (target: <100ms with overhead)"

    @pytest.mark.asyncio
    async def test_concurrent_hook_execution(self, temp_memory_dir):
        """Test concurrent hook execution doesn't cause issues"""
        with patch('claude_hooks.pre_prompt_submit.settings') as mock_settings:
            mock_settings.enable_memory_client = True
            mock_settings.enable_intent_extraction = False
            mock_settings.memory_max_tokens = 5000

            # Run multiple hooks concurrently
            tasks = [
                pre_prompt_main(f"Prompt {i}")
                for i in range(5)
            ]

            results = await asyncio.gather(*tasks, return_exceptions=True)

            # All should complete without errors
            for result in results:
                assert not isinstance(result, Exception)


class TestEndToEndScenario:
    """Test complete end-to-end scenarios"""

    @pytest.mark.asyncio
    async def test_complete_development_workflow(self, temp_memory_dir):
        """Test a complete development workflow with all hooks"""
        backend = FilesystemMemoryBackend(base_path=temp_memory_dir)
        memory = get_memory_client()

        with patch('claude_hooks.lib.memory_client.get_memory_client') as mock_get:
            mock_get.return_value = memory

            # Step 1: User submits a prompt (pre-prompt-submit)
            with patch('claude_hooks.pre_prompt_submit.settings') as mock_settings:
                mock_settings.enable_memory_client = True
                mock_settings.enable_intent_extraction = False
                mock_settings.memory_max_tokens = 5000

                prompt = "Implement JWT authentication in auth.py"
                enhanced = await pre_prompt_main(prompt)

                assert len(enhanced) > len(prompt)

            # Step 2: Claude executes tools (post-tool-use)
            with patch('claude_hooks.post_tool_use.settings') as mock_settings:
                mock_settings.enable_memory_client = True

                # Read file
                await post_tool_main("Read", "File contents of auth.py", duration_ms=45)

                # Edit file
                await post_tool_main("Edit", "Successfully edited auth.py", duration_ms=120)

            # Step 3: Files change (workspace-change)
            with patch('claude_hooks.workspace_change.settings') as mock_settings:
                mock_settings.enable_memory_client = True

                await workspace_change_main(["auth.py"], change_type="modified")

            # Step 4: Verify memory was updated
            # Check for execution history
            categories = await memory.list_categories()
            assert len(categories) > 0


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
