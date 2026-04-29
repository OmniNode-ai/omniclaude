#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

set -euo pipefail

DB_PATH="${OPENCODE_DB_PATH:-${HOME}/.local/share/opencode/opencode.db}"

if [[ ! -f "${DB_PATH}" ]]; then
    printf '%s\n' "opencode session db not found at ${DB_PATH}; nothing to emit" >&2
    exit 0
fi

if command -v uv >/dev/null 2>&1 && [[ -f "pyproject.toml" ]]; then
    exec uv run python -m omniclaude.hooks.opencode_emitter --db-path "${DB_PATH}"
fi

exec python3 -m omniclaude.hooks.opencode_emitter --db-path "${DB_PATH}"
