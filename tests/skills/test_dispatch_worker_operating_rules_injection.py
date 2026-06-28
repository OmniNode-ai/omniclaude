# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""OMN-9690: Verify dispatch_worker skill injects Operating Rules into worker prompts."""

from pathlib import Path

import pytest

SKILLS_ROOT = Path(__file__).parents[2] / "plugins" / "onex" / "skills"
DISPATCH_WORKER_DIR = SKILLS_ROOT / "dispatch_worker"

REQUIRED_RULES = [
    "No pre-existing excuse",
    "PR closing keyword",
    "Worktree-only development",
    "Full test suite before push",
    "Never bypass pre-commit hooks",
    "Anchor-first ordering",
    "Verifiable-handle reporting",
    "OCC receipt pairing",
    # OMN-13052 (D-6): UI DoD items require Playwright proof, not curl.
    "UI proof requires Playwright",
]

WORKER_TEMPLATE_VERSION = "v2"

# OMN-13052 (D-6): phrases that must appear in the UI-verification operating rule so a
# worker cannot pass a UI claim with a curl of the canonical endpoint.
UI_VERIFICATION_REQUIRED_PHRASES = [
    "Playwright",
    "operator's running surface",
    "screenshot",
    "network log",
]


@pytest.mark.unit
def test_skill_md_has_worker_template_version() -> None:
    skill_md = DISPATCH_WORKER_DIR / "SKILL.md"
    assert skill_md.exists(), f"SKILL.md not found at {skill_md}"
    content = skill_md.read_text()
    assert f"worker_template_version: {WORKER_TEMPLATE_VERSION}" in content, (
        f"SKILL.md missing 'worker_template_version: {WORKER_TEMPLATE_VERSION}'"
    )


@pytest.mark.unit
def test_skill_md_documents_all_operating_rules() -> None:
    skill_md = DISPATCH_WORKER_DIR / "SKILL.md"
    content = skill_md.read_text()
    missing = [rule for rule in REQUIRED_RULES if rule not in content]
    assert not missing, f"SKILL.md missing Operating Rules documentation: {missing}"


@pytest.mark.unit
def test_prompt_md_injects_operating_rules_header() -> None:
    prompt_md = DISPATCH_WORKER_DIR / "prompt.md"
    assert prompt_md.exists(), f"prompt.md not found at {prompt_md}"
    content = prompt_md.read_text()
    assert "## Inject Operating Rules" in content, (
        "prompt.md missing '## Inject Operating Rules' section"
    )


@pytest.mark.unit
def test_prompt_md_contains_all_operating_rules() -> None:
    prompt_md = DISPATCH_WORKER_DIR / "prompt.md"
    content = prompt_md.read_text()
    missing = [rule for rule in REQUIRED_RULES if rule not in content]
    assert not missing, f"prompt.md missing Operating Rules text: {missing}"


@pytest.mark.unit
def test_prompt_md_uses_final_prompt_in_agent_spawn() -> None:
    prompt_md = DISPATCH_WORKER_DIR / "prompt.md"
    content = prompt_md.read_text()
    assert "prompt=final_prompt" in content, (
        "prompt.md Agent() spawn must use 'prompt=final_prompt', "
        "not 'prompt=result.validated_prompt_template'"
    )


@pytest.mark.unit
def test_prompt_md_does_not_pass_raw_validated_template_to_agent() -> None:
    prompt_md = DISPATCH_WORKER_DIR / "prompt.md"
    content = prompt_md.read_text()
    # The raw template reference should only appear in the node invocation section,
    # not as the agent spawn argument.
    spawn_section_start = content.find("## Spawn Agent")
    assert spawn_section_start != -1, "prompt.md missing '## Spawn Agent' section"
    spawn_section = content[spawn_section_start:]
    assert "prompt=result.validated_prompt_template" not in spawn_section, (
        "Spawn Agent section must not pass raw validated_prompt_template; "
        "use final_prompt (Operating Rules prepended)"
    )


