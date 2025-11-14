"""
End-to-End Integration Test for STF Helper

Demonstrates complete agent-debug loop workflow:
1. Agent encounters error
2. Queries STFs for similar problems
3. Applies top-ranked STF
4. Validates solution
5. Updates usage metrics
6. Stores new STF for future use

This test simulates realistic agent behavior when interacting with the debug loop.
"""

import asyncio

import pytest

from agents.lib.stf_helper import STFHelper
from omniclaude.debug_loop.mock_database_protocol import MockDatabaseProtocol


@pytest.fixture
def mock_db():
    """Create fresh mock database for each test."""
    return MockDatabaseProtocol()


@pytest.fixture
def stf_helper(mock_db):
    """Create STFHelper with mock database."""
    return STFHelper(db_protocol=mock_db)


@pytest.mark.asyncio
async def test_complete_debugging_workflow(stf_helper):
    """
    Test complete debugging workflow: error → query → apply → track → store.

    Scenario: Agent encounters "No module named 'requests'" error
    1. Query for existing STFs
    2. Apply top-ranked solution
    3. Track usage metrics
    4. Store improved solution
    """

    # ============================================================================
    # PHASE 1: Setup - Pre-populate database with existing STFs
    # ============================================================================
    print("\n=== Phase 1: Setup - Pre-populate STF database ===")

    # Store several existing STFs for import errors
    existing_stfs = [
        {
            "name": "fix_import_basic",
            "code": "import sys\nsys.path.append('.')",
            "description": "Add current directory to Python path",
            "quality": 0.75,
        },
        {
            "name": "fix_import_advanced",
            "code": "import sys\nimport os\nsys.path.insert(0, os.getcwd())",
            "description": "Insert current working directory at front of path",
            "quality": 0.85,
        },
        {
            "name": "fix_import_pip_install",
            "code": "import subprocess\nsubprocess.check_call(['pip', 'install', 'requests'])",
            "description": "Install missing package using pip",
            "quality": 0.90,
        },
    ]

    stored_ids = []
    for stf in existing_stfs:
        stf_id = await stf_helper.store_stf(
            stf_name=stf["name"],
            stf_code=stf["code"],
            stf_description=stf["description"],
            problem_category="import_error",
            problem_signature="No module named",
            quality_score=stf["quality"],
            correlation_id=f"setup-{stf['name']}",
        )
        stored_ids.append(stf_id)
        print(f"  Stored STF: {stf['name']} (quality: {stf['quality']})")

    # Approve all STFs (simulate approval workflow)
    for stf in stf_helper.db.stfs.values():
        stf["approval_status"] = "approved"

    print(f"  Total STFs in database: {len(stf_helper.db.stfs)}")

    # ============================================================================
    # PHASE 2: Agent Encounters Error
    # ============================================================================
    print("\n=== Phase 2: Agent Encounters Error ===")

    error_message = "ModuleNotFoundError: No module named 'requests'"
    problem_signature = "No module named"
    problem_category = "import_error"

    print(f"  Error detected: {error_message}")
    print(f"  Problem signature: '{problem_signature}'")
    print(f"  Problem category: '{problem_category}'")

    # ============================================================================
    # PHASE 3: Query STFs for Similar Problems
    # ============================================================================
    print("\n=== Phase 3: Query STFs for Similar Problems ===")

    matching_stfs = await stf_helper.query_stfs(
        problem_signature=problem_signature,
        problem_category=problem_category,
        min_quality=0.7,
        limit=3,
    )

    print(f"  Found {len(matching_stfs)} matching STFs:")
    for i, stf in enumerate(matching_stfs, 1):
        print(
            f"    {i}. {stf['stf_name']} (quality: {stf['quality_score']}, "
            f"usage: {stf['usage_count']})"
        )

    assert len(matching_stfs) == 3
    assert matching_stfs[0]["quality_score"] >= matching_stfs[1]["quality_score"]

    # ============================================================================
    # PHASE 4: Apply Top-Ranked STF
    # ============================================================================
    print("\n=== Phase 4: Apply Top-Ranked STF ===")

    top_stf = matching_stfs[0]
    print(f"  Applying STF: {top_stf['stf_name']}")

    # Retrieve full STF details including code
    full_stf = await stf_helper.retrieve_stf(top_stf["stf_id"])
    assert full_stf is not None

    print(f"  Retrieved full STF details:")
    print(f"    Name: {full_stf['stf_name']}")
    print(f"    Description: {full_stf['stf_description']}")
    print(f"    Code:\n{full_stf['stf_code']}")

    # Simulate applying the transformation
    print(f"  Executing transformation code...")
    solution_applied = True  # Simulate successful application

    # ============================================================================
    # PHASE 5: Validate Solution
    # ============================================================================
    print("\n=== Phase 5: Validate Solution ===")

    # Simulate validation (in reality, agent would test the fix)
    validation_successful = True
    print(f"  Solution validation: {'PASSED' if validation_successful else 'FAILED'}")

    # ============================================================================
    # PHASE 6: Track Usage Metrics
    # ============================================================================
    print("\n=== Phase 6: Track Usage Metrics ===")

    if solution_applied:
        usage_updated = await stf_helper.update_stf_usage(
            stf_id=top_stf["stf_id"], success=validation_successful
        )
        assert usage_updated is True
        print(f"  Usage metrics updated for STF: {top_stf['stf_id']}")

        # Verify usage count incremented
        updated_stf = await stf_helper.retrieve_stf(top_stf["stf_id"])
        assert updated_stf["usage_count"] == 1
        print(f"  New usage count: {updated_stf['usage_count']}")

    # ============================================================================
    # PHASE 7: Store Improved Solution (Optional)
    # ============================================================================
    print("\n=== Phase 7: Store Improved Solution ===")

    # Simulate agent improving the solution with context-specific enhancements
    improved_code = """
import subprocess
import sys

# Install missing package using pip
subprocess.check_call([sys.executable, '-m', 'pip', 'install', 'requests'])

# Verify installation
try:
    import requests
    print("requests successfully installed")
except ImportError as e:
    print(f"Installation failed: {e}")
"""

    improved_stf_id = await stf_helper.store_stf(
        stf_name="fix_import_requests_with_verification",
        stf_code=improved_code,
        stf_description="Install missing 'requests' package with installation verification",
        problem_category=problem_category,
        problem_signature=problem_signature,
        quality_score=0.92,  # Higher quality due to verification
        correlation_id="agent-improvement-123",
        contributor_agent_name="debug-intelligence",
    )

    assert improved_stf_id is not None
    print(f"  Stored improved STF: {improved_stf_id}")
    print(f"  Quality score: 0.92 (improved from 0.90)")

    # ============================================================================
    # PHASE 8: Verify Final State
    # ============================================================================
    print("\n=== Phase 8: Verify Final State ===")

    # Query again to see updated rankings
    final_stfs = await stf_helper.query_stfs(
        problem_signature=problem_signature,
        problem_category=problem_category,
        min_quality=0.7,
    )

    print(f"  Total STFs after improvement: {len(final_stfs)}")
    print(f"  Top-ranked STFs:")
    for i, stf in enumerate(final_stfs[:3], 1):
        print(
            f"    {i}. {stf['stf_name']} (quality: {stf['quality_score']}, "
            f"usage: {stf['usage_count']})"
        )

    # Improved STF should be top-ranked (highest quality)
    assert final_stfs[0]["quality_score"] == 0.92
    assert final_stfs[0]["stf_name"] == "fix_import_requests_with_verification"

    print("\n=== End-to-End Test Complete ===")
    print(f"✓ Workflow successfully completed")
    print(f"✓ Database now contains {len(stf_helper.db.stfs)} STFs")
    print(f"✓ Usage metrics tracked for applied solutions")
    print(f"✓ Improved solution stored for future use")


