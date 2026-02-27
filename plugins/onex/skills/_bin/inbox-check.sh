#!/bin/bash
# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

# Inbox Check - Thin shell entrypoint
# Checks notifications and review requests for the authenticated user.
#
# Usage: inbox-check.sh --repo omniclaude [--format summary|json] [--run-id <id>]

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/_common.sh"
invoke_backend "inbox_check" "$@"
