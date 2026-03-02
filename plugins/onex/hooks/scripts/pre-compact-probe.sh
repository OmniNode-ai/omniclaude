#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

# PreCompact Probe - Step 0 diagnostic script.
# Verifies that (a) the hook fires, (b) session_id is present, (c) cwd is present.
#
# Deploy steps:
#   1. Register this script in hooks.json under "PreCompact"
#   2. Run /compact inside an active Claude Code session
#   3. cat /tmp/omniclaude-precompact-probe.log
#
# Expected output line:
#   2026-01-01T00:00:00Z PreCompact fired. session_id=<uuid> cwd=/path/to cwd_present=true keys="cwd,session_id,..."
#
# Gate: Replace this probe with pre-compact.sh ONLY after confirming:
#   (a) A log line appears in the probe log
#   (b) session_id is non-"missing"
#   (c) cwd is present in payload keys (or "missing" — update pre-compact.sh accordingly)

INPUT=$(cat)
echo "$(date -u +%Y-%m-%dT%H:%M:%SZ) PreCompact fired." \
  "session_id=$(echo "$INPUT" | jq -r '.session_id // .sessionId // "missing"')" \
  "cwd=$(echo "$INPUT" | jq -r '.cwd // "missing"')" \
  "keys=$(echo "$INPUT" | jq -r 'keys | @csv')" \
  >> /tmp/omniclaude-precompact-probe.log
exit 0
