#!/bin/bash
# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

# PR Scan - Thin shell entrypoint
# Lists open PRs for a repository with status summary.
#
# Usage: pr-scan.sh --repo omniclaude [--format summary|json] [--run-id <id>] [--out <path>]

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/_common.sh"
invoke_backend "pr_scan" "$@"
