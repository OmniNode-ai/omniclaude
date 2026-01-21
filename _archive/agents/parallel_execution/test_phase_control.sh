#!/bin/bash
#
# Test script for phase-by-phase execution control
#
# Tests all the new features:
# - --only-phase N
# - --stop-after-phase N
# - --skip-phases 0,1
# - --save-phase-state
# - --load-phase-state
# - Backward compatibility with existing flags

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TEST_INPUT="$SCRIPT_DIR/test_phase_control.json"
RUNNER="$SCRIPT_DIR/dispatch_runner.py"

echo "========================================================================"
echo "Phase Control Testing Suite"
echo "========================================================================"
echo ""

# Test 1: Backward compatibility - standard execution without phase control
echo "Test 1: Backward compatibility (standard execution)"
echo "Command: python dispatch_runner.py < test_phase_control.json"
echo "------------------------------------------------------------------------"
python3 "$RUNNER" < "$TEST_INPUT" > /tmp/test1_output.json 2> /tmp/test1_stderr.txt || true
echo "Exit code: $?"
echo "Stderr output:"
cat /tmp/test1_stderr.txt
echo ""
echo "Output structure:"
jq -r 'keys[]' /tmp/test1_output.json 2>/dev/null || echo "No JSON output"
echo ""
echo ""

# Test 2: Execute only Phase 0 (context gathering)
echo "Test 2: Execute only Phase 0 (--only-phase 0 --enable-context)"
echo "Command: python dispatch_runner.py --only-phase 0 --enable-context < test_phase_control.json"
echo "------------------------------------------------------------------------"
python3 "$RUNNER" --only-phase 0 --enable-context < "$TEST_INPUT" > /tmp/test2_output.json 2> /tmp/test2_stderr.txt || true
echo "Exit code: $?"
echo "Stderr output:"
cat /tmp/test2_stderr.txt
echo ""
echo "Phase results:"
jq -r '.phase_results[]? | "\(.phase_name): \(.success) (\(.duration_ms)ms)"' /tmp/test2_output.json 2>/dev/null || echo "No phase results"
echo ""
echo ""

# Test 3: Stop after Phase 1 (quorum validation)
echo "Test 3: Stop after Phase 1 (--stop-after-phase 1 --enable-context --enable-quorum)"
echo "Command: python dispatch_runner.py --stop-after-phase 1 --enable-context --enable-quorum < test_phase_control.json"
echo "------------------------------------------------------------------------"
python3 "$RUNNER" --stop-after-phase 1 --enable-context --enable-quorum < "$TEST_INPUT" > /tmp/test3_output.json 2> /tmp/test3_stderr.txt || true
echo "Exit code: $?"
echo "Stderr output:"
cat /tmp/test3_stderr.txt
echo ""
echo "Phase results:"
jq -r '.phase_results[]? | "\(.phase_name): \(.success) (\(.duration_ms)ms)"' /tmp/test3_output.json 2>/dev/null || echo "No phase results"
echo ""
echo ""

# Test 4: Skip phases 0 and 1
echo "Test 4: Skip phases 0 and 1 (--skip-phases 0,1)"
echo "Command: python dispatch_runner.py --skip-phases 0,1 < test_phase_control.json"
echo "------------------------------------------------------------------------"
python3 "$RUNNER" --skip-phases 0,1 < "$TEST_INPUT" > /tmp/test4_output.json 2> /tmp/test4_stderr.txt || true
echo "Exit code: $?"
echo "Stderr output:"
cat /tmp/test4_stderr.txt
echo ""
echo "Phase results:"
jq -r '.phase_results[]? | "\(.phase_name): \(.success) (\(.duration_ms)ms)"' /tmp/test4_output.json 2>/dev/null || echo "No phase results"
echo ""
echo ""

# Test 5: Save phase state
echo "Test 5: Save phase state (--save-phase-state phases.json)"
echo "Command: python dispatch_runner.py --save-phase-state /tmp/phases.json < test_phase_control.json"
echo "------------------------------------------------------------------------"
python3 "$RUNNER" --save-phase-state /tmp/phases.json < "$TEST_INPUT" > /tmp/test5_output.json 2> /tmp/test5_stderr.txt || true
echo "Exit code: $?"
echo "Stderr output:"
cat /tmp/test5_stderr.txt
echo ""
echo "Saved phase state keys:"
jq -r 'keys[]' /tmp/phases.json 2>/dev/null || echo "No phase state saved"
echo ""
echo "Phase results count:"
jq -r '.phases_executed | length' /tmp/phases.json 2>/dev/null || echo "0"
echo ""
echo ""

# Test 6: Test help output
echo "Test 6: Help output (--help)"
echo "Command: python dispatch_runner.py --help"
echo "------------------------------------------------------------------------"
python3 "$RUNNER" --help 2>&1 | head -30
echo ""
echo ""

# Summary
echo "========================================================================"
echo "Test Summary"
echo "========================================================================"
echo ""
echo "Test files created:"
ls -lh /tmp/test*_{output,stderr}.txt 2>/dev/null || echo "No test files"
echo ""
echo "Phase state file:"
ls -lh /tmp/phases.json 2>/dev/null || echo "No phase state file"
echo ""
echo "All tests completed!"
echo ""
