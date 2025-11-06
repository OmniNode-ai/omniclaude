"""
Comprehensive Unit Tests for Intent Extractor

Tests cover:
- Intent extraction (LLM and keyword-based)
- Task type detection
- Entity extraction
- File reference detection
- Operation identification
- Memory ranking algorithm
- Relevance scoring
- Edge cases and error conditions
"""

import asyncio
import pytest
from unittest.mock import Mock, patch, AsyncMock

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from claude_hooks.lib.intent_extractor import (
    Intent,
    extract_intent,
    rank_memories_by_intent,
    _extract_task_type,
    _extract_entities,
    _extract_files,
    _extract_operations,
    _calculate_relevance_score,
    _estimate_tokens
)


class TestIntentExtraction:
    """Test intent extraction"""

    @pytest.mark.asyncio
    async def test_extract_intent_authentication(self):
        """Test extracting authentication intent"""
        prompt = "Help me implement JWT authentication in auth.py"

        intent = await extract_intent(prompt, use_llm=False)  # Use keyword fallback

        assert intent.task_type == "authentication"
        assert "JWT" in intent.entities
        assert "auth.py" in intent.files
        assert "implement" in intent.operations

    @pytest.mark.asyncio
    async def test_extract_intent_database(self):
        """Test extracting database intent"""
        prompt = "Fix the PostgreSQL query in database.py"

        intent = await extract_intent(prompt, use_llm=False)

        assert intent.task_type == "database"
        assert "PostgreSQL" in intent.entities
        assert "database.py" in intent.files
        assert "fix" in intent.operations

    @pytest.mark.asyncio
    async def test_extract_intent_api(self):
        """Test extracting API intent"""
        prompt = "Create a new REST API endpoint for user management"

        intent = await extract_intent(prompt, use_llm=False)

        assert intent.task_type == "api"
        assert "REST" in intent.entities or "API" in intent.entities
        assert "create" in intent.operations or "implement" in intent.operations

    @pytest.mark.asyncio
    async def test_extract_intent_testing(self):
        """Test extracting testing intent"""
        prompt = "Write unit tests for the authentication module"

        intent = await extract_intent(prompt, use_llm=False)

        assert intent.task_type == "testing"
        assert "test" in intent.operations or "implement" in intent.operations

    @pytest.mark.asyncio
    async def test_extract_intent_empty_prompt(self):
        """Test extracting from empty prompt"""
        intent = await extract_intent("", use_llm=False)

        assert intent.task_type is None
        assert len(intent.entities) == 0
        assert len(intent.files) == 0

    @pytest.mark.asyncio
    async def test_extract_intent_confidence(self):
        """Test that keyword-based extraction has lower confidence"""
        intent = await extract_intent("Test prompt", use_llm=False)

        assert intent.confidence == 0.7  # Keyword-based confidence


class TestTaskTypeDetection:
    """Test task type detection"""

    def test_detect_authentication(self):
        """Test detecting authentication task"""
        prompt_lower = "implement jwt authentication"
        task_type = _extract_task_type(prompt_lower)
        assert task_type == "authentication"

    def test_detect_database(self):
        """Test detecting database task"""
        prompt_lower = "optimize the sql query"
        task_type = _extract_task_type(prompt_lower)
        assert task_type == "database"

    def test_detect_api(self):
        """Test detecting API task"""
        prompt_lower = "create a rest api endpoint"
        task_type = _extract_task_type(prompt_lower)
        assert task_type == "api"

    def test_detect_testing(self):
        """Test detecting testing task"""
        prompt_lower = "write unit tests"
        task_type = _extract_task_type(prompt_lower)
        assert task_type == "testing"

    def test_detect_debugging(self):
        """Test detecting debugging task"""
        prompt_lower = "fix the error in the code"
        task_type = _extract_task_type(prompt_lower)
        assert task_type == "debugging"

    def test_detect_refactoring(self):
        """Test detecting refactoring task"""
        prompt_lower = "refactor the code to improve readability"
        task_type = _extract_task_type(prompt_lower)
        assert task_type == "refactoring"

    def test_detect_no_task(self):
        """Test detecting no specific task"""
        prompt_lower = "hello world"
        task_type = _extract_task_type(prompt_lower)
        assert task_type is None