@pytest.mark.unit
def test_operating_rules_version_consistent_across_files() -> None:
    skill_md = DISPATCH_WORKER_DIR / "SKILL.md"
    prompt_md = DISPATCH_WORKER_DIR / "prompt.md"
    version_tag = f"worker_template_version: {WORKER_TEMPLATE_VERSION}"
    for path in (skill_md, prompt_md):
        content = path.read_text()
        assert version_tag in content, (
            f"{path.name} missing version tag '{version_tag}'"
        )


# OMN-13050 (retro D-4): the OCC receipt-pairing recipe must be tool-generated and
# embedded verbatim, with each prohibition paired to a failure mode + alternative.

OCC_RECIPE_MARKERS = [
    "scaffold_occ_receipt.py",
    "contract_sha256",
    "--base",
    "STOP and report back",
    "Evidence-Source",
    "Evidence-Ticket",
]


@pytest.mark.unit
def test_prompt_md_embeds_occ_receipt_recipe() -> None:
    """prompt.md injects the tool-generated OCC recipe incl. contract_sha256."""
    prompt_md = DISPATCH_WORKER_DIR / "prompt.md"
    content = prompt_md.read_text()
    missing = [m for m in OCC_RECIPE_MARKERS if m not in content]
    assert not missing, f"prompt.md missing OCC recipe markers: {missing}"


@pytest.mark.unit
def test_prompt_md_skip_token_prohibition_pairs_alternative() -> None:
    """The skip-token prohibition states the failure mode AND the alternative."""
    prompt_md = DISPATCH_WORKER_DIR / "prompt.md"
    content = prompt_md.read_text()
    # Failure mode (hard-fail) and alternative (STOP and report back) co-located.
    assert "hard-fails your PR" in content or "hard-FAILS" in content, (
        "prompt.md must state the skip-token failure mode (hard-fail)"
    )
    assert "STOP and report back" in content, (
        "prompt.md must pair the skip-token prohibition with the "
        "'STOP and report back' alternative (feedback_workers_disregard_negative_directives)"
    )


@pytest.mark.unit
def test_skill_md_references_occ_recipe() -> None:
    """SKILL.md keeps the OCC recipe rule in sync with prompt.md."""
    skill_md = DISPATCH_WORKER_DIR / "SKILL.md"
    content = skill_md.read_text()
    assert "scaffold_occ_receipt.py" in content, (
        "SKILL.md must reference the OCC receipt scaffold tool"
    )
    assert "contract_sha256" in content, (
        "SKILL.md must name contract_sha256 as part of the tool-generated schema"
    )


# OMN-13052 (D-6): every worker prompt must require Playwright proof for UI DoD items
# and explicitly reject a curl of the canonical endpoint as UI evidence. Bridges the
# gap until the A-2 Receipt-Gate evidence-class check (OMN-13024) is live.


@pytest.mark.unit
@pytest.mark.parametrize("filename", ["SKILL.md", "prompt.md"])
def test_dispatch_template_has_ui_verification_line(filename: str) -> None:
    """The UI-verification rule names Playwright + operator surface + screenshot + network log."""
    # Normalize whitespace: markdown wraps prose across lines, so a required
    # phrase may straddle a line break in the source.
    content = " ".join((DISPATCH_WORKER_DIR / filename).read_text().split())
    missing = [p for p in UI_VERIFICATION_REQUIRED_PHRASES if p not in content]
    assert not missing, (
        f"{filename} missing UI-verification phrases for the Playwright rule: {missing}"
    )


@pytest.mark.unit
@pytest.mark.parametrize("filename", ["SKILL.md", "prompt.md"])
def test_dispatch_template_rejects_curl_for_ui_claims(filename: str) -> None:
    """A curl of the canonical endpoint is explicitly NOT acceptable UI proof."""
    content = (DISPATCH_WORKER_DIR / filename).read_text().lower()
    assert "curl" in content, (
        f"{filename} must name curl so it can be rejected as UI evidence"
    )
    assert "not acceptable" in content, (
        f"{filename} must state curl is NOT acceptable evidence for a UI claim"
    )