@pytest.mark.asyncio
async def test_parallel_agent_stf_usage(stf_helper):
    """
    Test multiple agents using STF system concurrently.

    Scenario: Multiple agents encounter similar errors simultaneously
    and all query/apply/track STFs in parallel.
    """

    print("\n=== Test: Parallel Agent STF Usage ===")

    # Pre-populate with a single high-quality STF
    stf_id = await stf_helper.store_stf(
        stf_name="fix_connection_timeout",
        stf_code="pool_size = 20\nmax_connections = 100\ntimeout = 30",
        stf_description="Increase connection pool size and timeout",
        problem_category="connection_pooling",
        problem_signature="connection timeout",
        quality_score=0.88,
        correlation_id="parallel-setup",
    )

    # Approve STF
    stf_helper.db.stfs[stf_id]["approval_status"] = "approved"

    # Simulate 5 agents using the same STF concurrently
    async def agent_workflow(agent_id: int):
        """Single agent workflow."""
        print(f"  Agent {agent_id}: Querying STFs...")

        # Query STFs
        stfs = await stf_helper.query_stfs(
            problem_signature="connection timeout",
            problem_category="connection_pooling",
            min_quality=0.8,
        )

        assert len(stfs) >= 1

        # Apply top STF
        top_stf = stfs[0]
        print(f"  Agent {agent_id}: Applying STF {top_stf['stf_id'][:8]}...")

        # Simulate successful application
        await asyncio.sleep(0.01)  # Simulate work

        # Track usage
        success = await stf_helper.update_stf_usage(top_stf["stf_id"], success=True)
        assert success

        print(f"  Agent {agent_id}: Completed workflow")
        return agent_id

    # Run 5 agent workflows concurrently
    print("\n  Launching 5 concurrent agent workflows...")
    agent_tasks = [agent_workflow(i) for i in range(1, 6)]
    results = await asyncio.gather(*agent_tasks)

    assert len(results) == 5
    assert all(r is not None for r in results)

    # Verify usage count increased by 5
    final_stf = await stf_helper.retrieve_stf(stf_id)
    assert final_stf["usage_count"] == 5

    print(f"\n  ✓ All 5 agents completed successfully")
    print(f"  ✓ STF usage count: {final_stf['usage_count']}")


