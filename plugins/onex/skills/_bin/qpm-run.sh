#!/bin/bash
# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

# QPM Run - Full queue priority manager pass
# Usage: qpm-run.sh [--repo <repo>] [--mode shadow|label_gated|auto] [--repos repo1,repo2] [--dry-run] [--max-promotions N]

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/_common.sh"
invoke_backend "qpm_run" "$@"
