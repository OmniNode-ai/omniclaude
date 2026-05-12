#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""Wrapper for omnibase_core.validation.validator_local_paths.

Fails with a clear error if omnibase_core.validation.validator_local_paths
is not importable — a missing validator is a configuration error, not a
reason to silently pass.
"""

import sys


def main() -> None:
    try:
        from omnibase_core.validation.validator_local_paths import (  # type: ignore[import-not-found]
            main as validatorMain,
        )
    except ModuleNotFoundError:
        print(
            "ERROR: [check-local-paths] omnibase_core.validation.validator_local_paths "
            "is not importable. Run 'uv sync' to install omnibase_core.",
            file=sys.stderr,
        )
        sys.exit(1)

    # Module is available — delegate to it with all arguments
    sys.exit(validatorMain(sys.argv[1:]))


if __name__ == "__main__":
    main()
