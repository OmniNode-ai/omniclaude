#!/bin/bash
# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

# PR Merge Readiness - Thin shell entrypoint
# Checks whether a specific PR is ready to merge.
#
# Usage: pr-merge-readiness.sh --repo omniclaude --pr 123 [--format summary|json] [--run-id <id>]

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/_common.sh"
invoke_backend "pr_merge_readiness" "$@"
