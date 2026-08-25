# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
from pathlib import Path


def test_charter_file_exists():
    charter = Path("docs/architecture/charter.md")
    assert charter.exists(), "omniclaude charter doc must exist"


def test_charter_declares_scope_boundary():
    """The charter's scope-boundary prose (plugin scaffolding / omnimarket /
    business logic split) now lives in the knowledge base
    (architecture/omniclaude-repo-charter.md) -- this repo's copy was thinned
    to the taxonomy pointer per the Wave 2 docs migration. Assert the pointer
    is intact rather than the prose, which no longer lives here."""
    charter = Path("docs/architecture/charter.md")
    text = charter.read_text()
    assert (
        "Full documentation \u2192 https://github.com/OmniNode-ai/knowledge-base"
        in text
    )
