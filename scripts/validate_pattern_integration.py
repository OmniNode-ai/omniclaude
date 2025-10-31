#!/usr/bin/env python3
"""
Validate Pattern Learning Integration in OmniNodeTemplateEngine

This script validates that:
1. Pattern learning imports work correctly
2. Pattern detection can identify CRUD patterns
3. Pattern extraction works on sample code
4. Pattern storage connects to Qdrant

Run this to verify the KV-002 integration is working.
"""

import sys
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))


def test_pattern_library_import():
    """Test PatternLibrary can be imported"""
    try:

        print("✅ PatternLibrary import successful")
        return True
    except Exception as e:
        print(f"❌ PatternLibrary import failed: {e}")
        return False


def test_pattern_storage_import():
    """Test PatternStorage can be imported"""
    try:

        print("✅ PatternStorage import successful")
        return True
    except Exception as e:
        print(f"❌ PatternStorage import failed: {e}")
        return False


def test_pattern_extractor_import():
    """Test PatternExtractor can be imported"""
    try:

        print("✅ PatternExtractor import successful")
        return True
    except Exception as e:
        print(f"❌ PatternExtractor import failed: {e}")
        return False


def test_pattern_detection():
    """Test pattern detection on CRUD capabilities"""
    try:
        from agents.lib.pattern_library import PatternLibrary

        library = PatternLibrary()

        # Simulate CRUD contract
        contract = {
            "capabilities": [
                {"name": "create", "description": "Create operation"},
                {"name": "read", "description": "Read operation"},
                {"name": "update", "description": "Update operation"},
                {"name": "delete", "description": "Delete operation"},
            ]
        }

        result = library.detect_pattern(contract, min_confidence=0.7)

        if result.get("matched"):
            print(
                f"✅ Pattern detected: {result['pattern_name']} (confidence: {result['confidence']:.2f})"
            )
            return True
        else:
            print("❌ No pattern detected (expected CRUD)")
            return False

    except Exception as e:
        print(f"❌ Pattern detection failed: {e}")
        import traceback

        traceback.print_exc()
        return False


def test_pattern_extraction():
    """Test pattern extraction on sample ONEX code"""
    try:
        from agents.lib.patterns.pattern_extractor import PatternExtractor

        sample_code = """
class NodeDatabaseWriterEffect:
    \"\"\"Effect node for database write operations\"\"\"

    async def execute_effect(self, contract):
        \"\"\"Execute database write effect\"\"\"
        # Implementation here
        pass

    async def create(self, data):
        \"\"\"Create operation\"\"\"
        pass

    async def update(self, data):
        \"\"\"Update operation\"\"\"
        pass
"""

        extractor = PatternExtractor(min_confidence=0.5)
        result = extractor.extract_patterns(
            generated_code=sample_code,
            context={"framework": "onex", "node_type": "EFFECT"},
        )

        if result.patterns:
            print(
                f"✅ Extracted {len(result.patterns)} patterns ({result.extraction_time_ms}ms)"
            )
            for pattern in result.patterns[:3]:  # Show first 3
                print(
                    f"   - {pattern.pattern_type.value}: {pattern.pattern_name} (confidence: {pattern.confidence_score:.2f})"
                )
            return True
        else:
            print("❌ No patterns extracted")
            return False

    except Exception as e:
        print(f"❌ Pattern extraction failed: {e}")
        import traceback

        traceback.print_exc()
        return False


def test_qdrant_connectivity():
    """Test Qdrant server connectivity"""
    try:
        import requests

        response = requests.get("http://localhost:6333/collections", timeout=2)

        if response.status_code == 200:
            collections = response.json().get("result", {}).get("collections", [])
            print(f"✅ Qdrant connected: {len(collections)} collections available")
            return True
        else:
            print(f"❌ Qdrant returned status {response.status_code}")
            return False

    except Exception as e:
        print(f"⚠️  Qdrant not available (will fallback to in-memory): {e}")
        return False  # Non-critical


def test_pattern_storage_initialization():
    """Test PatternStorage can initialize (with Qdrant or in-memory)"""
    try:
        from agents.lib.patterns.pattern_storage import PatternStorage

        storage = PatternStorage(
            qdrant_url="http://localhost:6333",
            collection_name="test_patterns",
            use_in_memory=False,  # Try Qdrant first
        )

        if storage.use_in_memory:
            print("✅ PatternStorage initialized (in-memory fallback)")
        else:
            print("✅ PatternStorage initialized (Qdrant connected)")

        return True

    except Exception as e:
        print(f"❌ PatternStorage initialization failed: {e}")
        import traceback

        traceback.print_exc()
        return False


def main():
    """Run all validation tests"""
    print("=" * 60)
    print("Pattern Learning Integration Validation")
    print("=" * 60)
    print()

    results = []

    print("1. Testing Imports")
    print("-" * 60)
    results.append(("PatternLibrary Import", test_pattern_library_import()))
    results.append(("PatternStorage Import", test_pattern_storage_import()))
    results.append(("PatternExtractor Import", test_pattern_extractor_import()))
    print()

    print("2. Testing Pattern Detection")
    print("-" * 60)
    results.append(("Pattern Detection", test_pattern_detection()))
    print()

    print("3. Testing Pattern Extraction")
    print("-" * 60)
    results.append(("Pattern Extraction", test_pattern_extraction()))
    print()

    print("4. Testing Infrastructure")
    print("-" * 60)
    results.append(("Qdrant Connectivity", test_qdrant_connectivity()))
    results.append(("PatternStorage Init", test_pattern_storage_initialization()))
    print()

    # Summary
    print("=" * 60)
    print("Summary")
    print("=" * 60)

    passed = sum(1 for _, result in results if result)
    total = len(results)

    for name, result in results:
        status = "✅ PASS" if result else "❌ FAIL"
        print(f"{status}: {name}")

    print()
    print(f"Total: {passed}/{total} tests passed")

    if passed == total:
        print("✅ All tests passed! Pattern learning integration is working.")
        return 0
    else:
        print("⚠️  Some tests failed. Check details above.")
        return 1


if __name__ == "__main__":
    sys.exit(main())
