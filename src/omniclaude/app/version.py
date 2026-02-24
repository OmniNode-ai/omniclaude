# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("omniclaude")
except PackageNotFoundError:
    __version__ = "0.0.0-dev"
