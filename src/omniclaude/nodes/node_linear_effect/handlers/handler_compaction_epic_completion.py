#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Read an epic's Linear children and fail unless every child of a track is Done.

Used by OMN-21090's evidence contract. A contribution to one child never establishes
completion of a whole epic track. Missing authorization and incomplete reads fail.
"""

from __future__ import annotations

import argparse
import sys
from typing import cast

from omniclaude.nodes.node_linear_effect.handlers.handler_linear_ticketing import (
    LinearApiError,
    Transport,
    http_transport,
)

_QUERY = """query($id: String!) {
  issue(id: $id) {
    children(first: 100) {
      nodes { identifier title state { name } }
      pageInfo { hasNextPage }
    }
  }
}"""


def _object(value: object) -> dict[str, object]:
    if not isinstance(value, dict) or any(not isinstance(key, str) for key in value):
        raise ValueError("Linear returned a non-object; completion is unreadable")
    return cast("dict[str, object]", value)


def validate_children(result: dict[str, object], title_prefix: str) -> None:
    """Require a complete, nonempty track read and report every unfinished child."""
    if result.get("errors"):
        raise ValueError("Linear returned errors; completion is unreadable")
    data = _object(result["data"])
    children = _object(_object(data["issue"])["children"])
    if _object(children["pageInfo"])["hasNextPage"] is not False:
        raise ValueError("Child list is paginated; completion is unreadable")
    nodes = children["nodes"]
    if not isinstance(nodes, list):
        raise ValueError("Linear returned no child array; completion is unreadable")
    members: list[dict[str, object]] = []
    for value in nodes:
        child = _object(value)
        title = child["title"]
        if not isinstance(title, str):
            raise ValueError("Linear returned no child title; completion is unreadable")
        if title.startswith(title_prefix):
            members.append(child)
    if not members:
        raise ValueError("Track has no children; completion is unreadable")
    pending = [
        str(child["identifier"])
        for child in members
        if _object(child["state"])["name"] != "Done"
    ]
    if pending:
        raise ValueError("Track remains incomplete: " + ", ".join(pending))


def main(
    argv: list[str] | None = None, *, transport: Transport = http_transport
) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--epic", required=True)
    parser.add_argument("--title-prefix", required=True)
    args = parser.parse_args(argv)
    try:
        result: dict[str, object] = {"data": transport(_QUERY, {"id": args.epic})}
        validate_children(result, args.title_prefix)
    except (
        OSError,
        LinearApiError,
        ValueError,
        KeyError,
        TypeError,
        AttributeError,
    ) as exc:
        # HTTP errors are deliberately rendered without response bodies or headers.
        sys.stderr.write(f"Linear completion check failed: {exc}\n")
        return 1
    sys.stdout.write(f"{args.epic} {args.title_prefix}: every child is Done\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
