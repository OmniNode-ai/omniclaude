# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""Falsifiability tests for the deploy-gate evidence matcher (OMN-14505).

THE PROOF STANDARD THIS FILE MUST MEET
--------------------------------------
This file is a check that checks checks. The defect under repair is exactly the
failure mode this file is most likely to reproduce, so it holds itself to the
standard the fix demands:

  A test that only proves "a check_value with no deploy words is REJECTED" is
  VACUOUS. The old matcher rejected that too. Such a test goes green against the
  UNFIXED code and proves nothing.

Every regression rejection test in sections 1-3 is therefore paired with an assertion
that the LEGACY substring matcher **ACCEPTS** the same input
(``_legacy_has_deploy_keyword(v) is True``). That pairing is what makes the RED real:
it proves the input actually reaches the old accept-path, so ``falsifiable is False``
is a genuine behavioural change against the EXISTS-but-WRONG state — not a green on
absence.

The vacuous fixtures are **verbatim strings from the live onex_change_control
corpus**, not strings invented for this test. An audit of OCC@dev (6,944
contracts) found 1,123 of 1,268 deploy-satisfying checks were circular greps of
the receipt the same OCC companion PR authored.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
import yaml

ACTION_DIR = Path(__file__).parent.parent.parent / ".github" / "actions" / "deploy-gate"
sys.path.insert(0, str(ACTION_DIR))

from validate_pr_deploy_required import (  # noqa: E402
    _legacy_has_deploy_keyword,
    classify_check_value,
    has_deploy_evidence,
)

# ---------------------------------------------------------------------------
# THE CRUX — the exact check_value that closed the REQUIRED deploy-gate on
# omnibase_infra PR #2279 via OCC PR #4067 (merged 2026-07-13 01:03:22Z),
# evidence item `dod-deploy-assessment-head-f973c737` on contract OMN-14487.
# Copied byte-for-byte from onex_change_control@dev.
# ---------------------------------------------------------------------------
PR_4067_CHECK_VALUE = (
    "grep -q '^status: PASS$' "
    "drift/dod_receipts/OMN-14487/dod-deploy-assessment-head-f973c737/command.yaml "
    "&& grep -qi 'no live deploy' "
    "drift/dod_receipts/OMN-14487/dod-deploy-assessment-head-f973c737/command.yaml"
)

# Verbatim vacuous check_values from the live OCC corpus, one per failure class.
VACUOUS_CORPUS: dict[str, str] = {
    # The dominant idiom: 1,123/1,268 satisfying checks. Greps its own receipt.
    "self_referential_receipt_grep": PR_4067_CHECK_VALUE,
    # OMN-11547 — bare receipt grep, passes the gate on the FILENAME alone
    # ("dod-no-deploy" contains "deploy"; the grep body never mentions deploying).
    "passes_on_filename_alone": (
        "grep -q '^status: PASS$' "
        '"drift/dod_receipts/OMN-11547/dod-no-deploy/command.yaml"'
    ),
    # OMN-11833 — greps the receipt for a sentence the author wrote into it.
    "greps_own_prose": (
        "grep -q 'no production deploy or runtime mutation performed' "
        '"drift/dod_receipts/OMN-11833/dod-deploy-no-prod/command.yaml"'
    ),
    # OMN-12826 — $CONTRACT_REPO_DIR form of the same circularity.
    "self_referential_via_contract_repo_dir": (
        "grep -q '^status: PASS$' "
        '"$CONTRACT_REPO_DIR/drift/dod_receipts/OMN-12826/dod-deploy/command.yaml"'
    ),
    # OMN-9120 — THE EMBED TRAP, ALREADY IN THE WILD (66 corpus instances).
    # It greps the receipt for the literal TEXT "docker exec". A stricter keyword
    # list passes this unchanged; only command-position parsing rejects it.
    "embed_trap_greps_for_the_word_docker_exec": (
        "grep -q 'docker exec' "
        "drift/dod_receipts/OMN-9120/dod-omnibase-infra-deploy-smoke/command.yaml "
        "&& grep -q 'status: PASS' "
        "drift/dod_receipts/OMN-9120/dod-omnibase-infra-deploy-smoke/command.yaml"
    ),
}

# The exact adversarial string the reviewer named: a probe keyword embedded as a
# quoted argument to echo, beside a circular grep. Must be REJECTED.
ADVERSARIAL_EMBED = "echo 'docker exec' && grep -q PASS my_own_receipt"

