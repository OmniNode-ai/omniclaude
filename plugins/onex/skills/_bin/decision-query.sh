#!/bin/bash
# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

# Decision Query - Thin shell entrypoint
# Queries the local decision store for recent decisions.
#
# Usage: decision-query.sh --repo omniclaude [--format summary|json] [--run-id <id>]

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/_common.sh"
invoke_backend "decision_query" "$@"
