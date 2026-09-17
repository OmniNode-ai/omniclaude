# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Tests for the credential-rotation admission gate (OMN-17957).

Written red first: the first run of this file was a collection error against an
absent decision core, recorded on OMN-17957.

The gate enforces the operator ruling of 2026-09-05. Every case below is either
a command shape taken from the 30-day rotation sweep on that ticket, or a way
the consent citation can fail to establish authorisation. There is deliberately
no case asserting that some spelling of "I decided this was a leak" is admitted:
an agent's own judgement is never the authorisation, so no test may encode one.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
LIB_DIR = REPO_ROOT / "plugins" / "onex" / "hooks" / "lib"
HOOK_SCRIPT = (
    REPO_ROOT
    / "plugins"
    / "onex"
    / "hooks"
    / "scripts"
    / "pre_tool_use_credential_rotation_guard.sh"
)
POLICY_PATH = (
    REPO_ROOT
    / "plugins"
    / "onex"
    / "hooks"
    / "config"
    / "credential_rotation_policy.json"
)

sys.path.insert(0, str(LIB_DIR))

from credential_rotation_guard import (  # noqa: E402
    CONSENT_CITATION_GRAMMAR,
    GATE_BIT_NAME,
    Finding,
    Policy,
    PolicyError,
    check_bash_command,
    evaluate_bash_command,
    load_policy,
    render_block_reason,
    split_heredocs,
)

pytestmark = pytest.mark.unit


# --------------------------------------------------------------------------
# Fixtures
# --------------------------------------------------------------------------

#: A well-formed consent row: rule 18 of omni_home CLAUDE.md, extended by
#: OMN-17957 rule 22 with the approved_by field. The quoted words here are a
#: TEST FIXTURE and are not attributed to anybody.
GOOD_ROW = (
    "2026-09-05T12:00:00Z | OPERATOR-CONSENT | lane=fixture-lane | "
    "approved_by=operator | "
    '"fixture consent row, not operator words" | '
    "APPROVED SCOPE: rotate the Infisical operator-k8s client secret and "
    "restart every consumer | "
    "OUT OF SCOPE: every other credential, any prod runtime promotion | "
    "This row is the durable authorization evidence"
)

JAKE_ROW = GOOD_ROW.replace("approved_by=operator", "approved_by=jake")

#: Same shape, but the approver is a lane rather than one of the two people.
SELF_APPROVED_ROW = GOOD_ROW.replace("approved_by=operator", "approved_by=lane")

#: A consent row with no OUT OF SCOPE list. Rule 18 requires both lists; the
#: missing half is the one that BOUNDS the grant, and a row without it looks
#: identical to a valid one to the next lane that cites it.
NO_OUT_OF_SCOPE_ROW = (
    "2026-09-05T12:00:00Z | OPERATOR-CONSENT | lane=fixture-lane | "
    "approved_by=operator | "
    '"fixture consent row, not operator words" | '
    "APPROVED SCOPE: rotate the Infisical operator-k8s client secret | "
    "This row is the durable authorization evidence"
)

#: An ordinary CLAIM row. Citing it is the "points at a non-consent row" case.
CLAIM_ROW = (
    "2026-09-05T11:00:00Z | CLAIM | lane=fixture-lane | ticket=OMN-17957 | "
    "APPROVED SCOPE: rotate the Infisical operator-k8s client secret | "
    "OUT OF SCOPE: nothing"
)

#: A consent row whose scope names a different credential entirely.
OTHER_CREDENTIAL_ROW = GOOD_ROW.replace("operator-k8s", "some-other-identity")


@pytest.fixture
def policy() -> Policy:
    return load_policy(POLICY_PATH)


