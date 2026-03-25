#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
set -euo pipefail
# Pre-flight scope check for epic agent tickets.
# Env: TICKET_ID, TICKET_REPO, EPIC_ID
# Exits 0 if ticket is valid for dispatch, 1 otherwise.

if [[ -z "${TICKET_REPO:-}" ]]; then
  echo "FAIL: Ticket ${TICKET_ID:-unknown} has no repo assignment" >&2
  exit 1
fi

echo "PASS: Ticket ${TICKET_ID:-unknown} assigned to repo ${TICKET_REPO} under epic ${EPIC_ID:-unknown}"
exit 0
