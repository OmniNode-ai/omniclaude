#!/usr/bin/env python3
"""Wrapper for omnibase_core.validation.validator_local_paths.

Gracefully skips the check when omnibase_core.validation.validator_local_paths
is not available (e.g. during the transition period before omnibase-core 0.19.0
is released to PyPI and dependency constraints are updated).

Remove this wrapper once omnibase-core>=0.19.0 is stable and the pre-commit
hook can reference the module directly.
"""

import sys


def main() -> None:
    try:
        from omnibase_core.validation.validator_local_paths import (  # type: ignore[import-not-found]
            main as validator_main,
        )
    except ModuleNotFoundError:
        print(
            "[check-local-paths] WARNING: omnibase_core.validation.validator_local_paths "
            "not available (requires omnibase-core>=0.19.0). "
            "Skipping local path check until dependency is updated.",
            file=sys.stderr,
        )
        sys.exit(0)

    # Module is available — delegate to it with all arguments
    sys.exit(validator_main(sys.argv[1:]))


if __name__ == "__main__":
    main()