class TestEntityExtraction:
    """Test entity extraction"""

    def test_extract_known_entities(self):
        """Test extracting known technical entities"""
        prompt = "Implement JWT authentication with Redis caching and PostgreSQL storage"

        entities = _extract_entities(prompt)

        assert "JWT" in entities
        assert "Redis" in entities
        assert "PostgreSQL" in entities

    def test_extract_capitalized_terms(self):
        """Test extracting capitalized technical terms"""
        prompt = "Use the FastAPI framework with Pydantic models"

        entities = _extract_entities(prompt)

        assert "FastAPI" in entities or "Pydantic" in entities

    def test_extract_no_entities(self):
        """Test extracting from prompt with no entities"""
        prompt = "this is a simple test"

        entities = _extract_entities(prompt)

        # Should be empty or only common capitalizations
        assert len(entities) <= 2

    def test_remove_duplicates(self):
        """Test that duplicate entities are removed"""
        prompt = "Use JWT for JWT authentication with JWT tokens"

        entities = _extract_entities(prompt)

        # Should only have one JWT
        assert entities.count("JWT") == 1


class TestFileDetection:
    """Test file reference detection"""

    def test_detect_python_file(self):
        """Test detecting Python file"""
        prompt = "Update the auth.py file"

        files = _extract_files(prompt)

        assert "auth.py" in files

    def test_detect_multiple_files(self):
        """Test detecting multiple files"""
        prompt = "Modify auth.py, config.yaml, and database.sql"

        files = _extract_files(prompt)

        assert "auth.py" in files
        assert "config.yaml" in files
        assert "database.sql" in files

    def test_detect_file_in_quotes(self):
        """Test detecting file in quotes"""
        prompt = 'Update the "config/settings.py" file'

        files = _extract_files(prompt)

        assert any("settings.py" in f for f in files)

    def test_detect_file_with_path(self):
        """Test detecting file with path"""
        prompt = "Check src/utils/helpers.js"

        files = _extract_files(prompt)

        assert any("helpers.js" in f for f in files)

    def test_no_files(self):
        """Test prompt with no files"""
        prompt = "This prompt has no file references"

        files = _extract_files(prompt)

        assert len(files) == 0


class TestOperationDetection:
    """Test operation detection"""

    def test_detect_implement(self):
        """Test detecting implement operation"""
        prompt_lower = "implement a new feature"

        operations = _extract_operations(prompt_lower)

        assert "implement" in operations

    def test_detect_fix(self):
        """Test detecting fix operation"""
        prompt_lower = "fix the bug in the code"

        operations = _extract_operations(prompt_lower)

        assert "fix" in operations

    def test_detect_refactor(self):
        """Test detecting refactor operation"""
        prompt_lower = "refactor the module for better performance"

        operations = _extract_operations(prompt_lower)

        assert "refactor" in operations

    def test_detect_multiple_operations(self):
        """Test detecting multiple operations"""
        prompt_lower = "implement the feature and test it thoroughly"

        operations = _extract_operations(prompt_lower)

        assert "implement" in operations
        assert "test" in operations

    def test_no_operations(self):
        """Test prompt with no operations"""
        prompt_lower = "this is just a question"

        operations = _extract_operations(prompt_lower)

        # Might detect "analyze" or similar, or be empty
        assert isinstance(operations, list)


class TestMemoryRanking:
    """Test memory ranking by relevance"""

    @pytest.mark.asyncio
    async def test_rank_memories_by_intent(self):
        """Test ranking memories by intent"""
        # Create intent
        intent = Intent(
            task_type="authentication",
            entities=["JWT"],
            files=["auth.py"],
            operations=["implement"]
        )

        # Create mock memories
        memories = {
            "memory1": {
                "description": "JWT authentication pattern",
                "file": "auth.py",
                "type": "authentication"
            },
            "memory2": {
                "description": "Database connection",
                "file": "database.py",
                "type": "database"
            },
            "memory3": {
                "description": "Redis caching",
                "type": "caching"
            }
        }

        # Rank memories
        ranked = await rank_memories_by_intent(memories, intent, max_tokens=5000)

        # memory1 should be ranked highest (matches task_type, entities, files)
        assert "memory1" in ranked
        # memory2 might not be included if irrelevant
        # Ranking algorithm filters less relevant memories


    @pytest.mark.asyncio
    async def test_rank_respects_token_budget(self):
        """Test that ranking respects token budget"""
        intent = Intent(task_type="test")

        # Create large memories
        memories = {
            f"memory{i}": {"data": "x" * 1000}  # ~1000 tokens each
            for i in range(10)
        }

        # Rank with tight budget
        ranked = await rank_memories_by_intent(memories, intent, max_tokens=3000)

        # Should only include ~3 memories to stay within budget
        assert len(ranked) <= 4  # Allow some buffer for JSON overhead


