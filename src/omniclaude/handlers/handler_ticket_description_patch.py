# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Apply a Linear ``save_issue`` description patch (OMN-18404 rule 9).

Lifted out of ``plugins/onex/hooks/lib/ticket_creation_guard.py`` so the guard
script, a baselined mod file that may only shrink under the canonical-file-shape
ratchet, can take the lane-intake rules (OMN-17942) without growing. The guard
loads this module by path; it imports the standard library only, because the
guard runs under a bare interpreter with no ``omniclaude`` package.
"""

from __future__ import annotations

from typing import Any


def apply_description_patch(
    previous: str, operations: Any, error: type[ValueError]
) -> str:
    """The description ``operations`` produce when applied to ``previous``.

    ``save_issue`` can edit a description through ``patch`` instead of sending
    the whole field, and ticking a checkbox is exactly the shape somebody
    reaches for ``patch`` to do. A rule 9 that read only ``description`` would
    therefore miss the most likely route to the defect while looking like it
    covered it, so the ops are applied here and the RESULT is compared.

    Anchor semantics are the tool's own: every anchor must match exactly once,
    and the ops apply in order, atomically. Anything this cannot resolve to one
    definite result raises ``error`` and the caller refuses --
    "I could not work out what this writes" must not resolve to "so it passes".
    """
    if not isinstance(operations, list) or not operations:
        raise error("patch is not a non-empty list of operations")
    body = previous
    for index, raw in enumerate(operations):
        if not isinstance(raw, dict):
            raise error(f"operation {index} is not an object")
        op = raw.get("op")
        if op == "prepend":
            text = raw.get("text")
            if not isinstance(text, str):
                raise error(f"operation {index} carries no text")
            body = text + body
        elif op == "append":
            text = raw.get("text")
            if not isinstance(text, str):
                raise error(f"operation {index} carries no text")
            body = body + text
        elif op in {"insert_before", "insert_after"}:
            anchor, text = raw.get("anchor"), raw.get("text")
            if not isinstance(anchor, str) or not isinstance(text, str):
                raise error(f"operation {index} needs a string anchor and text")
            if body.count(anchor) != 1:
                raise error(
                    f"operation {index} anchor matches {body.count(anchor)} times"
                )
            at = body.index(anchor)
            at = at if op == "insert_before" else at + len(anchor)
            body = body[:at] + text + body[at:]
        elif op == "replace":
            old, new = raw.get("old_string"), raw.get("new_string")
            if not isinstance(old, str) or not old or not isinstance(new, str):
                raise error(
                    f"operation {index} needs a non-empty old_string and a new_string"
                )
            if raw.get("replace_all") is True:
                if old not in body:
                    raise error(f"operation {index} matches nothing")
                body = body.replace(old, new)
            else:
                if body.count(old) != 1:
                    raise error(
                        f"operation {index} old_string matches {body.count(old)} times"
                    )
                body = body.replace(old, new, 1)
        elif op == "replace_range":
            start, end = raw.get("from"), raw.get("to")
            new = raw.get("new_string")
            if (
                not isinstance(start, str)
                or not start
                or not isinstance(end, str)
                or not end
                or not isinstance(new, str)
            ):
                raise error(f"operation {index} needs from, to, new_string")
            if body.count(start) != 1:
                raise error(
                    f"operation {index} 'from' matches {body.count(start)} times"
                )
            head = body.index(start)
            tail = body.find(end, head + len(start))
            if tail == -1 or body.count(end, head + len(start)) != 1:
                raise error(
                    f"operation {index} 'to' does not follow 'from' exactly once"
                )
            body = body[:head] + new + body[tail:]
        else:
            raise error(f"operation {index} has unknown op {op!r}")
    return body


__all__ = ["apply_description_patch"]
