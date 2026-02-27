#!/bin/bash
# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

# Repo Sync Status - Thin shell entrypoint
# Checks synchronization state between local clone and remote.
#
# Usage: repo-sync-status.sh --repo omniclaude [--format summary|json] [--run-id <id>]

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/_common.sh"
invoke_backend "repo_sync_status" "$@"
