#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
#
# CI lint gate: fail if any gated plugin file contains monorepo-local references.
# OMN-8795 (SD-08); rewritten as a wrapper by OMN-16850.
#
# This script used to carry its own hand-copied `grep -E` pattern list, a second
# implementation of the rule already living in
# tests/skills/test_no_monorepo_refs_in_plugin_skills.py. The two drifted by
# construction -- one engine's escaping is not the other's -- so both now call the
# single matcher in scripts/skill_monorepo_refs.py over the single registry in
# scripts/skill_monorepo_ref_patterns.json. Keep this file thin: patterns and roots
# belong in the JSON, matching belongs in the Python.
#
# Escape hatch: append "# local-path-ok: <reason>" to the offending line.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

PYTHON=""
for candidate in python3 python; do
  if command -v "$candidate" >/dev/null 2>&1; then
    PYTHON="$candidate"
    break
  fi
done

if [ -z "$PYTHON" ]; then
  echo "::error::skill monorepo-ref gate needs python3 on PATH and found none" >&2
  echo "The gate fails closed rather than reporting a pass it did not perform." >&2
  exit 1
fi

exec "$PYTHON" "$SCRIPT_DIR/skill_monorepo_refs.py" "$@"
