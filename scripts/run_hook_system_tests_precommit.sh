#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
#
# run_hook_system_tests_precommit.sh (OMN-20109)
#
# Pre-commit entry for the real-hook system suite. Local commits touching the hook
# tree run tests/hooks_system. In CI the same suite is its own required job
# ("Hook System Tests (OMN-20109)"), so the pre-commit suite job stands down here
# and says so, rather than running 60 seconds of process-counting twice.
set -euo pipefail

if [[ "${GITHUB_ACTIONS:-}" == "true" ]]; then
  echo "hook-system-tests: in CI this suite runs as the required job 'Hook System Tests (OMN-20109)'; not run twice."
  exit 0
fi

for tool in ps jq; do
  command -v "${tool}" >/dev/null 2>&1 || { echo "hook-system-tests: '${tool}' is required and is not installed" >&2; exit 1; }
done

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
exec bash "${here}/uv-run-worktree-safe.sh" python -m pytest tests/hooks_system -q -x -p no:cacheprovider
