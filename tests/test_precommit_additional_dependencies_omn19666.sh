#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
guard="${repo_root}/scripts/validation/check_precommit_additional_dependencies.sh"
bad_fixture="${repo_root}/tests/fixtures/omn19666/pre-commit-git-dependency.yaml"
good_fixture="${repo_root}/tests/fixtures/omn19666/pre-commit-pypi-dependency.yaml"
output="$(mktemp)"
trap 'rm -f "${output}"' EXIT

if bash "${guard}" "${bad_fixture}" >"${output}" 2>&1; then
  echo "expected the git dependency fixture to be rejected" >&2
  exit 1
fi
grep -Fq "additional_dependencies must use a released package" "${output}"

bash "${guard}" "${good_fixture}"
bash "${guard}" "${repo_root}/.pre-commit-config.yaml"

echo "pre-commit additional_dependencies guard: fixture and live-config checks passed"
