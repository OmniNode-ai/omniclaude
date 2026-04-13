# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""Structural tests for mandatory ModelTicketContract generation (OMN-8647).

Verifies that the 4 ticket-creation skills all contain the required contract
generation logic in their prompt/SKILL.md files. These tests are intentionally
textual — they guard against accidental removal of the mandatory contract block.
"""

from __future__ import annotations

from pathlib import Path

import pytest

_SKILLS_DIR = Path(__file__).resolve().parents[3] / "plugins" / "onex" / "skills"


@pytest.mark.unit
class TestCreateTicketMandatoryContract:
    """create_ticket SKILL.md must declare mandatory contract generation."""

    SKILL_FILE = _SKILLS_DIR / "create_ticket" / "SKILL.md"

    def test_skill_file_exists(self) -> None:
        assert self.SKILL_FILE.is_file(), f"Missing: {self.SKILL_FILE}"

    def test_mandatory_contract_section_present(self) -> None:
        content = self.SKILL_FILE.read_text(encoding="utf-8")
        assert "Contract Generation (MANDATORY)" in content or (
            "MANDATORY" in content and "ModelTicketContract" in content
        ), "create_ticket SKILL.md must contain MANDATORY contract generation section"

    def test_step_5_5_present(self) -> None:
        content = self.SKILL_FILE.read_text(encoding="utf-8")
        assert "Step 5.5" in content, (
            "create_ticket SKILL.md must have Step 5.5 (contract embedding)"
        )

    def test_contract_embedded_in_every_ticket(self) -> None:
        content = self.SKILL_FILE.read_text(encoding="utf-8")
        assert (
            "generate_model_ticket_contract" in content or "contract_yaml" in content
        ), "create_ticket must generate contract YAML for every ticket"

    def test_contract_completeness_stub_present(self) -> None:
        content = self.SKILL_FILE.read_text(encoding="utf-8")
        assert "contract_completeness" in content, (
            "create_ticket must use contract_completeness field (stub/enriched/full)"
        )


@pytest.mark.unit
class TestPlanToTicketsMandatoryContract:
    """plan_to_tickets SKILL.md must declare mandatory contract generation for all tickets."""

    SKILL_FILE = _SKILLS_DIR / "plan_to_tickets" / "SKILL.md"

    def test_skill_file_exists(self) -> None:
        assert self.SKILL_FILE.is_file(), f"Missing: {self.SKILL_FILE}"

    def test_post_creation_contracts_section_present(self) -> None:
        content = self.SKILL_FILE.read_text(encoding="utf-8")
        assert "Post-Creation" in content and "Contracts" in content, (
            "plan_to_tickets SKILL.md must have Post-Creation contract generation section"
        )

    def test_generate_contracts_for_all_tickets(self) -> None:
        content = self.SKILL_FILE.read_text(encoding="utf-8")
        assert (
            "generate_contracts_for_all" in content or "every ticket" in content.lower()
        ), (
            "plan_to_tickets must generate contracts for ALL tickets, not just seam tickets"
        )

    def test_no_seam_only_filter(self) -> None:
        """Must not filter contract generation to seam tickets only."""
        content = self.SKILL_FILE.read_text(encoding="utf-8")
        assert "Call generate-ticket-contract for every ticket" in content or (
            "no seam-keyword filtering" in content.lower()
        ), "plan_to_tickets must NOT filter contract generation to seam tickets only"


@pytest.mark.unit
class TestDecomposeEpicMandatoryContract:
    """decompose_epic prompt.md must generate contracts for all sub-tickets (OMN-8647)."""

    PROMPT_FILE = _SKILLS_DIR / "decompose_epic" / "prompt.md"

    def test_prompt_file_exists(self) -> None:
        assert self.PROMPT_FILE.is_file(), f"Missing: {self.PROMPT_FILE}"

    def test_mandatory_contract_comment_present(self) -> None:
        content = self.PROMPT_FILE.read_text(encoding="utf-8")
        assert "MANDATORY" in content and "ModelTicketContract" in content, (
            "decompose_epic prompt.md must contain MANDATORY contract generation comment"
        )

    def test_contract_embedded_mode_a(self) -> None:
        content = self.PROMPT_FILE.read_text(encoding="utf-8")
        assert (
            content.count("MANDATORY: generate and embed ModelTicketContract") >= 1
        ), "decompose_epic Mode A must embed a ModelTicketContract for each sub-ticket"

    def test_contract_embedded_mode_b(self) -> None:
        content = self.PROMPT_FILE.read_text(encoding="utf-8")
        assert (
            content.count("MANDATORY: generate and embed ModelTicketContract") >= 2
        ), (
            "decompose_epic Mode B must also embed a ModelTicketContract for each sub-ticket"
        )

    def test_contract_completeness_field_present(self) -> None:
        content = self.PROMPT_FILE.read_text(encoding="utf-8")
        assert "contract_completeness" in content, (
            "decompose_epic must set contract_completeness field on generated contracts"
        )

    def test_seam_detection_logic_present(self) -> None:
        content = self.PROMPT_FILE.read_text(encoding="utf-8")
        assert "seam_signals" in content, (
            "decompose_epic must run seam detection to set is_seam_ticket correctly"
        )

    def test_save_issue_called_after_creation(self) -> None:
        content = self.PROMPT_FILE.read_text(encoding="utf-8")
        assert "save_issue" in content, (
            "decompose_epic must call save_issue to embed the contract in the ticket description"
        )


@pytest.mark.unit
class TestTicketWorkMandatoryContract:
    """ticket_work prompt.md must auto-generate a stub contract during intake (OMN-8647)."""

    PROMPT_FILE = _SKILLS_DIR / "ticket_work" / "prompt.md"

    def test_prompt_file_exists(self) -> None:
        assert self.PROMPT_FILE.is_file(), f"Missing: {self.PROMPT_FILE}"

    def test_auto_generate_mentioned_in_initialization(self) -> None:
        content = self.PROMPT_FILE.read_text(encoding="utf-8")
        assert (
            "auto-generate" in content.lower() and "ModelTicketContract" in content
        ), (
            "ticket_work initialization must describe auto-generating a stub contract when absent"
        )

    def test_intake_phase_generates_stub_contract(self) -> None:
        content = self.PROMPT_FILE.read_text(encoding="utf-8")
        assert "stub ModelTicketContract" in content or (
            "generate" in content and "stub" in content and "intake" in content
        ), "ticket_work intake phase must generate a stub contract when none is found"

    def test_contract_generation_is_mandatory(self) -> None:
        content = self.PROMPT_FILE.read_text(encoding="utf-8")
        assert "MANDATORY" in content and "contract" in content.lower(), (
            "ticket_work must mark contract generation as MANDATORY"
        )

    def test_seam_detection_in_intake(self) -> None:
        content = self.PROMPT_FILE.read_text(encoding="utf-8")
        assert "seam_signals" in content, (
            "ticket_work intake phase must run seam detection when auto-generating the contract"
        )

    def test_save_issue_called_to_embed_contract(self) -> None:
        content = self.PROMPT_FILE.read_text(encoding="utf-8")
        assert "save_issue" in content, (
            "ticket_work must call save_issue to embed the auto-generated contract"
        )
