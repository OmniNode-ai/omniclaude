# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
from pathlib import Path


def test_charter_file_exists():
    charter = Path("docs/architecture/charter.md")
    assert charter.exists(), "omniclaude charter doc must exist"


def test_charter_declares_scope_boundary():
    charter = Path("docs/architecture/charter.md")
    text = charter.read_text()
    assert "plugin scaffolding" in text
    assert "omnimarket" in text
    assert "business logic" in text
