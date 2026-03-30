# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Build verification prompt for independent verifier agent (B).

The verifier agent receives this prompt and operates independently from the
implementing agent. It has no access to conversation history and must verify
task completion solely from contract, evidence artifacts, and live repo state.
"""

from __future__ import annotations


def build_verifier_prompt(
    task_id: str,
    contract_path: str,
    self_check_path: str,
    repo: str,
    branch: str,
) -> str:
    """Build the prompt for the independent task verifier agent.

    The returned prompt instructs the verifier to:
    - Re-run all contract checks independently (self-check is non-authoritative)
    - Verify against live repository state, not claims
    - Write structured evidence to .onex_state/evidence/
    """
    return f"""You are an independent task verifier. Your job is to verify that task {task_id} is actually complete.

VERIFICATION RULES:
- Verify from contract, repository state, and mechanical evidence ONLY
- The repository is the authoritative source of truth
- Do NOT trust the implementing agent's self-check — it is non-authoritative
- Run every check independently — re-execute all commands yourself
- Report PASS or FAIL with specific evidence for each check

INPUTS:
1. Read the task contract: {contract_path}
2. Read the self-check evidence: {self_check_path}
3. Verify in repo: {repo} on branch: {branch}

PROCESS:
1. Read the contract YAML and extract all definition_of_done checks
2. For each check, execute it independently in the repo worktree
3. Compare your results against the self-check evidence
4. Write your verification to .onex_state/evidence/{task_id}/verifier-check.yaml

OUTPUT FORMAT:
Write a YAML file with:
- task_id: {task_id}
- verifier_model: (your model name)
- passed: true/false
- checks: list of criterion + status (PASS or FAIL) + your_output
- agreement_with_self_check: true/false
- disagreement_details: (if any checks disagree with self-check)
"""
