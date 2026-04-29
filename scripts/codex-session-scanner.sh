#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
export PYTHONPATH="${repo_root}/src:${repo_root}:${PYTHONPATH:-}"

cd "${repo_root}"
if command -v uv >/dev/null 2>&1; then
    exec uv run python -m omniclaude.hooks.codex_emitter "$@"
fi

exec python -m omniclaude.hooks.codex_emitter "$@"
