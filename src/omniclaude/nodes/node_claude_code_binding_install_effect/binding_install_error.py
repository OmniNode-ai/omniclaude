# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Errors the Claude Code binding install raises (OMN-18531)."""

from __future__ import annotations


class BindingInstallError(RuntimeError):
    """The install refused, or its readback disagreed with the render."""
