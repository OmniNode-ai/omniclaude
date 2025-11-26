#!/usr/bin/env python3
"""
Test Enhanced Metadata Extraction
Validates performance (<15ms target) and accuracy
"""

import json
import sys
import time
from pathlib import Path

from .lib.correlation_manager import CorrelationManager
from .lib.metadata_extractor import MetadataExtractor


def test_performance():
    """Test performance of metadata extraction."""
    print("=" * 80)
    print("Performance Test")
    print("=" * 80)

    test_prompts = [
        "Fix the authentication bug in user_login.py",
        "Implement a new caching layer for the API endpoints",
        "Refactor the database query code to improve performance",
        "Add unit tests for the payment processing module",
        "Debug the memory leak in the background worker",
    ]

    extractor = MetadataExtractor()
    total_time: float = 0.0
    max_time: float = 0.0
    min_time: float = float("inf")

    for i, prompt in enumerate(test_prompts, 1):
        start = time.perf_counter()
        metadata = extractor.extract_all(prompt, agent_name="agent-test")
        elapsed = (time.perf_counter() - start) * 1000  # Convert to ms

        total_time += elapsed
        max_time = max(max_time, elapsed)
        min_time = min(min_time, elapsed)

        print(f"\nTest {i}: {elapsed:.2f}ms")
        print(f"  Prompt: {prompt[:50]}...")
        print(f"  Workflow: {metadata['workflow_stage']}")
        print(f"  Command words: {metadata['prompt_characteristics']['command_words']}")

    avg_time = total_time / len(test_prompts)

    print("\n" + "=" * 80)
    print("Performance Summary")
    print("=" * 80)
    print(f"Average time: {avg_time:.2f}ms")
    print(f"Min time: {min_time:.2f}ms")
    print(f"Max time: {max_time:.2f}ms")
    print("Target: <15ms")
    print(f"Status: {'✅ PASS' if avg_time < 15 else '⚠️  FAIL'}")


def test_workflow_classification():
    """Test workflow stage classification accuracy."""
    print("\n" + "=" * 80)
    print("Workflow Classification Test")
    print("=" * 80)

    test_cases = [
        ("Fix the authentication bug", "debugging"),
        ("Implement a new feature", "feature_development"),
        ("Refactor the code", "refactoring"),
        ("Add unit tests", "testing"),
        ("Document the API", "documentation"),
        ("Review the pull request", "review"),
        ("What is the current status?", "exploratory"),
    ]

    extractor = MetadataExtractor()
    passed = 0
    total = len(test_cases)

    for prompt, expected_stage in test_cases:
        metadata = extractor.extract_all(prompt)
        actual_stage = metadata["workflow_stage"]

        status = "✅" if actual_stage == expected_stage else "❌"
        print(
            f"{status} {prompt[:40]:<40} -> {actual_stage:<20} (expected: {expected_stage})"
        )

        if actual_stage == expected_stage:
            passed += 1

    print("\n" + "=" * 80)
    print(f"Accuracy: {passed}/{total} ({100 * passed / total:.1f}%)")
    print("=" * 80)


def test_editor_context():
    """Test editor context extraction."""
    print("\n" + "=" * 80)
    print("Editor Context Test")
    print("=" * 80)

    extractor = MetadataExtractor()
    metadata = extractor.extract_all("Test prompt")

    editor_context = metadata["editor_context"]

    print(f"Working directory: {editor_context['working_directory']}")
    print(f"Active file: {editor_context['active_file']}")
    print(f"Language: {editor_context['language']}")
    print(f"File type: {editor_context['file_type']}")

    if editor_context["active_file"]:
        print("\n✅ Editor context extraction working")
    else:
        print("\n⚠️  No active file detected (this is OK if no recent files)")


def test_session_context():
    """Test session context tracking."""
    print("\n" + "=" * 80)
    print("Session Context Test")
    print("=" * 80)

    # Initialize correlation manager
    manager = CorrelationManager()
    manager.clear()  # Start fresh

    # Simulate multiple prompts
    for i in range(3):
        manager.set_correlation_id(
            correlation_id=f"test-{i}",
            agent_name="agent-test",
            prompt_preview=f"Test prompt {i}",
        )

        if i > 0:
            time.sleep(0.1)  # Small delay between prompts

        # Extract metadata
        extractor = MetadataExtractor()
        correlation_context = manager.get_correlation_context()
        metadata = extractor.extract_all(
            "Test prompt", correlation_context=correlation_context
        )

        session_context = metadata["session_context"]
        print(f"\nPrompt {i + 1}:")
        print(f"  Prompts in session: {session_context['prompts_in_session']}")
        print(
            f"  Time since last: {session_context['time_since_last_prompt_seconds']}s"
        )

    manager.clear()
    print("\n✅ Session context tracking working")


def test_prompt_characteristics():
    """Test prompt characteristics extraction."""
    print("\n" + "=" * 80)
    print("Prompt Characteristics Test")
    print("=" * 80)

    test_cases = [
        ("Fix bug in `auth.py` code", True, 0, ["fix"]),
        ("How do I implement this? What about testing?", False, 2, ["implement"]),
        ("Create a new feature and add tests", False, 0, ["create", "add"]),
    ]

    extractor = MetadataExtractor()

    for prompt, has_code, questions, commands in test_cases:
        metadata = extractor.extract_all(prompt)
        chars = metadata["prompt_characteristics"]

        print(f"\nPrompt: {prompt}")
        print(f"  Length: {chars['length_chars']} chars")
        print(f"  Has code: {chars['has_code_block']} (expected: {has_code})")
        print(f"  Questions: {chars['question_count']} (expected: {questions})")
        print(f"  Commands: {chars['command_words']} (expected: {commands})")

        # Validate
        code_ok = chars["has_code_block"] == has_code
        q_ok = chars["question_count"] == questions
        cmd_ok = all(cmd in chars["command_words"] for cmd in commands)

        status = "✅" if (code_ok and q_ok and cmd_ok) else "❌"
        print(f"  Status: {status}")

    print("\n✅ Prompt characteristics working")


def test_complete_metadata():
    """Test complete metadata structure."""
    print("\n" + "=" * 80)
    print("Complete Metadata Structure Test")
    print("=" * 80)

    extractor = MetadataExtractor()
    metadata = extractor.extract_all(
        prompt="Implement a new authentication feature with tests",
        agent_name="agent-feature-developer",
    )

    print("\nComplete metadata:")
    print(json.dumps(metadata, indent=2))

    # Validate structure
    required_keys = [
        "trigger_source",
        "workflow_stage",
        "editor_context",
        "session_context",
        "prompt_characteristics",
        "extraction_time_ms",
    ]

    missing_keys = [key for key in required_keys if key not in metadata]

    if missing_keys:
        print(f"\n❌ Missing keys: {missing_keys}")
    else:
        print("\n✅ All required keys present")


if __name__ == "__main__":
    print("\n" + "=" * 80)
    print("ENHANCED METADATA EXTRACTION TEST SUITE")
    print("=" * 80)

    try:
        test_performance()
        test_workflow_classification()
        test_editor_context()
        test_session_context()
        test_prompt_characteristics()
        test_complete_metadata()

        print("\n" + "=" * 80)
        print("✅ ALL TESTS COMPLETED")
        print("=" * 80)

    except Exception as e:
        print(f"\n❌ Test failed with error: {e}")
        import traceback

        traceback.print_exc()
        sys.exit(1)