@pytest.fixture
def ledger(tmp_path: Path) -> Path:
    """A fake OMNI_HOME carrying a ledger whose rows are the fixtures above.

    Returns the OMNI_HOME root. Line numbers are 1-based and stable:
      1 GOOD_ROW, 2 JAKE_ROW, 3 SELF_APPROVED_ROW, 4 NO_OUT_OF_SCOPE_ROW,
      5 CLAIM_ROW, 6 OTHER_CREDENTIAL_ROW.
    """
    tracking = tmp_path / "docs" / "tracking"
    tracking.mkdir(parents=True)
    (tracking / "ROLLING_WORK_LEDGER.md").write_text(
        "\n".join(
            [
                GOOD_ROW,
                JAKE_ROW,
                SELF_APPROVED_ROW,
                NO_OUT_OF_SCOPE_ROW,
                CLAIM_ROW,
                OTHER_CREDENTIAL_ROW,
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    return tmp_path


def _cite(line: int, path: str = "docs/tracking/ROLLING_WORK_LEDGER.md") -> str:
    return f"# ROTATION-CONSENT: {path}:{line}"


def codes(findings: list[Finding]) -> set[str]:
    return {f.code for f in findings}


# --------------------------------------------------------------------------
# Every rotation shape from the OMN-17957 30-day sweep is refused bare
# --------------------------------------------------------------------------

#: (id, command). Each names the credential `operator-k8s` wherever the shape
#: has somewhere to name one, so the same command can be re-used verbatim in
#: the ALLOW cases below against a consent row scoped to that credential.
ROTATION_SHAPES: list[tuple[str, str]] = [
    (
        "infisical_rest_delete",
        "curl -sS -X DELETE "
        "'https://infisical.example/api/v3/secrets/raw/operator-k8s"
        "?secretPath=/dev/onex-runtime'",
    ),
    (
        "infisical_rest_patch",
        "curl -sS -X PATCH "
        "'https://infisical.example/api/v3/secrets/raw/operator-k8s' "
        '-d \'{"secretValue":"x"}\'',
    ),
    (
        "infisical_cli_secret_create",
        "infisical identity universal-auth client-secret create "
        "--identity operator-k8s",
    ),
    (
        "infisical_cli_secret_revoke",
        "infisical identity universal-auth client-secret revoke "
        "--identity operator-k8s --client-secret-id abc",
    ),
    (
        "kubectl_create_secret",
        "kubectl -n onex-dev create secret generic operator-k8s "
        "--from-literal=clientSecret=x --dry-run=client -o yaml",
    ),
    (
        "kubectl_delete_secret",
        "kubectl -n onex-dev delete secret operator-k8s",
    ),
    (
        "aws_secretsmanager_put",
        "aws secretsmanager put-secret-value --secret-id operator-k8s "
        "--secret-string x",
    ),
    (
        "aws_secretsmanager_rotate",
        "aws secretsmanager rotate-secret --secret-id operator-k8s",
    ),
    (
        "aws_secretsmanager_update",
        "aws secretsmanager update-secret --secret-id operator-k8s --secret-string x",
    ),
    (
        "aws_iam_create_access_key",
        "aws iam create-access-key --user-name operator-k8s",
    ),
    (
        "aws_iam_delete_access_key",
        "aws iam delete-access-key --user-name operator-k8s --access-key-id AK",
    ),
    (
        "gh_secret_set",
        "gh secret set operator-k8s --repo OmniNode-ai/omniclaude --body x",
    ),
    (
        "gh_secret_delete",
        "gh secret delete operator-k8s --repo OmniNode-ai/omniclaude",
    ),
    (
        "kcadm_client_secret",
        "kcadm.sh create clients/operator-k8s/client-secret -r onex",
    ),
    (
        "psql_alter_role_password",
        "psql -c \"ALTER ROLE operator-k8s WITH PASSWORD 'x'\"",
    ),
]


@pytest.mark.parametrize(
    ("shape_id", "command"), ROTATION_SHAPES, ids=[s for s, _ in ROTATION_SHAPES]
)
def test_rotation_shape_is_refused_without_consent(
    shape_id: str, command: str, policy: Policy, ledger: Path
) -> None:
    findings = check_bash_command(command, policy, ledger)
    assert findings, f"{shape_id} must be refused with no consent citation"
    assert "rotation_without_consent" in codes(findings)


@pytest.mark.parametrize(
    ("shape_id", "command"), ROTATION_SHAPES, ids=[s for s, _ in ROTATION_SHAPES]
)
def test_rotation_shape_is_allowed_with_valid_consent(
    shape_id: str, command: str, policy: Policy, ledger: Path
) -> None:
    findings = check_bash_command(f"{command} {_cite(1)}", policy, ledger)
    assert findings == [], f"{shape_id} with a valid consent row must pass: {findings}"


def test_every_configured_shape_has_a_test(policy: Policy) -> None:
    """The config cannot grow a shape that no test exercises.

    A shape added to the policy with no case here is a rule nobody has ever
    seen fire, which is how a gate ends up reporting green while enforcing
    nothing.
    """
    tested = {shape_id for shape_id, _ in ROTATION_SHAPES}
    configured = {shape.id for shape in policy.rotation_shapes}
    assert configured == tested, (
        "every rotation shape in credential_rotation_policy.json must have a "
        f"case in ROTATION_SHAPES. Untested: {sorted(configured - tested)!r}; "
        f"tested but not configured: {sorted(tested - configured)!r}"
    )


# --------------------------------------------------------------------------
# The consent citation itself
# --------------------------------------------------------------------------


def test_jake_is_an_approver(policy: Policy, ledger: Path) -> None:
    command = "aws secretsmanager rotate-secret --secret-id operator-k8s"
    assert check_bash_command(f"{command} {_cite(2)}", policy, ledger) == []


def test_lane_self_approval_is_refused(policy: Policy, ledger: Path) -> None:
    command = "aws secretsmanager rotate-secret --secret-id operator-k8s"
    findings = check_bash_command(f"{command} {_cite(3)}", policy, ledger)
    assert "consent_approver_not_authorized" in codes(findings)


def test_row_without_out_of_scope_is_refused(policy: Policy, ledger: Path) -> None:
    command = "aws secretsmanager rotate-secret --secret-id operator-k8s"
    findings = check_bash_command(f"{command} {_cite(4)}", policy, ledger)
    assert "consent_missing_scope_list" in codes(findings)


def test_citation_pointing_at_a_non_consent_row_is_refused(
    policy: Policy, ledger: Path
) -> None:
    """A CLAIM row carrying both scope lists is still not consent."""
    command = "aws secretsmanager rotate-secret --secret-id operator-k8s"
    findings = check_bash_command(f"{command} {_cite(5)}", policy, ledger)
    assert "consent_row_not_operator_consent" in codes(findings)


def test_scope_naming_a_different_credential_is_refused(
    policy: Policy, ledger: Path
) -> None:
    command = "aws secretsmanager rotate-secret --secret-id operator-k8s"
    findings = check_bash_command(f"{command} {_cite(6)}", policy, ledger)
    assert "consent_scope_omits_credential" in codes(findings)


def test_citation_past_end_of_ledger_is_refused(policy: Policy, ledger: Path) -> None:
    command = "aws secretsmanager rotate-secret --secret-id operator-k8s"
    findings = check_bash_command(f"{command} {_cite(9999)}", policy, ledger)
    assert "consent_line_absent" in codes(findings)


def test_citation_to_a_non_canonical_path_is_refused(
    policy: Policy, ledger: Path
) -> None:
    """The consent row must live in the one append-only coordination surface.

    A lane that may cite any file it can write has not been gated at all.
    """
    (ledger / "scratch.md").write_text(GOOD_ROW + "\n", encoding="utf-8")
    command = "aws secretsmanager rotate-secret --secret-id operator-k8s"
    findings = check_bash_command(f"{command} {_cite(1, 'scratch.md')}", policy, ledger)
    assert "consent_path_not_canonical" in codes(findings)


def test_citation_escaping_omni_home_is_refused(policy: Policy, ledger: Path) -> None:
    command = "aws secretsmanager rotate-secret --secret-id operator-k8s"
    findings = check_bash_command(
        f"{command} {_cite(1, '../../etc/docs/tracking/ROLLING_WORK_LEDGER.md')}",
        policy,
        ledger,
    )
    assert "consent_path_not_canonical" in codes(findings)


def test_malformed_citation_is_refused(policy: Policy, ledger: Path) -> None:
    command = (
        "aws secretsmanager rotate-secret --secret-id operator-k8s "
        "# ROTATION-CONSENT: docs/tracking/ROLLING_WORK_LEDGER.md"
    )
    findings = check_bash_command(command, policy, ledger)
    assert "rotation_without_consent" in codes(findings)


def test_unresolvable_omni_home_is_refused(policy: Policy, tmp_path: Path) -> None:
    command = f"aws secretsmanager rotate-secret --secret-id operator-k8s {_cite(1)}"
    findings = check_bash_command(command, policy, tmp_path / "absent")
    assert "consent_ledger_unreadable" in codes(findings)


def test_consent_does_not_license_a_second_unscoped_credential(
    policy: Policy, ledger: Path
) -> None:
    """One citation authorises the credential its scope names, not the shell."""
    command = (
        "aws secretsmanager rotate-secret --secret-id operator-k8s && "
        "aws secretsmanager rotate-secret --secret-id unrelated-identity "
        f"{_cite(1)}"
    )
    findings = check_bash_command(command, policy, ledger)
    assert "consent_scope_omits_credential" in codes(findings)


# --------------------------------------------------------------------------
# Reads and the remedy are never gated
# --------------------------------------------------------------------------

READ_ONLY_COMMANDS = [
    "kubectl -n onex-dev get secret operator-k8s -o name",
    "kubectl -n onex-dev describe secret operator-k8s",
    "kubectl -n onex-dev get secrets",
    "aws secretsmanager get-secret-value --secret-id operator-k8s",
    "aws secretsmanager describe-secret --secret-id operator-k8s",
    "aws secretsmanager list-secrets",
    "aws iam list-access-keys --user-name operator-k8s",
    "gh secret list --repo OmniNode-ai/omniclaude",
    "kcadm.sh get clients -r onex",
    "curl -sS 'https://infisical.example/api/v3/secrets/raw/operator-k8s'",
    "psql -c 'SELECT rolname FROM pg_roles'",
    # The consumer-restart half of the remedy. Refusing it would make the
    # correct repair harder than the mistake, which is how a gate gets routed
    # around.
    "kubectl -n infisical-operator-system rollout restart "
    "deployment/secrets-operato-controller-manager",
    "kubectl -n onex-dev rollout restart deployment/omninode-runtime",
    # Ordinary traffic that merely mentions the vocabulary.
    "echo 'aws secretsmanager rotate-secret --secret-id operator-k8s'",
    "grep -rn 'create-access-key' docs/",
    "git commit -m 'docs: describe the rotate-secret path'",
]


@pytest.mark.parametrize("command", READ_ONLY_COMMANDS)
def test_read_only_and_remedy_commands_are_never_gated(
    command: str, policy: Policy, ledger: Path
) -> None:
    assert check_bash_command(command, policy, ledger) == [], command


# --------------------------------------------------------------------------
# Fail-closed on malformed input
# --------------------------------------------------------------------------


def test_unquotable_command_carrying_rotation_vocabulary_is_refused(
    policy: Policy, ledger: Path
) -> None:
    """An unbalanced quote is a command the guard cannot tokenise.

    It carries the vocabulary, so it is refused rather than assumed clean.
    """
    findings = check_bash_command(
        "aws secretsmanager rotate-secret --secret-id 'operator-k8s",
        policy,
        ledger,
    )
    assert "unevaluable" in codes(findings)


def test_non_string_command_is_refused(policy: Policy, ledger: Path) -> None:
    findings = check_bash_command(None, policy, ledger)  # type: ignore[arg-type]
    assert "unevaluable" in codes(findings)


def test_rotation_with_no_nameable_credential_is_refused(
    policy: Policy, ledger: Path
) -> None:
    """A shape whose credential cannot be read cannot be scope-checked."""
    findings = check_bash_command(
        f"aws secretsmanager rotate-secret {_cite(1)}", policy, ledger
    )
    assert "credential_unnamed" in codes(findings)


# --------------------------------------------------------------------------
# Policy loading
# --------------------------------------------------------------------------


def test_shipped_policy_names_exactly_two_approvers(policy: Policy) -> None:
    assert policy.approvers == frozenset({"operator", "jake"})


def test_policy_has_no_escape_entry() -> None:
    raw = json.loads(POLICY_PATH.read_text(encoding="utf-8"))
    flat = json.dumps({k: v for k, v in raw.items() if not k.startswith("$")}).lower()
    for escape in ("wildcard", '"any"', "exempt", "allow_all", "bypass"):
        assert escape not in flat, (
            f"credential_rotation_policy.json must carry no escape entry; "
            f"found {escape!r}"
        )


def test_malformed_policy_raises_rather_than_defaulting(tmp_path: Path) -> None:
    bad = tmp_path / "policy.json"
    bad.write_text("{ not json", encoding="utf-8")
    with pytest.raises(PolicyError):
        load_policy(bad)


def test_policy_missing_approvers_raises(tmp_path: Path) -> None:
    bad = tmp_path / "policy.json"
    bad.write_text(json.dumps({"rotation_shapes": []}), encoding="utf-8")
    with pytest.raises(PolicyError):
        load_policy(bad)


def test_policy_with_a_third_approver_raises(tmp_path: Path) -> None:
    """Exactly two people may approve. A third is a policy edit, not a config."""
    bad = tmp_path / "policy.json"
    raw = json.loads(POLICY_PATH.read_text(encoding="utf-8"))
    raw["approvers"] = ["operator", "jake", "some-lane"]
    bad.write_text(json.dumps(raw), encoding="utf-8")
    with pytest.raises(PolicyError):
        load_policy(bad)


# --------------------------------------------------------------------------
# The refusal text
# --------------------------------------------------------------------------


def test_refusal_states_the_ruling_and_the_exposure_bar(
    policy: Policy, ledger: Path
) -> None:
    findings = check_bash_command(
        "aws secretsmanager rotate-secret --secret-id operator-k8s", policy, ledger
    )
    reason = render_block_reason(findings, policy)
    lowered = reason.lower()
    assert "transcript" in lowered
    assert "is not exposure" in lowered
    assert "pushed to a remote" in lowered
    assert "operator" in lowered and "jake" in lowered
    assert CONSENT_CITATION_GRAMMAR in reason
    assert GATE_BIT_NAME in reason
    assert "no agent, lane or codex message is approval" in lowered


# --------------------------------------------------------------------------
# End to end, through the registered hook script
# --------------------------------------------------------------------------


def _run_hook(
    payload: dict[str, object], env: dict[str, str]
) -> subprocess.CompletedProcess[str]:
    base = {
        "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
        "HOME": os.environ.get("HOME", "/tmp"),
    }
    base.update(env)
    return subprocess.run(
        ["bash", str(HOOK_SCRIPT)],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        env=base,
        timeout=120,
        check=False,
    )


def test_hook_script_blocks_a_bare_rotation(tmp_path: Path, ledger: Path) -> None:
    result = _run_hook(
        {
            "tool_name": "Bash",
            "tool_input": {
                "command": ("aws secretsmanager rotate-secret --secret-id operator-k8s")
            },
        },
        {
            "OMNI_HOME": str(ledger),
            "CLAUDE_PROJECT_DIR": str(REPO_ROOT),
            "ONEX_HOOK_LOG": str(tmp_path / "hooks.log"),
        },
    )
    assert result.returncode == 2, result.stdout + result.stderr
    payload = json.loads(result.stdout)
    assert payload["decision"] == "block"
    assert "ROTATION-CONSENT" in payload["reason"]


def test_hook_script_allows_a_cited_rotation(tmp_path: Path, ledger: Path) -> None:
    result = _run_hook(
        {
            "tool_name": "Bash",
            "tool_input": {
                "command": (
                    "aws secretsmanager rotate-secret --secret-id operator-k8s "
                    "# ROTATION-CONSENT: docs/tracking/ROLLING_WORK_LEDGER.md:1"
                )
            },
        },
        {
            "OMNI_HOME": str(ledger),
            "CLAUDE_PROJECT_DIR": str(REPO_ROOT),
            "ONEX_HOOK_LOG": str(tmp_path / "hooks.log"),
        },
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_hook_script_passes_unrelated_traffic(tmp_path: Path, ledger: Path) -> None:
    result = _run_hook(
        {"tool_name": "Bash", "tool_input": {"command": "ls -la"}},
        {
            "OMNI_HOME": str(ledger),
            "CLAUDE_PROJECT_DIR": str(REPO_ROOT),
            "ONEX_HOOK_LOG": str(tmp_path / "hooks.log"),
        },
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_hook_script_refuses_malformed_json_carrying_the_vocabulary(
    tmp_path: Path, ledger: Path
) -> None:
    result = subprocess.run(
        ["bash", str(HOOK_SCRIPT)],
        input='{"tool_name": "Bash", "tool_input": {"command": "aws secretsmanager rotate-secret',
        capture_output=True,
        text=True,
        env={
            "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
            "HOME": os.environ.get("HOME", "/tmp"),
            "OMNI_HOME": str(ledger),
            "CLAUDE_PROJECT_DIR": str(REPO_ROOT),
            "ONEX_HOOK_LOG": str(tmp_path / "hooks.log"),
        },
        timeout=120,
        check=False,
    )
    assert result.returncode == 2, result.stdout + result.stderr


def test_disabled_hook_allows_and_logs(tmp_path: Path, ledger: Path) -> None:
    """A deliberate disable is allowed, and it is LOGGED, never silent.

    The OMN-13244 history is a hook going dark with no repo-visible signal for
    months; a bare `|| exit 0` here would reproduce that one mask edit at a
    time.
    """
    log = tmp_path / "hooks.log"
    result = _run_hook(
        {
            "tool_name": "Bash",
            "tool_input": {
                "command": ("aws secretsmanager rotate-secret --secret-id operator-k8s")
            },
        },
        {
            "OMNI_HOME": str(ledger),
            "CLAUDE_PROJECT_DIR": str(REPO_ROOT),
            "ONEX_HOOK_LOG": str(log),
            "ONEX_HOOKS_MASK": "0x0",
        },
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert log.exists(), "a disabled run must leave a log line"
    text = log.read_text(encoding="utf-8")
    assert "DISABLED" in text
    assert GATE_BIT_NAME in text


def test_hook_script_logs_a_refusal(tmp_path: Path, ledger: Path) -> None:
    log = tmp_path / "hooks.log"
    _run_hook(
        {
            "tool_name": "Bash",
            "tool_input": {
                "command": "gh secret delete operator-k8s --repo OmniNode-ai/omniclaude"
            },
        },
        {
            "OMNI_HOME": str(ledger),
            "CLAUDE_PROJECT_DIR": str(REPO_ROOT),
            "ONEX_HOOK_LOG": str(log),
        },
    )
    assert "BLOCKED" in log.read_text(encoding="utf-8")


# --------------------------------------------------------------------------
# Registration
# --------------------------------------------------------------------------


def test_hook_is_registered_on_the_bash_matcher() -> None:
    hooks = json.loads(
        (REPO_ROOT / "plugins" / "onex" / "hooks" / "hooks.json").read_text(
            encoding="utf-8"
        )
    )["hooks"]["PreToolUse"]
    bash_groups = [g for g in hooks if g.get("matcher") == "Bash"]
    assert bash_groups, "the guard must be registered on the Bash matcher"
    commands = [h.get("command", "") for h in bash_groups[0]["hooks"]]
    assert any(
        c.endswith("pre_tool_use_credential_rotation_guard.sh") for c in commands
    ), commands


def test_borrowed_bit_namesake_stays_unregistered() -> None:
    """The borrow is only safe while the namesake is not itself registered.

    Re-registering pre_tool_use_authorization_shim.sh would silently put two
    controls behind one mask bit. That turns this suite red instead.
    """
    raw = (REPO_ROOT / "plugins" / "onex" / "hooks" / "hooks.json").read_text(
        encoding="utf-8"
    )
    assert "pre_tool_use_authorization_shim.sh" not in raw, (
        "pre_tool_use_authorization_shim.sh is registered again, so "
        f"`onex hooks disable {GATE_BIT_NAME}` would disable two controls. "
        "Give the rotation guard its own bit before re-registering it."
    )


def test_hook_is_declared_in_the_typed_inventory() -> None:
    inventory = (
        REPO_ROOT / "plugins" / "onex" / "hooks" / "contracts" / "hook_inventory.yaml"
    ).read_text(encoding="utf-8")
    assert "pre_tool_use_credential_rotation_guard.sh" in inventory
    assert "OMN-17957" in inventory


def test_hook_is_classified_in_the_distribution_manifest() -> None:
    manifest = (REPO_ROOT / "plugins" / "distribution_manifest.yaml").read_text(
        encoding="utf-8"
    )
    assert "hooks/scripts/pre_tool_use_credential_rotation_guard.sh" in manifest, (
        "the guard must be classified in the distribution manifest"
    )


# --------------------------------------------------------------------------
# OMN-18175: the selection surface is the command and its arguments
# --------------------------------------------------------------------------
#
# A heredoc BODY is data the command writes, not a command the shell runs. Two
# lanes were refused in four days for writing an ordinary file -- one a findings
# document, one a test fixture -- because the body named credential vocabulary
# and an apostrophe in the prose left the whole command untokenisable. The
# refusal itself was correct fail-closed behaviour; the defect is that the
# command was selected for evaluation at all.
#
# Recorded at docs/tracking/ROLLING_WORK_LEDGER.md:8464 and :8479.

#: Occurrence 2's shape: a TERMINAL row written through a heredoc and appended
#: by ledger_lock.py. The body names the guarded vocabulary precisely because
#: an honest closeout row asserts the ABSENCE of an identity-store operation,
#: and it carries the ordinary English apostrophes that broke the tokeniser.
LEDGER_ROW_HEREDOC = (
    "cat > /tmp/row.md <<'ROW'\n"
    "2026-09-11T08:00:00Z | TERMINAL | lane=fixture-lane | the lane's own row: "
    "no identity-store operation of any kind, no secret read or written, no "
    "access-key minted, no kcadm call, and the phase's own probes printed no "
    "protected value.\n"
    "ROW\n"
    "python3 scripts/ledger_lock.py "
    "docs/tracking/ROLLING_WORK_LEDGER.md --append-file /tmp/row.md"
)

#: Occurrence 1's shape: a findings document whose prose describes a stored key
#: reference.
FINDINGS_DOC_HEREDOC = (
    "cat > reports/findings.md <<'MD'\n"
    "The cloud client is blocked. It resolves its client_secret_ref from the "
    "store, so the lane's next step is to re-issue nothing and read the "
    "api-key reference instead.\n"
    "MD"
)

#: Occurrence 2 of the same class from a different direction: source code whose
#: fixtures necessarily name credential fields.
TEST_FIXTURE_HEREDOC = (
    "cat > tests/test_confidential_client.py <<'PY'\n"
    "FIXTURE = {'client_secret_ref': 'x', 'api-key': 'y'}  # don't re-issue\n"
    "PY"
)

#: Every term the shell pre-filter greps for, plus a complete rotation recipe,
#: written into a document. Documenting a rotation is not performing one -- the
#: same rule that lets `echo 'aws secretsmanager rotate-secret'` through.
RUNBOOK_HEREDOC = (
    "cat > runbooks/rotation.md <<'DOC'\n"
    "To rotate: aws secretsmanager rotate-secret --secret-id operator-k8s, then "
    "aws iam create-access-key --user-name operator-k8s, then kcadm.sh update "
    "clients/operator-k8s/client-secret, then in psql ALTER ROLE operator-k8s "
    "PASSWORD 'x' (ALTER USER works too), then gh secret set OPERATOR_K8S, "
    "then kubectl create secret generic operator-k8s. Never use access_key "
    "material from the transcript.\n"
    "DOC"
)

NOT_SELECTED_HEREDOCS = [
    ("ledger_row", LEDGER_ROW_HEREDOC),
    ("findings_doc", FINDINGS_DOC_HEREDOC),
    ("test_fixture", TEST_FIXTURE_HEREDOC),
    ("runbook", RUNBOOK_HEREDOC),
]


@pytest.mark.parametrize(
    ("label", "command"),
    NOT_SELECTED_HEREDOCS,
    ids=[label for label, _ in NOT_SELECTED_HEREDOCS],
)
def test_heredoc_body_is_not_the_selection_surface(
    label: str, command: str, policy: Policy, ledger: Path
) -> None:
    """AC-1. A command whose only guarded vocabulary is in a heredoc body passes.

    Falsified by any finding at all -- an `unevaluable` refusal included, since
    a body that is never evaluated cannot make a command unevaluable.
    """
    assert check_bash_command(command, policy, ledger) == [], label


@pytest.mark.parametrize(
    ("label", "command"),
    NOT_SELECTED_HEREDOCS,
    ids=[label for label, _ in NOT_SELECTED_HEREDOCS],
)
def test_non_selection_of_a_heredoc_body_is_recorded(
    label: str, command: str, policy: Policy, ledger: Path
) -> None:
    """AC-2. The skip is auditable, and it never echoes the body.

    A body can hold a credential value, so the note carries the delimiter, the
    byte count and the program the body was redirected to -- never content.
    """
    decision = evaluate_bash_command(command, policy, ledger)
    assert decision.findings == []
    assert decision.notes, "a dropped heredoc body must be recorded, not silent"
    note = " ".join(decision.notes)
    assert "heredoc" in note.lower()
    for secret_ish in ("operator-k8s", "client_secret_ref", "identity-store"):
        assert secret_ish not in note, (
            f"the non-selection note must not echo body content ({secret_ish!r})"
        )


def test_file_named_by_append_file_is_never_read(
    policy: Policy, ledger: Path, tmp_path: Path
) -> None:
    """AC-1, the other half. The guard opens no file the command names.

    The rotation recipe here is real and on disk. It is not a command this
    session runs, so it is not this session's rotation.
    """
    row = tmp_path / "row.md"
    row.write_text(
        "aws secretsmanager rotate-secret --secret-id operator-k8s\n",
        encoding="utf-8",
    )
    command = (
        "python3 scripts/ledger_lock.py "
        f"docs/tracking/ROLLING_WORK_LEDGER.md --append-file {row}"
    )
    assert check_bash_command(command, policy, ledger) == []


def test_a_single_line_command_is_never_rewritten(policy: Policy) -> None:
    """The stripper can only remove whole lines AFTER the operator's line.

    A heredoc body begins on the next line, so a one-line command has no body
    to remove and its text reaches the tokeniser byte-identical. This is what
    makes the change safe for every shape in ROTATION_SHAPES, all of which are
    written on one line.
    """
    for _, command in ROTATION_SHAPES:
        visible, heredocs = split_heredocs(command)
        assert visible == command, command
        assert heredocs == {}, command


def test_here_string_is_not_a_heredoc(policy: Policy, ledger: Path) -> None:
    """`<<<` feeds an argument, not a body, and stays inside the surface."""
    command = "psql -h h <<< \"ALTER ROLE operator-k8s PASSWORD 'x'\""
    assert "rotation_without_consent" in codes(
        check_bash_command(command, policy, ledger)
    )


# -- AC-3: the refusal path is untouched ----------------------------------


def test_rotation_beside_a_document_heredoc_is_still_refused(
    policy: Policy, ledger: Path
) -> None:
    """The body is dropped; the command it accompanies is not."""
    command = (
        f"{FINDINGS_DOC_HEREDOC}\n"
        "aws secretsmanager rotate-secret --secret-id operator-k8s"
    )
    findings = check_bash_command(command, policy, ledger)
    assert "rotation_without_consent" in codes(findings)
    assert any(f.credential == "operator-k8s" for f in findings)


def test_untokenisable_arguments_are_still_refused_when_a_heredoc_is_present(
    policy: Policy, ledger: Path
) -> None:
    """AC-3. Stripping the body does not rescue an unbalanced quote in the args.

    The apostrophe that matters is the one on the command line.
    """
    command = (
        "cat > /tmp/note.md <<'MD'\nthe lane's own note\nMD\n"
        "aws secretsmanager rotate-secret --secret-id 'operator-k8s"
    )
    assert "unevaluable" in codes(check_bash_command(command, policy, ledger))


EXECUTED_HEREDOCS = [
    (
        "bash",
        "bash <<'SH'\naws secretsmanager rotate-secret --secret-id operator-k8s\nSH",
    ),
    (
        "sh_dash_s",
        "sh -s <<'SH'\ngh secret delete operator-k8s --repo OmniNode-ai/omniclaude\nSH",
    ),
    (
        "ssh",
        "ssh host <<'SH'\nkubectl -n onex-dev delete secret operator-k8s\nSH",
    ),
]


@pytest.mark.parametrize(
    ("label", "command"),
    EXECUTED_HEREDOCS,
    ids=[label for label, _ in EXECUTED_HEREDOCS],
)
def test_rotation_inside_an_executed_heredoc_is_refused(
    label: str, command: str, policy: Policy, ledger: Path
) -> None:
    """AC-3. A body fed to an interpreter IS a command, so it stays in scope.

    This is the half that must not be lost when bodies stop being tokenised
    with the command line: `cat` writes its body to a file, `bash` and `ssh`
    run it.
    """
    assert "rotation_without_consent" in codes(
        check_bash_command(command, policy, ledger)
    ), label


def test_untokenisable_executed_heredoc_body_is_refused(
    policy: Policy, ledger: Path
) -> None:
    """An executed body that cannot be parsed is refused, never assumed clean."""
    command = (
        "bash <<'SH'\naws secretsmanager rotate-secret --secret-id 'operator-k8s\nSH"
    )
    assert "unevaluable" in codes(check_bash_command(command, policy, ledger))


def test_sql_in_a_psql_heredoc_is_refused(policy: Policy, ledger: Path) -> None:
    """A body fed to a credential-surface program is that program's argument.

    `psql <<EOF ALTER ROLE ... PASSWORD ... EOF` is the same rotation as
    `psql -c "ALTER ROLE ... PASSWORD ..."` and is refused on the same terms.
    """
    command = "psql -h h -U u <<'SQL'\nALTER ROLE operator-k8s PASSWORD 'new';\nSQL"
    findings = check_bash_command(command, policy, ledger)
    assert "rotation_without_consent" in codes(findings)
    assert any(f.credential == "operator-k8s" for f in findings)


def test_heredoc_marker_is_never_reported_as_the_credential(
    policy: Policy, ledger: Path
) -> None:
    """The placeholder that tracks body ownership must not look like a name."""
    command = (
        "gh secret set operator-k8s --repo OmniNode-ai/omniclaude <<'VAL'\nxx\nVAL"
    )
    findings = check_bash_command(command, policy, ledger)
    assert findings, "gh secret set is still a rotation"
    assert [f.credential for f in findings] == ["operator-k8s"], findings


def test_an_executed_heredoc_rotation_can_be_authorised(
    policy: Policy, ledger: Path
) -> None:
    """The citation is read from the command line and from executed bodies."""
    command = (
        f"bash <<'SH'\naws secretsmanager rotate-secret --secret-id operator-k8s "
        f"{_cite(1)}\nSH"
    )
    assert check_bash_command(command, policy, ledger) == []


def test_citation_hidden_in_a_document_body_does_not_authorise(
    policy: Policy, ledger: Path
) -> None:
    """A citation in dropped text authorises nothing -- it was never read."""
    command = (
        f"cat > /tmp/note.md <<'MD'\n{_cite(1)}\nMD\n"
        "aws secretsmanager rotate-secret --secret-id operator-k8s"
    )
    assert "rotation_without_consent" in codes(
        check_bash_command(command, policy, ledger)
    )


# -- An unquoted newline ends a command -----------------------------------


LATER_LINE_ROTATIONS = [
    (
        "after_an_echo",
        "echo starting\naws secretsmanager rotate-secret --secret-id operator-k8s",
    ),
    (
        "after_a_heredoc",
        f"{TEST_FIXTURE_HEREDOC}\ngh secret delete operator-k8s --repo OmniNode-ai/omniclaude",
    ),
    (
        "after_a_comment",
        "# rotate the pair\nkubectl -n onex-dev delete secret operator-k8s",
    ),
]


@pytest.mark.parametrize(
    ("label", "command"),
    LATER_LINE_ROTATIONS,
    ids=[label for label, _ in LATER_LINE_ROTATIONS],
)
def test_a_rotation_on_a_later_line_is_refused(
    label: str, command: str, policy: Policy, ledger: Path
) -> None:
    """`shlex` reads an unquoted newline as whitespace, not as a separator.

    The shipped guard therefore merged every line of a multi-line command into
    one segment and read its program from line 1, so
    `echo hi\\naws secretsmanager rotate-secret ...` was ADMITTED. Heredocs make
    multi-line commands the normal shape here, so the separator is explicit.
    """
    assert "rotation_without_consent" in codes(
        check_bash_command(command, policy, ledger)
    ), label


def test_a_newline_inside_a_quoted_argument_does_not_split(
    policy: Policy, ledger: Path
) -> None:
    """Falsifier for the rule above: a quoted newline is part of an argument."""
    command = "psql -c \"ALTER ROLE operator-k8s\n  PASSWORD 'new'\""
    findings = check_bash_command(command, policy, ledger)
    assert "rotation_without_consent" in codes(findings)
    assert any(f.credential == "operator-k8s" for f in findings)


def test_a_backslash_continuation_does_not_split(policy: Policy, ledger: Path) -> None:
    """The other falsifier: a continued line is one command, not two.

    Split here and the first segment would be `aws secretsmanager` with no
    mutating subcommand, which matches nothing and would admit the rotation.
    """
    command = "aws secretsmanager \\\n  rotate-secret --secret-id operator-k8s"
    assert "rotation_without_consent" in codes(
        check_bash_command(command, policy, ledger)
    )


# -- AC-5: the vocabulary is not narrowed ---------------------------------


def test_shell_prefilter_vocabulary_is_unchanged() -> None:
    """AC-5. The fix is the matching surface, never the vocabulary.

    A patch that made the heredoc cases pass by deleting a term from the
    pre-filter or the policy would fail this ticket, so both are pinned: the
    terms here, and every shape by test_every_configured_shape_has_a_test.
    """
    script = HOOK_SCRIPT.read_text(encoding="utf-8")
    assert (
        "'secret|access-key|access_key|kcadm|alter[[:space:]]+(role|user)'" in script
    ), "the pre-filter vocabulary must stay as shipped"


def test_policy_still_names_every_shipped_shape(policy: Policy) -> None:
    """AC-5, restated as a count so a deletion cannot pass quietly."""
    assert len(policy.rotation_shapes) == 15
    assert policy.approvers == {"operator", "jake"}


# -- End to end, through the registered hook script ------------------------


def test_hook_script_allows_a_document_heredoc_and_logs_the_skip(
    tmp_path: Path, ledger: Path
) -> None:
    """AC-1 and AC-2 at the seam the lanes actually hit."""
    log = tmp_path / "hooks.log"
    result = _run_hook(
        {"tool_name": "Bash", "tool_input": {"command": LEDGER_ROW_HEREDOC}},
        {
            "OMNI_HOME": str(ledger),
            "CLAUDE_PROJECT_DIR": str(REPO_ROOT),
            "ONEX_HOOK_LOG": str(log),
        },
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert log.exists(), "the non-selection must leave a log line"
    text = log.read_text(encoding="utf-8")
    assert "NOT SELECTED" in text, text
    assert "BLOCKED" not in text, text


def test_hook_script_still_blocks_a_rotation_beside_a_heredoc(
    tmp_path: Path, ledger: Path
) -> None:
    log = tmp_path / "hooks.log"
    result = _run_hook(
        {
            "tool_name": "Bash",
            "tool_input": {
                "command": (
                    f"{FINDINGS_DOC_HEREDOC}\n"
                    "aws secretsmanager rotate-secret --secret-id operator-k8s"
                )
            },
        },
        {
            "OMNI_HOME": str(ledger),
            "CLAUDE_PROJECT_DIR": str(REPO_ROOT),
            "ONEX_HOOK_LOG": str(log),
        },
    )
    assert result.returncode == 2, result.stdout + result.stderr
    assert "BLOCKED" in log.read_text(encoding="utf-8")


# --------------------------------------------------------------------------
# The timestamp citation form, which a ledger roll cannot move (OMN-18620)
# --------------------------------------------------------------------------
# A line number is only true until the ledger is next rolled. A cap-crossing
# roll on 2026-09-17 removed 926 lines from the top of the live file, moving the
# operator's qwen hold ruling from :4311 to :3385 and a consent row from :4367
# to :3441. A pending rotation citing either by line would then resolve to a
# DIFFERENT row, and this guard would refuse a legitimate rotation while giving
# a reason that describes the wrong row entirely.
#
# A row timestamp travels with the row, including into the archive when it is
# rolled, so the timestamp form survives any number of rolls.
_UNIQUE_STAMP = "2026-09-06T08:30:00Z"
_UNIQUE_ROW = GOOD_ROW.replace("2026-09-05T12:00:00Z", _UNIQUE_STAMP)

_ROTATE = (
    "infisical identity universal-auth client-secret create --identity operator-k8s"
)


def _stamp_cite(stamp: str, path: str = "docs/tracking/ROLLING_WORK_LEDGER.md") -> str:
    return f"# ROTATION-CONSENT: {path}@{stamp}"


@pytest.fixture
def stamped_home(tmp_path: Path) -> Path:
    """An OMNI_HOME whose ledger carries exactly one uniquely-stamped row."""
    tracking = tmp_path / "docs" / "tracking"
    tracking.mkdir(parents=True)
    (tracking / "ROLLING_WORK_LEDGER.md").write_text(
        "\n".join([CLAIM_ROW, _UNIQUE_ROW]) + "\n", encoding="utf-8"
    )
    return tmp_path


def test_a_timestamp_citation_resolves_the_consent_row(
    policy: Policy, stamped_home: Path
) -> None:
    findings = check_bash_command(
        f"{_ROTATE} {_stamp_cite(_UNIQUE_STAMP)}", policy, stamped_home
    )
    assert findings == [], f"a valid timestamp citation was refused: {findings}"


def test_the_line_form_still_resolves_the_same_row(
    policy: Policy, stamped_home: Path
) -> None:
    """The replacement must not invalidate citations already written.

    Pending rotations in flight cite lines. A change that made the timestamp
    form work by breaking the line form would refuse exactly the authorisations
    it was meant to protect.
    """
    findings = check_bash_command(f"{_ROTATE} {_cite(2)}", policy, stamped_home)
    assert findings == [], f"the line form stopped working: {findings}"


def test_a_timestamp_citation_survives_the_row_being_rolled(
    policy: Policy, stamped_home: Path
) -> None:
    """The property the whole form exists for.

    The row is moved out of the live ledger into the archive, exactly as a
    cap-crossing roll does. Its line number is now meaningless; its timestamp
    is not.
    """
    tracking = stamped_home / "docs" / "tracking"
    archive = tracking / "archive"
    archive.mkdir()
    (archive / "ROLLING_WORK_LEDGER_2026-09-06-split.md").write_text(
        "## Rolled\n\n" + _UNIQUE_ROW + "\n", encoding="utf-8"
    )
    (tracking / "ROLLING_WORK_LEDGER.md").write_text(CLAIM_ROW + "\n", encoding="utf-8")

    findings = check_bash_command(
        f"{_ROTATE} {_stamp_cite(_UNIQUE_STAMP)}", policy, stamped_home
    )

    assert findings == [], (
        f"a rolled consent row stopped authorising its own rotation: {findings}"
    )


def test_an_absent_timestamp_is_refused(policy: Policy, stamped_home: Path) -> None:
    findings = check_bash_command(
        f"{_ROTATE} {_stamp_cite('2026-01-01T00:00:00Z')}", policy, stamped_home
    )
    assert "consent_stamp_absent" in codes(findings)


def test_an_ambiguous_timestamp_is_refused_not_picked(
    policy: Policy, ledger: Path
) -> None:
    """Ambiguity is a refusal, never a choice.

    Two lanes can append inside the same second, so a row timestamp is not
    guaranteed unique -- four rows in the shared fixture share one. Choosing
    among them would mean this guard authorising a rotation against a row
    nobody cited, which is worse than refusing.
    """
    findings = check_bash_command(
        f"{_ROTATE} {_stamp_cite('2026-09-05T12:00:00Z')}", policy, ledger
    )

    assert "consent_stamp_ambiguous" in codes(findings)
    reason = next(f.reason for f in findings if f.code == "consent_stamp_ambiguous")
    # Counted from the fixture, not hard-coded: a constant here would drift the
    # moment a row is added to the shared ledger fixture, and the count is the
    # part of the message that tells the reader how bad the ambiguity is.
    rows = (
        (ledger / "docs" / "tracking" / "ROLLING_WORK_LEDGER.md")
        .read_text(encoding="utf-8")
        .splitlines()
    )
    sharing = sum(
        1 for row in rows if row.split("|", 1)[0].strip() == "2026-09-05T12:00:00Z"
    )
    assert sharing > 1, "the fixture no longer has an ambiguous timestamp"
    assert f"{sharing} rows" in reason, reason


def test_a_timestamp_quoted_inside_a_row_body_does_not_resolve(
    policy: Policy, tmp_path: Path
) -> None:
    """Matched on the row's FIRST field, not anywhere in the line.

    Rows routinely quote other rows' timestamps -- every citation in this fleet
    does. Matching those would resolve a citation to a row that merely mentions
    the one meant, which is the same class of wrongness as the line shift but
    harder to notice.
    """
    tracking = tmp_path / "docs" / "tracking"
    tracking.mkdir(parents=True)
    mentioning = CLAIM_ROW + f" | see {_UNIQUE_STAMP} for the consent"
    (tracking / "ROLLING_WORK_LEDGER.md").write_text(
        mentioning + "\n", encoding="utf-8"
    )

    findings = check_bash_command(
        f"{_ROTATE} {_stamp_cite(_UNIQUE_STAMP)}", policy, tmp_path
    )

    assert "consent_stamp_absent" in codes(findings), (
        f"a row that merely mentions the timestamp resolved the citation: {findings}"
    )


def test_a_non_consent_row_cited_by_timestamp_is_still_refused(
    policy: Policy, stamped_home: Path
) -> None:
    """Control: the new form must not skip the checks the line form runs.

    Resolving a row is only the first half; it still has to BE a consent row
    with both scope lists and one of the two approvers. A form that resolved
    rows but bypassed those would be an authorisation bypass, not a fix.
    """
    findings = check_bash_command(
        f"{_ROTATE} {_stamp_cite('2026-09-05T11:00:00Z')}", policy, stamped_home
    )

    assert findings, "citing a CLAIM row by timestamp was allowed"
    assert "consent_row_not_operator_consent" in codes(findings)


def test_an_archive_file_outside_the_roll_naming_shape_is_not_read(
    policy: Policy, stamped_home: Path
) -> None:
    """The archive search is scoped to the names a roll actually writes.

    A bare ``*.md`` glob would read every markdown file in the archive
    directory, so anything that could land a file there -- a stray doc, a
    partial write, a crafted name -- could carry a row with the target timestamp
    and the required fields and authorise a rotation nobody consented to. This
    plants exactly such a file under a name no roll produces and asserts the
    guard does not see it.
    """
    tracking = stamped_home / "docs" / "tracking"
    archive = tracking / "archive"
    archive.mkdir()
    (archive / "notes.md").write_text(_UNIQUE_ROW + "\n", encoding="utf-8")
    (tracking / "ROLLING_WORK_LEDGER.md").write_text(CLAIM_ROW + "\n", encoding="utf-8")

    findings = check_bash_command(
        f"{_ROTATE} {_stamp_cite(_UNIQUE_STAMP)}", policy, stamped_home
    )

    assert "consent_stamp_absent" in codes(findings), (
        f"a consent row planted under a name no roll writes was accepted: {findings}"
    )


def test_a_conforming_archive_name_is_still_read(
    policy: Policy, stamped_home: Path
) -> None:
    """Positive control for the scoping above.

    Without it, narrowing the glob to something that matches nothing would
    satisfy the test above while silently retiring archive resolution -- which
    is the one behaviour the timestamp form exists to provide.
    """
    tracking = stamped_home / "docs" / "tracking"
    archive = tracking / "archive"
    archive.mkdir()
    (archive / "ROLLING_WORK_LEDGER_2026-09-06-split.md").write_text(
        _UNIQUE_ROW + "\n", encoding="utf-8"
    )
    (tracking / "ROLLING_WORK_LEDGER.md").write_text(CLAIM_ROW + "\n", encoding="utf-8")

    findings = check_bash_command(
        f"{_ROTATE} {_stamp_cite(_UNIQUE_STAMP)}", policy, stamped_home
    )

    assert findings == [], f"archive resolution stopped working entirely: {findings}"


def test_a_symlinked_archive_entry_is_not_read(
    policy: Policy, stamped_home: Path, tmp_path: Path
) -> None:
    """The glob restricts the NAME; this restricts the inode.

    A symlink called ``<ledger stem>_<date>-split.md`` matches the pattern, and
    ``read_text`` follows symlinks, so without the check a link planted in the
    archive directory could point at any file on the host and answer a citation
    with whatever that file contains. The name is attacker-choosable; the target
    must not be.
    """
    tracking = stamped_home / "docs" / "tracking"
    archive = tracking / "archive"
    archive.mkdir()
    elsewhere = tmp_path / "planted.md"
    elsewhere.write_text(_UNIQUE_ROW + "\n", encoding="utf-8")
    (archive / "ROLLING_WORK_LEDGER_2026-09-06-split.md").symlink_to(elsewhere)
    (tracking / "ROLLING_WORK_LEDGER.md").write_text(CLAIM_ROW + "\n", encoding="utf-8")

    findings = check_bash_command(
        f"{_ROTATE} {_stamp_cite(_UNIQUE_STAMP)}", policy, stamped_home
    )

    assert "consent_stamp_absent" in codes(findings), (
        "a consent row reached through a symlink out of the archive directory "
        f"was accepted: {findings}"
    )


def test_a_symlinked_archive_directory_does_not_defeat_the_check(
    policy: Policy, stamped_home: Path, tmp_path: Path
) -> None:
    """The second half: the directory itself can be the link.

    Checking only the entry would still read a real file sitting in a real
    directory that the archive path merely points at.
    """
    tracking = stamped_home / "docs" / "tracking"
    real_dir = tmp_path / "planted_archive"
    real_dir.mkdir()
    (real_dir / "ROLLING_WORK_LEDGER_2026-09-06-split.md").write_text(
        _UNIQUE_ROW + "\n", encoding="utf-8"
    )
    (tracking / "archive").symlink_to(real_dir, target_is_directory=True)
    (tracking / "ROLLING_WORK_LEDGER.md").write_text(CLAIM_ROW + "\n", encoding="utf-8")

    findings = check_bash_command(
        f"{_ROTATE} {_stamp_cite(_UNIQUE_STAMP)}", policy, stamped_home
    )

    assert "consent_stamp_absent" in codes(findings), (
        f"an archive directory that is a symlink out of the tree was read: {findings}"
    )
