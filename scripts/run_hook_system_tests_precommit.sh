#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
#
# run_hook_system_tests_precommit.sh (OMN-20109)
#
# Pre-commit entry for the real-hook system suite (OMN-20109).
#
# A commit that touches the hook tree runs the DETERMINISTIC half of the suite:
# the canary contract, the hook registration and cost-ratchet checks. The
# real-process half (40 hooks in parallel, broken emit paths, the per-call
# wall-time budget) spawns thousands of processes and its wall-time assertions
# depend on host load, so a hand-run on a loaded workstation would fail for the
# load and teach people to bypass the hook (rule 21: directory-wide runs go
# off-box). That half is the required CI job "Hook System Tests (OMN-20109)".
# In CI this pre-commit hook stands down and says so, rather than running twice.
set -euo pipefail

if [[ "${GITHUB_ACTIONS:-}" == "true" ]]; then
  echo "hook-system-tests: in CI the full suite runs as the required job 'Hook System Tests (OMN-20109)'; not run twice."
  exit 0
fi

# pytest imports the root conftest, and a bytecode cache written into the project
# root fails the pre-push clean-root validator on the next push.
export PYTHONDONTWRITEBYTECODE=1

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
exec bash "${here}/uv-run-worktree-safe.sh" python -m pytest -q -x -p no:cacheprovider \
  tests/hooks_system/test_hook_canary.py \
  tests/ci/test_hook_system_tests_gate_omn20109.py \
  "tests/hooks_system/test_hook_call_budget.py::test_budget_record_only_ratchets_down" \
  "tests/hooks_system/test_hook_call_budget.py::test_every_registered_hook_exists_and_is_executable"