@pytest.mark.asyncio
async def test_stf_learning_loop(stf_helper):
    """
    Test STF quality improvement through learning loop.

    Scenario: Agent uses STF, improves it, stores improved version,
    and the improved version becomes the top-ranked solution.
    """

    print("\n=== Test: STF Learning Loop ===")

    # ============================================================================
    # Iteration 1: Initial solution
    # ============================================================================
    print("\n  Iteration 1: Initial Solution")

    stf_v1_id = await stf_helper.store_stf(
        stf_name="fix_build_failure_v1",
        stf_code="pip install -r requirements.txt",
        stf_description="Install all dependencies from requirements.txt",
        problem_category="build_failure",
        problem_signature="build failed",
        quality_score=0.70,
        correlation_id="learning-v1",
    )

    stf_helper.db.stfs[stf_v1_id]["approval_status"] = "approved"
    print(f"    Stored v1 (quality: 0.70)")

    # ============================================================================
    # Iteration 2: Improved solution with error handling
    # ============================================================================
    print("\n  Iteration 2: Add Error Handling")

    stf_v2_id = await stf_helper.store_stf(
        stf_name="fix_build_failure_v2",
        stf_code="pip install --upgrade pip\npip install -r requirements.txt",
        stf_description="Upgrade pip first, then install dependencies",
        problem_category="build_failure",
        problem_signature="build failed",
        quality_score=0.80,
        correlation_id="learning-v2",
    )

    stf_helper.db.stfs[stf_v2_id]["approval_status"] = "approved"
    print(f"    Stored v2 (quality: 0.80)")

    # ============================================================================
    # Iteration 3: Production-ready solution with validation
    # ============================================================================
    print("\n  Iteration 3: Add Validation")

    stf_v3_id = await stf_helper.store_stf(
        stf_name="fix_build_failure_v3",
        stf_code="""
pip install --upgrade pip
pip install -r requirements.txt

# Verify installation
python -c "import sys; print(f'Python {sys.version}')"
pip list
""",
        stf_description="Upgrade pip, install dependencies, and verify installation",
        problem_category="build_failure",
        problem_signature="build failed",
        quality_score=0.92,
        correlation_id="learning-v3",
    )

    stf_helper.db.stfs[stf_v3_id]["approval_status"] = "approved"
    print(f"    Stored v3 (quality: 0.92)")

    # ============================================================================
    # Verify learning progression
    # ============================================================================
    print("\n  Verifying Learning Progression:")

    top_stfs = await stf_helper.get_top_stfs(
        problem_category="build_failure", limit=3, min_quality=0.6
    )

    print(f"    Top-ranked solutions:")
    for i, stf in enumerate(top_stfs, 1):
        print(f"      {i}. {stf['stf_name']} (quality: {stf['quality_score']})")

    # v3 should be top-ranked
    assert top_stfs[0]["stf_name"] == "fix_build_failure_v3"
    assert top_stfs[0]["quality_score"] == 0.92

    # Quality should be monotonically increasing
    qualities = [stf["quality_score"] for stf in top_stfs]
    assert qualities == sorted(qualities, reverse=True)

    print(f"\n  ✓ Learning loop validated")
    print(f"  ✓ Quality progression: 0.70 → 0.80 → 0.92")
    print(f"  ✓ Best solution promoted to top rank")


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])  # -s to show print statements
