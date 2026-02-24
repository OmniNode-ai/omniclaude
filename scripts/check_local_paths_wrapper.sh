#!/usr/bin/env bash
# Wrapper for the check-local-paths pre-commit hook.
# Gracefully skips if omnibase_core.validation.validator_local_paths is not yet published.
# TODO: Remove this wrapper once validator_local_paths is in a released omnibase_core package
#       (the module exists in omnibase_core source via PR #530 but is not yet on PyPI).
set -euo pipefail

if uv run python -c "import omnibase_core.validation.validator_local_paths" 2>/dev/null; then
    exec uv run python -m omnibase_core.validation.validator_local_paths "$@"
else
    echo "⚠  check-local-paths: validator_local_paths not in installed omnibase_core — skipping until next release" >&2
    exit 0
fi
