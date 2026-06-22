# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Run the runtime_profiles contract validator with the omniclaude allowlist.

Mirrors the required CI gate `.github/workflows/validator-runtime-profiles.yml`
exactly: it constructs `ValidatorRuntimeProfiles` with the repo-local
`scripts/validation/runtime_profiles_allowlist.yaml` and validates `src/`.

This script exists so the local pre-commit hook and CI run the SAME invocation.
The validator's module `__main__` entry point resolves its allowlist from the
omnibase_core *package* directory, which does not contain the omniclaude repo's
frozen-violator allowlist — so invoking the bare module locally flags every
pre-existing allowlisted contract while CI passes. Pointing the hook at this
script removes that local/CI drift (OMN-13288, mirrors OMN-13297 for
omniintelligence/omnimemory and OMN-12955 for omnimarket).
"""

from __future__ import annotations

from pathlib import Path

from omnibase_core.validation.validator_runtime_profiles import (
    ValidatorRuntimeProfiles,
)

ALLOWLIST_PATH = Path("scripts/validation/runtime_profiles_allowlist.yaml")
SRC_ROOT = Path("src")


def main() -> int:
    result = ValidatorRuntimeProfiles(allowlist_path=ALLOWLIST_PATH).validate(SRC_ROOT)
    for issue in result.issues:
        print(
            f"[{issue.severity.value}] {issue.file_path}:{issue.line_number}: {issue.message}"
        )
    return 0 if result.is_valid else 1


if __name__ == "__main__":
    raise SystemExit(main())
