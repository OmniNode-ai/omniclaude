#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
#
# Shell path resolver for ONEX state directory.
# Source this file to export derived path variables.
#
# Requires ONEX_STATE_DIR to be set in the environment.

if [[ -z "${ONEX_STATE_DIR:-}" ]]; then
    echo "FATAL: ONEX_STATE_DIR is not set. Set it in ~/.omnibase/.env or export it." >&2
    return 1 2>/dev/null || exit 1
fi

export ONEX_LOG_DIR="${ONEX_STATE_DIR}/logs"
export ONEX_HOOKS_STATE_DIR="${ONEX_STATE_DIR}/hooks"
export ONEX_PIPELINES_DIR="${ONEX_STATE_DIR}/pipelines"
export ONEX_SESSION_STATE_DIR="${ONEX_STATE_DIR}/sessions"
export ONEX_HOOK_LOG="${ONEX_STATE_DIR}/logs/hooks.log"
export ONEX_HANDOFF_DIR="${ONEX_STATE_DIR}/handoff"
export ONEX_WORKTREES_DIR="${ONEX_STATE_DIR}/worktrees"
