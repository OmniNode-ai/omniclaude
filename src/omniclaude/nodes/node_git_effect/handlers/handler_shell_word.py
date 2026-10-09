# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Shell word types and regexes split out of handler_shell_words for OMN-20685."""

from __future__ import annotations

import re
from dataclasses import dataclass

from omniclaude.nodes.node_git_effect.enums.enum_quote_kind import EnumQuoteKind

_ASSIGNMENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")
_UNQUOTED_GLOB = re.compile(r"[*?\[]")
_UNQUOTED_BRACE = re.compile(r"\{[^{}]*(?:,|\.\.)[^{}]*\}")


class ShellSyntaxError(ValueError):
    """The command cannot be split into words (an unbalanced quote, most likely)."""

    # Set by the tokenizer at a shell separator, never by searching raw prose.
    segment_start: int | None = None


class UnresolvableWord(ValueError):
    """A word whose value the shell would compute and this module will not."""


@dataclass(frozen=True)
class WordPart:
    text: str
    # "none": unquoted; "double": inside double quotes; "literal": single
    # quotes or a backslash escape, where nothing is expanded.
    quote: EnumQuoteKind


@dataclass(frozen=True)
class Word:
    parts: tuple[WordPart, ...]

    @property
    def text(self) -> str:
        """The word with quotes removed and nothing expanded."""
        return "".join(part.text for part in self.parts)

    @property
    def splits(self) -> bool:
        """True when an unquoted expansion makes the shell word-split this word."""
        return any(
            part.quote == EnumQuoteKind.NONE and ("$" in part.text or "`" in part.text)
            for part in self.parts
        )

    @property
    def is_plain(self) -> bool:
        """True when the word needs no expansion at all."""
        for part in self.parts:
            if part.quote == EnumQuoteKind.LITERAL:
                continue
            if "$" in part.text or "`" in part.text:
                return False
            if part.quote == EnumQuoteKind.NONE and (
                part.text.startswith("~")
                or _UNQUOTED_GLOB.search(part.text)
                or _UNQUOTED_BRACE.search(part.text)
            ):
                return False
        return True

    def assignment(self) -> tuple[str, Word] | None:
        """``(NAME, value)`` when this word is a ``NAME=value`` assignment."""
        if not self.parts or self.parts[0].quote != EnumQuoteKind.NONE:
            return None
        head = self.parts[0].text
        match = _ASSIGNMENT.match(head)
        if match is None:
            return None
        name = head[: match.end() - 1]
        rest = head[match.end() :]
        value_parts = (
            (WordPart(rest, EnumQuoteKind.NONE),) if rest else ()
        ) + self.parts[1:]
        return name, Word(value_parts)


@dataclass(frozen=True)
class Operator:
    text: str
