#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Resolve an overlay-configured skill's overlay file [OMN-19235].

Every overlay-configured skill in this plugin is a public process interface
whose content — which commands, which boards, which directories — lives in an
overlay an installation provides. This file is the ONE search order they all
share, so a skill cannot resolve its overlay one way while its neighbour
resolves the same shape another way.

In order:

1. the explicit pointer the caller passed, when it passed one (``--overlay``);
2. the skill's own selector variable, ``<SKILL>_OVERLAY_PATH``;
3. each root in ``ONEX_SKILL_OVERLAY_ROOTS``, joined with ``<skill>/overlay.yaml``;
4. for a skill that opts in, the conventional per-user install directory,
   ``$XDG_CONFIG_HOME/onex/overlays/<skill>/overlay.yaml`` (or ``~/.config/...``).

The first two are explicit, so one that names no readable file is a hard stop
rather than a fall-through: a run told to use one overlay and silently given
another is the silent wrong answer every one of these skills refuses. The rest
fall through when absent. When nothing resolves, the refusal names every
location tried and every variable left unset, because a reader who has to fix it
needs to know where the resolver looked.

The selector name is derived from the skill name and never configured, so it
cannot drift from the ``overlay_env`` a skill declares in its frontmatter; a
test pins the two together.

Command line, used by each skill's first step::

    python3 resolve_skill_overlay.py <skill> [--overlay PATH] [--user-fallback]

Prints the resolved path on stdout and exits ``0``, or prints the refusal on
stderr and exits ``2``. Standard library only: a skill's first step runs this
under whatever ``python3`` the session has.
"""

from __future__ import annotations

import argparse
import os
import re
import sys
from pathlib import Path

EXIT_OK = 0
EXIT_CONFIG = 2

# A marketplace root, or several, separated by the platform path separator. One
# value set once, and every overlay-configured skill's overlay resolves.
OVERLAY_ROOTS_ENV = "ONEX_SKILL_OVERLAY_ROOTS"

# The file a root carries for each skill, under a directory named for the skill.
OVERLAY_FILENAME = "overlay.yaml"

EXPLICIT_SOURCE = "--overlay"
USER_FALLBACK_SOURCE = "the per-user overlay directory"

_USER_CONFIG_ENV = "XDG_CONFIG_HOME"
_USER_CONFIG_RELATIVE = Path("onex") / "overlays"

_SKILL_NAME = re.compile(r"^[a-z][a-z0-9_]*$")


class OverlayNotResolved(Exception):
    """No overlay resolved, or an explicit pointer missed. Refuse, never guess.

    ``tried`` carries one line per location searched and per selector left
    unset when nothing resolved, and is empty when an explicit pointer missed,
    so a caller can word its own refusal without parsing this one.
    """

    def __init__(self, message: str, tried: tuple[str, ...] = ()) -> None:
        super().__init__(message)
        self.tried = tried


def selector_env(skill: str) -> str:
    """The skill's own explicit selector variable, derived from its name."""
    if not _SKILL_NAME.match(skill):
        raise OverlayNotResolved(
            f"{skill!r} is not a skill name: expected lower-case letters, digits "
            f"and underscores"
        )
    return f"{skill.upper()}_OVERLAY_PATH"


def user_overlay_root() -> Path:
    """The per-user overlay directory, resolved the conventional way."""
    raw = os.environ.get(_USER_CONFIG_ENV)
    base = Path(raw) if raw else Path.home() / ".config"
    return base / _USER_CONFIG_RELATIVE


def _split_roots(raw: str | None) -> list[Path]:
    return [Path(part) for part in (raw or "").split(os.pathsep) if part.strip()]


def overlay_candidates(
    skill: str,
    *,
    explicit: str | None = None,
    user_fallback: bool = False,
) -> list[tuple[str, Path]]:
    """Every location the overlay is searched for, in order, as (source, path).

    Returned rather than walked internally so a refusal can name every location
    that was tried.
    """
    selector = selector_env(skill)
    relative = Path(skill) / OVERLAY_FILENAME
    candidates: list[tuple[str, Path]] = []
    if explicit:
        candidates.append((EXPLICIT_SOURCE, Path(explicit)))
    from_env = os.environ.get(selector)
    if from_env:
        candidates.append((selector, Path(from_env)))
    for root in _split_roots(os.environ.get(OVERLAY_ROOTS_ENV)):
        candidates.append((OVERLAY_ROOTS_ENV, root / relative))
    if user_fallback:
        candidates.append((USER_FALLBACK_SOURCE, user_overlay_root() / relative))
    return candidates


def resolve_overlay_path(
    skill: str,
    *,
    explicit: str | None = None,
    user_fallback: bool = False,
) -> Path:
    """Return the first overlay that resolves, or refuse naming every location."""
    selector = selector_env(skill)
    candidates = overlay_candidates(
        skill, explicit=explicit, user_fallback=user_fallback
    )
    for source, path in candidates:
        if path.is_file():
            return path
        if source in (EXPLICIT_SOURCE, selector):
            raise OverlayNotResolved(f"{source} points at no readable file: {path}")

    lines = [f"  - {source}: {path}" for source, path in candidates]
    # An UNSET pointer is not a location that was tried, and saying it was would
    # be a lie. It is still the thing a reader most needs named, so it is listed
    # as what it is: available and unset.
    for name in (selector, OVERLAY_ROOTS_ENV):
        if not os.environ.get(name):
            lines.append(f"  - {name}: not set")
    tried = "\n".join(lines)
    raise OverlayNotResolved(
        f"no {skill} overlay resolved. Locations tried, in order:\n{tried}",
        tuple(lines),
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="resolve_skill_overlay.py",
        description="Print the overlay file an overlay-configured skill resolves.",
    )
    parser.add_argument("skill", help="The skill's directory name, e.g. comment_sweep.")
    parser.add_argument(
        "--overlay",
        default=None,
        help="An explicit overlay path. Beats every other location; a miss is refused.",
    )
    parser.add_argument(
        "--user-fallback",
        action="store_true",
        help="Also search the per-user overlay directory, last.",
    )
    args = parser.parse_args(argv)
    try:
        path = resolve_overlay_path(
            args.skill, explicit=args.overlay, user_fallback=args.user_fallback
        )
    except OverlayNotResolved as exc:
        print(f"{args.skill}: REFUSED — {exc}", file=sys.stderr)
        return EXIT_CONFIG
    print(path)
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
