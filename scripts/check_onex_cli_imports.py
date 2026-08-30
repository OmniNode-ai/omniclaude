#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""Assert the packaged ``onex`` CLI imports in this environment (OMN-17176).

**The gap this closes.** omnibase-core 0.47.1 registers ``run`` natively, while
omnibase-infra v0.38.9 still advertised ``run`` as an ``onex.cli`` entry point.
Core's OMN-16967 loader fails loud on a duplicate command name, so the packaged
``onex`` CLI raised ``ONEX_CORE_064_DUPLICATE_REGISTRATION`` at *import* time in
every freshly-resolved venv — which took down every onex-backed pre-commit hook
and made committing to omniclaude impossible from a clean worktree.

No required check caught it. omniclaude's CI runs ruff, mypy, pytest and a wall
of static gates, and not one of them invokes the console script the repo's own
hooks depend on. The breakage was invisible to CI and total for developers: the
worst possible split. It also hid in existing worktrees, whose ``.venv`` still
held core 0.46.x.

This check is the missing signal, and it is deliberately blunt: resolve the
``onex.cli`` entry-point group, report every duplicated command name with the
distributions claiming it, then import the CLI for real. A name claimed by two
installed distributions is reported here with both names attached, because the
bare loader traceback names only the second one to arrive and leaves you
guessing at the other side of the collision.

Exit codes:
    0 — the entry-point set is collision-free and the CLI imported
    1 — a duplicate command name, or the CLI failed to import
"""

from __future__ import annotations

import argparse
import sys
from collections import defaultdict
from importlib.metadata import entry_points

_CLI_EXTENSION_GROUP = "onex.cli"


def find_duplicate_commands() -> dict[str, list[str]]:
    """Map each duplicated ``onex.cli`` name to the distributions claiming it."""
    claimants: dict[str, list[str]] = defaultdict(list)
    for entry_point in entry_points(group=_CLI_EXTENSION_GROUP):
        dist = entry_point.dist
        claimants[entry_point.name].append(
            dist.name if dist is not None else "an unknown distribution"
        )
    return {name: sorted(dists) for name, dists in claimants.items() if len(dists) > 1}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.parse_args(argv)

    duplicates = find_duplicate_commands()
    if duplicates:
        print(
            "FAIL: two installed distributions advertise the same "
            f"'{_CLI_EXTENSION_GROUP}' command name.",
            file=sys.stderr,
        )
        for name, dists in sorted(duplicates.items()):
            print(f"  - '{name}' claimed by: {', '.join(dists)}", file=sys.stderr)
        print(
            "\nEntry points have no defined order across distributions, so which "
            "command runs would depend on the machine. omnibase_core's loader "
            "(OMN-16967) refuses to guess and raises at import, which takes the "
            "whole CLI down -- including every onex-backed pre-commit hook.\n"
            "Fix by moving the pin that carries the stale duplicate, not by "
            "pinning around the symptom.",
            file=sys.stderr,
        )
        return 1

    # The entry-point set is clean; now prove the CLI actually imports. The two
    # are not the same claim -- a malformed target or a non-click object fails
    # the loader without duplicating any name.
    try:
        from omnibase_core.cli.cli_commands import cli  # noqa: F401
    except Exception as exc:  # boundary-ok: reporting an install-time defect.
        print(
            f"FAIL: the packaged 'onex' CLI did not import: "
            f"{type(exc).__name__}: {exc}",
            file=sys.stderr,
        )
        return 1

    names = sorted(ep.name for ep in entry_points(group=_CLI_EXTENSION_GROUP))
    print(
        f"OK: 'onex' CLI imported; {len(names)} "
        f"'{_CLI_EXTENSION_GROUP}' extension(s) attached without collision: "
        f"{', '.join(names)}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
