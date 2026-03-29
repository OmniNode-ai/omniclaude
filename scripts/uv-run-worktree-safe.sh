#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
#
# uv-run-worktree-safe.sh — Wrapper for `uv run` in pre-commit/pre-push hooks.
#
# Problem: pre-commit sets GIT_DIR and GIT_WORK_TREE env vars. When uv resolves
# git-based dependencies (e.g., omninode-intelligence @ git+https://...),
# it spawns a `git fetch` subprocess that inherits these vars. In a git worktree,
# the GIT_DIR points to a .git/worktrees/<name> path, which the subprocess's
# `git fetch` cannot use — it errors with "fatal: not a git repository".
#
# Fix: unset GIT_DIR and GIT_WORK_TREE before calling uv run, so uv's internal
# git subprocess can discover the repository normally.
#
# Usage in .pre-commit-config.yaml:
#   entry: bash scripts/uv-run-worktree-safe.sh python scripts/validation/my_check.py
# instead of:
#   entry: uv run python scripts/validation/my_check.py

set -euo pipefail

unset GIT_DIR 2>/dev/null || true
unset GIT_WORK_TREE 2>/dev/null || true

exec uv run "$@"
