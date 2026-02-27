#!/bin/bash
# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

# CI Status - Thin shell entrypoint
# Checks CI/CD status for a specific PR or the default branch.
#
# Usage: ci-status.sh --repo omniclaude [--pr 123] [--format summary|json] [--run-id <id>]

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/_common.sh"
invoke_backend "ci_status" "$@"
