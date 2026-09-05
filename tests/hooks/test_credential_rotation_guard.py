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
    load_policy,
    render_block_reason,
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