class TestRelevanceScoring:
    """Test relevance scoring algorithm"""

    def test_score_task_type_match(self):
        """Test scoring with task type match"""
        memory = {"description": "authentication implementation"}
        intent = Intent(task_type="authentication")

        score = _calculate_relevance_score(memory, intent)

        assert score >= 0.3  # Task type match adds 0.3

    def test_score_entity_match(self):
        """Test scoring with entity match"""
        memory = {"description": "JWT token validation"}
        intent = Intent(entities=["JWT"])

        score = _calculate_relevance_score(memory, intent)

        assert score >= 0.2  # Entity match adds 0.2

    def test_score_file_match(self):
        """Test scoring with file match"""
        memory = {"file": "auth.py", "description": "authentication"}
        intent = Intent(files=["auth.py"])

        score = _calculate_relevance_score(memory, intent)

        assert score >= 0.3  # File match adds 0.3

    def test_score_multiple_matches(self):
        """Test scoring with multiple matches"""
        memory = {
            "description": "JWT authentication in auth.py",
            "file": "auth.py",
            "type": "authentication"
        }
        intent = Intent(
            task_type="authentication",
            entities=["JWT"],
            files=["auth.py"]
        )

        score = _calculate_relevance_score(memory, intent)

        # Should have high score (task + entity + file)
        assert score >= 0.8

    def test_score_capped_at_one(self):
        """Test that score is capped at 1.0"""
        memory = {
            "description": "authentication JWT auth.py implement fix",
            "file": "auth.py",
            "type": "authentication",
            "success_rate": 0.95
        }
        intent = Intent(
            task_type="authentication",
            entities=["JWT"],
            files=["auth.py"],
            operations=["implement", "fix"]
        )

        score = _calculate_relevance_score(memory, intent)

        assert score <= 1.0


class TestTokenEstimation:
    """Test token estimation"""

    def test_estimate_tokens_simple(self):
        """Test token estimation for simple string"""
        text = "Hello world"  # 11 characters
        tokens = _estimate_tokens(text)

        # ~4 characters per token
        assert tokens == 2  # 11 // 4 = 2

    def test_estimate_tokens_large(self):
        """Test token estimation for large text"""
        text = "x" * 10000  # 10000 characters
        tokens = _estimate_tokens(text)

        assert tokens == 2500  # 10000 // 4

    def test_estimate_tokens_empty(self):
        """Test token estimation for empty string"""
        tokens = _estimate_tokens("")
        assert tokens == 0


class TestEdgeCases:
    """Test edge cases"""

    @pytest.mark.asyncio
    async def test_intent_with_unicode(self):
        """Test intent extraction with unicode characters"""
        prompt = "Implement authentication for 用户 in файл.py"

        intent = await extract_intent(prompt, use_llm=False)

        # Should not crash and return valid intent
        assert isinstance(intent, Intent)

    @pytest.mark.asyncio
    async def test_intent_very_long_prompt(self):
        """Test intent extraction with very long prompt"""
        prompt = "Implement a feature " + ("that does something " * 100)

        intent = await extract_intent(prompt, use_llm=False)

        # Should not crash
        assert isinstance(intent, Intent)

    @pytest.mark.asyncio
    async def test_intent_special_characters(self):
        """Test intent extraction with special characters"""
        prompt = "Fix bug in auth.py!!! @#$%^&*()"

        intent = await extract_intent(prompt, use_llm=False)

        # Should extract despite special characters
        assert "auth.py" in intent.files
        assert "fix" in intent.operations


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
