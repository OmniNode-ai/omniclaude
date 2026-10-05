# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Run the runtime_profiles contract validator over omniclaude with no allowlist.

Mirrors the required CI gate `.github/workflows/ci.yml (runtime-profiles)`
exactly, so the local pre-commit hook and CI run the SAME invocation.

The repo's frozen-violator allowlist (OMN-13288) burned down to zero and was
deleted (OMN-20560): every command-consuming contract under `src/` declares
`runtime_profiles`. The validator is constructed with an explicit empty
allowlist, which also turns off its walk-up discovery of a repo-root allowlist
file, so neither the omnibase_core package default nor a recreated file can
exempt a node here.
"""

from __future__ import annotations

from pathlib import Path

from omnibase_core.validation.validator_runtime_profiles import (
    ValidatorRuntimeProfiles,
)

SRC_ROOT = Path("src")


def main() -> int:
    result = ValidatorRuntimeProfiles(allowlist=set()).validate(SRC_ROOT)
    for issue in result.issues:
        print(
            f"[{issue.severity.value}] {issue.file_path}:{issue.line_number}: {issue.message}"
        )
    return 0 if result.is_valid else 1


if __name__ == "__main__":
    raise SystemExit(main())
