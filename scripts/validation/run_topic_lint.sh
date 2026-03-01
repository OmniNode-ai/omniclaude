#!/usr/bin/env bash
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 OmniNode Team
#
# Wrapper: run topic-naming-lint against Python source files. (OMN-3259)
#
# Usage: invoked by pre-commit as a system-language hook.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LINT="$SCRIPT_DIR/lint_topic_names.py"
RC=0

uv run python "$LINT" --scan-python src/omniclaude || RC=$?

exit "$RC"
