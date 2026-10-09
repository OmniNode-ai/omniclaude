# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Shell word quoting kinds."""

from enum import StrEnum


class EnumQuoteKind(StrEnum):
    """Unquoted; inside double quotes; or single quotes/a backslash escape.

    Nothing is expanded in single quotes or a backslash escape.
    """

    NONE = "none"
    DOUBLE = "double"
    LITERAL = "literal"