# Genuine probes from the live corpus — these MUST stay accepted. Rejecting them
# would wedge every consuming repo's merges (false-negative blast radius).
REAL_CORPUS: dict[str, str] = {
    # OMN-10124 — real docker exec into the deployed runtime container. Goes RED
    # against un-deployed code: the import fails if the container lacks the code.
    "docker_exec_import_smoke": (
        "docker exec ${RUNTIME_CONTAINER:-omninode-runtime} python -c "
        '"from omnimarket.nodes.node_emit_daemon.__main__ import _configure_logging; '
        "print('deploy smoke ok')\""
    ),
    "rpk_topic_consume": (
        "rpk topic consume onex.evt.omnimarket.dispatch-completed.v1 -n 1 --brokers localhost:19092"
    ),
    # Hosts below are placeholders on purpose: what the matcher keys on is the
    # command in command position, never the host, so a real internal IP would add
    # nothing to the assertion and would only trip the no-internal-ips gate.
    "psql_projection_readback": (
        "psql -h db.internal -U onex -d omnidash_analytics "
        '-c "select count(*) from dispatch_records" | grep -q "1 row"'
    ),
    "curl_health_endpoint": "curl -fsS http://runtime.internal:18085/health",
    "ssh_remote_container_check": (
        "ssh deploy@runtime.internal "
        "'docker ps --filter name=omninode-runtime --format {{.Status}}' | grep -q Up"
    ),
    # Wrapper forms — the real command must still surface through them.
    "env_wrapper": (
        "env -u PYTHONPATH docker exec omninode-runtime python -c 'import omnibase_core'"
    ),
    "bash_dash_c_wrapper": (
        "bash -c 'docker exec omninode-runtime python -c \"import omnibase_infra\"'"
    ),
    "command_substitution": (
        'test "$(docker inspect -f {{.State.Running}} omninode-runtime)" = "true"'
    ),
    "timeout_wrapper": "timeout 30 kubectl exec deploy/onex-runtime -- python -c 'import omnimarket'",
    # OMN-14443 backfill — the ONLY live-probe command reachable from every CI
    # runner (github.com, not a LAN/.201 host) that is ALSO not flagged by
    # onex_change_control's OMN-14051 hermetic-command guard, which is why that
    # guard's own rejection message recommends this exact `gh api` pattern.
    # Pinned to an immutable commit SHA, asserting a real content symbol —
    # mirrors the OCC#4012/OMN-14418 precedent.
    "gh_api_content_pinned_symbol": (
        'CONTENT="$(gh api '
        '"repos/OmniNode-ai/omnibase_infra/contents/src/x/handler.py?ref=abc123" '
        '--jq .content | base64 -d)" && echo "$CONTENT" | grep -q "def handle"'
    ),
}


# ---------------------------------------------------------------------------
# 1. THE CRUX — RED against the EXISTS-but-WRONG state.
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestPr4067IsRejected:
    """The exact check_value that closed a REQUIRED merge gate must now be rejected."""

    def test_legacy_matcher_accepted_it(self) -> None:
        """PRECONDITION for the RED below: prove the old rule really did accept it.

        Without this assertion the rejection test could be passing for the wrong
        reason (e.g. a typo'd fixture that no matcher ever accepted). This is the
        assertion that makes the next test a genuine RED against unfixed code
        rather than a green on absence.
        """
        assert _legacy_has_deploy_keyword(PR_4067_CHECK_VALUE) is True

    def test_new_matcher_rejects_it(self) -> None:
        verdict = classify_check_value(PR_4067_CHECK_VALUE)
        assert verdict.falsifiable is False
        assert "self-referential" in verdict.reason

    def test_it_passes_on_the_word_deploy_not_on_any_probe(self) -> None:
        """The check contains no probe at all — it only contains the WORD 'deploy'."""
        assert "deploy" in PR_4067_CHECK_VALUE.lower()
        assert "docker exec" not in PR_4067_CHECK_VALUE.lower()
        assert "rpk topic produce" not in PR_4067_CHECK_VALUE.lower()


# ---------------------------------------------------------------------------
# 2. Every vacuous class — each paired with proof the legacy rule accepted it.
# ---------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.parametrize(("name", "value"), sorted(VACUOUS_CORPUS.items()))
class TestVacuousCorpusIsRejected:
    def test_legacy_matcher_accepted_it(self, name: str, value: str) -> None:
        """EXISTS-but-WRONG precondition: the old gate passed all of these."""
        assert _legacy_has_deploy_keyword(value) is True, (
            f"{name}: fixture does not reach the legacy accept-path, so the "
            f"rejection assertion below would be a vacuous green on absence"
        )

    def test_new_matcher_rejects_it(self, name: str, value: str) -> None:
        assert classify_check_value(value).falsifiable is False, name


