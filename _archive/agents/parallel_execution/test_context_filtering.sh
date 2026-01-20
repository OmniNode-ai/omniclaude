#!/bin/bash
# Test script for context filtering system

set -e

echo "========================================"
echo "Context Filtering System Test"
echo "========================================"
echo ""

# Navigate to correct directory
cd "$(dirname "$0")"
echo "Working directory: $(pwd)"
echo ""

# Test 1: Without context filtering (legacy mode)
echo "Test 1: Running WITHOUT context filtering (legacy mode)..."
echo "Command: python dispatch_runner.py < example_context_filtering.json"
echo ""
echo "Expected: No context filtering logs, agents gather independently"
echo "Press Enter to continue..."
read

python dispatch_runner.py < example_context_filtering.json > /tmp/test_no_context.json 2>&1

echo ""
echo "✅ Test 1 complete. Output saved to /tmp/test_no_context.json"
echo ""

# Test 2: With context filtering (enhanced mode)
echo "========================================"
echo "Test 2: Running WITH context filtering (enhanced mode)..."
echo "Command: python dispatch_runner.py --enable-context < example_context_filtering.json"
echo ""
echo "Expected context filtering logs:"
echo "  - [DispatchRunner] Context filtering enabled"
echo "  - [DispatchRunner] Phase 0: Gathering global context..."
echo "  - [ContextManager] Gathered X context items in Yms"
echo "  - [DispatchRunner] Filtering context for task..."
echo "  - [ContextManager] Filtered to X items (Y tokens) in Zms"
echo ""
echo "Press Enter to continue..."
read

python dispatch_runner.py --enable-context < example_context_filtering.json > /tmp/test_with_context.json 2>&1

echo ""
echo "✅ Test 2 complete. Output saved to /tmp/test_with_context.json"
echo ""

# Compare results
echo "========================================"
echo "Test Summary"
echo "========================================"
echo ""

# Extract stderr logs
echo "Logs WITHOUT context filtering:"
grep -E "\[DispatchRunner\]|\[ContextManager\]" /tmp/test_no_context.json || echo "  (No context filtering logs - expected)"
echo ""

echo "Logs WITH context filtering:"
grep -E "\[DispatchRunner\]|\[ContextManager\]" /tmp/test_with_context.json || echo "  (Check file for logs)"
echo ""

# Performance comparison
echo "Performance Comparison:"
echo "  - Test 1 (no context): Check /tmp/test_no_context.json"
echo "  - Test 2 (with context): Check /tmp/test_with_context.json"
echo ""

# Success rates
echo "Success rates:"
TEST1_SUCCESS=$(jq -r '.results[] | select(.success==true) | .task_id' /tmp/test_no_context.json 2>/dev/null | wc -l || echo "0")
TEST2_SUCCESS=$(jq -r '.results[] | select(.success==true) | .task_id' /tmp/test_with_context.json 2>/dev/null | wc -l || echo "0")

echo "  - Test 1: $TEST1_SUCCESS successful tasks"
echo "  - Test 2: $TEST2_SUCCESS successful tasks"
echo ""

echo "========================================"
echo "✅ All tests complete!"
echo "========================================"
echo ""
echo "Review the output files:"
echo "  - /tmp/test_no_context.json"
echo "  - /tmp/test_with_context.json"
echo ""
echo "Key metrics to compare:"
echo "  1. Total execution time"
echo "  2. Context gathering time (Phase 0)"
echo "  3. Token usage reduction"
echo "  4. Number of RAG queries (should be fewer in Test 2)"
echo ""
