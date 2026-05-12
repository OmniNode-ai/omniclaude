#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

# Wrapper for the check-local-paths pre-commit hook.
# Fails loud if omnibase_core.validation.validator_local_paths is not importable —
# a missing validator is a configuration error, not a reason to silently pass.
set -euo pipefail

if uv run python -c "import omnibase_core.validation.validator_local_paths" 2>/dev/null; then
    exec uv run python -m omnibase_core.validation.validator_local_paths "$@"
else
    echo "ERROR: check-local-paths: omnibase_core.validation.validator_local_paths is not importable." >&2
    echo "  Run 'uv sync' to install omnibase_core, or check that omnibase_core is in your dependencies." >&2
    exit 1
fi