@pytest.mark.unit
class TestAdversarialEmbedTrap:
    """A stricter keyword list is NOT the fix — this is why."""

    def test_legacy_matcher_accepts_the_embed(self) -> None:
        assert _legacy_has_deploy_keyword(ADVERSARIAL_EMBED) is True

    def test_a_stricter_keyword_list_would_also_accept_the_embed(self) -> None:
        """Even after removing the bare word 'deploy', substring matching still passes."""
        strict_keywords = ["docker exec", "rpk topic produce"]  # 'deploy' removed
        assert any(kw in ADVERSARIAL_EMBED.lower() for kw in strict_keywords)

    def test_new_matcher_rejects_the_embed(self) -> None:
        verdict = classify_check_value(ADVERSARIAL_EMBED)
        assert verdict.falsifiable is False

    def test_docker_never_reaches_command_position_inside_echo(self) -> None:
        """The structural distinction substring matching cannot see."""
        verdict = classify_check_value("echo 'docker exec omninode-runtime true'")
        assert verdict.falsifiable is False
        assert "no live-surface probe in command position" in verdict.reason


# ---------------------------------------------------------------------------
# 3. No false negatives — real probes stay accepted, or every repo wedges.
# ---------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.parametrize(("name", "value"), sorted(REAL_CORPUS.items()))
def test_real_probes_are_accepted(name: str, value: str) -> None:
    verdict = classify_check_value(value)
    assert verdict.falsifiable is True, f"{name} FALSE NEGATIVE — {verdict.reason}"


# ---------------------------------------------------------------------------
# 4. Fail-closed on anything not provably a live probe.
# ---------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.parametrize(
    "value",
    [
        "",
        "   ",
        None,
        123,
        "echo 'deployed successfully'",
        "printf 'deploy ok\\n'",
        "test -f docs/evidence/deploy.md",
        "deploy omnibase_core to .201",  # prose — the old test fixture itself
        "true # deploy verified",
        "cat deploy_notes.txt",
        "grep -q PASS docs/evidence/deploy-report.md",  # non-receipt file, still no probe
        "docker exec 'unbalanced",  # unparseable -> fails CLOSED
        # `command -v`/`command -V` is a POSIX PATH-lookup builtin, not execution:
        # it only tests that `docker` resolves to an executable, so its exit
        # status carries no information about a live deployed surface. Unwrapping
        # it to `docker` (like a real wrapper) would be a false accept — CodeRabbit
        # finding on this PR.
        "command -v docker",
        "command -V docker",
    ],
)
def test_non_probes_fail_closed(value: object) -> None:
    assert classify_check_value(value).falsifiable is False


# ---------------------------------------------------------------------------
# 5. has_deploy_evidence: report mode preserves today's behaviour (zero merge
#    risk); enforce mode is load-bearing. The flip is env-only, not code.
# ---------------------------------------------------------------------------


def _contract(tmp_path: Path, check_value: str) -> Path:
    path = tmp_path / "OMN-14487.yaml"
    path.write_text(
        yaml.dump(
            {
                "dod_evidence": [
                    {
                        "id": "dod-deploy-assessment-head-f973c737",
                        "checks": [{"check_value": check_value}],
                    }
                ]
            }
        )
    )
    return path


@pytest.mark.unit
class TestRolloutModes:
    def test_report_mode_still_passes_the_vacuous_check(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Report mode = today's exit status exactly. This is the canary safety property:
        landing this PR cannot wedge any of the 4 consuming repos."""
        monkeypatch.setenv("DEPLOY_GATE_FALSIFIABILITY", "report")
        assert has_deploy_evidence(_contract(tmp_path, PR_4067_CHECK_VALUE)) is True

    def test_enforce_mode_rejects_the_vacuous_check(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("DEPLOY_GATE_FALSIFIABILITY", "enforce")
        assert has_deploy_evidence(_contract(tmp_path, PR_4067_CHECK_VALUE)) is False

    def test_enforce_mode_accepts_a_real_probe(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("DEPLOY_GATE_FALSIFIABILITY", "enforce")
        real = REAL_CORPUS["docker_exec_import_smoke"]
        assert has_deploy_evidence(_contract(tmp_path, real)) is True

    def test_default_mode_is_report(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("DEPLOY_GATE_FALSIFIABILITY", raising=False)
        assert has_deploy_evidence(_contract(tmp_path, PR_4067_CHECK_VALUE)) is True

    def test_missing_contract_fails_closed_in_both_modes(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        for mode in ("report", "enforce"):
            monkeypatch.setenv("DEPLOY_GATE_FALSIFIABILITY", mode)
            assert has_deploy_evidence(tmp_path / "OMN-99999.yaml") is False
