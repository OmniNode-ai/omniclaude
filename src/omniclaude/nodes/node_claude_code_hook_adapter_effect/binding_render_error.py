# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Errors the Claude Code binding render and adapter raise (OMN-18531)."""

from __future__ import annotations


class BindingRenderError(ValueError):
    """A binding row cannot be rendered: it names something the hook input does not carry."""
