#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
#
# canonical-clone-sync-tick.sh -- the launchd catch-all for canonical-clone
# freshness (OMN-19607).
#
# The PostToolUse hook post_tool_use_merge_clone_sync.sh fast-forwards the
# matching clones when THIS Mac makes a merge. Most merges are not made here:
# auto-merge completes on GitHub's side minutes after it is armed, and other
# people and other hosts merge too. This tick runs the same engine over every
# canonical clone under $OMNI_HOME and every registry root, so a merge made
# anywhere reaches the clones within one interval.
#
# Driven by scripts/launchd/ai.omninode.canonical-clone-sync.plist
# (StartInterval). Install just this agent with:
#
#   bash omniclaude/scripts/tick-bundle-install.sh --only ai.omninode.canonical-clone-sync
#
# The engine logs one JSON line per clone to
# $ONEX_STATE_DIR/logs/canonical-clone-sync.jsonl, with the before, after and
# target sha, or the refusal reason. It spends no GitHub API quota.
#
# Replacement: the webhook path of the GitHub-quota plan (OMN-19470, the
# onexbot-pr-reader App's push deliveries into the bus) makes this poll
# unnecessary; see the engine's module docstring.

set -euo pipefail

OMNI_HOME="${OMNI_HOME:?OMNI_HOME is not set; there is no default registry path}"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ENGINE="${SCRIPT_DIR}/../plugins/onex/hooks/lib/canonical_clone_sync.py"
[[ -f "${ENGINE}" ]] || { echo "canonical-clone-sync-tick: engine missing at ${ENGINE}" >&2; exit 2; }

# launchd runs with a restricted PATH. The plist sets PATH to the literal
# Homebrew bin directories (rule 11: never a $(brew --prefix) expansion), so
# python3.13 resolves to the project interpreter. The engine is standard
# library only.
PY="$(command -v python3.13 || true)"
[[ -n "${PY}" ]] || { echo "canonical-clone-sync-tick: no python3.13 on PATH=${PATH}" >&2; exit 2; }

exec env -u PYTHONPATH "${PY}" "${ENGINE}" sync --trigger timer
