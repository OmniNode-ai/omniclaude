# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Behaviour tests for ``scripts/public_repo_hygiene_gate.py`` (OMN-18014).

An untested gate rots, and a gate that reports green over an unscanned path
is the failure this whole programme exists about. So every rule below is
pinned by a POSITIVE CONTROL: a fixture repository carrying a known
violation, asserted to be reported — never a fixture asserted merely to be
clean, which is the reading that four consecutive false "zero failures"
sweeps produced during the trusted-CI canary.

Every fixture is a throwaway git repository, because the scanned surface is
the TRACKED set (``git ls-files``), not a directory walk and not the ignore
rules. Root cause 4.9: an ignore file neither untracks an existing path nor
stops a forced add — ``omnicursor/.DS_Store`` is committed *and* ignored.

This file deliberately contains literals that the gate itself detects. They
are the corpus; the repository's own hygiene gates carry the annotations that
say so.
"""

from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path
from types import ModuleType

import pytest
from omnibase_core.validators.no_unguarded_git_subprocess import (
    scrub_git_location_env,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
GATE_PATH = REPO_ROOT / "scripts" / "public_repo_hygiene_gate.py"

# Positive-control literals. Each sits alone on its own annotated line so
# `ruff format` cannot reflow it onto a line that has lost its marker.
LAN_LITERAL = "192.168.86.201"  # onex-allow-internal-ip  # public-skill-ok: control
OPERATOR_HOME = (
    "/Users/jonah/Code/omni_home"  # local-path-ok  # public-skill-ok: control
)
INSTANCE_ID = "i-06169517a92b45f86"  # public-skill-ok: control fixture
ROLE_ARN = "arn:aws:iam::123456789012:role/example"  # public-skill-ok: control fixture
PRIVATE_REPO = "omninode_infra"  # public-skill-ok: control fixture
KB_PROSE = "our internal knowledge base"  # public-skill-ok: control fixture
PERSON = "testpersonhandle"  # public-skill-ok: control fixture
TRACKER_URL = "https://linear.app/omninode/issue/OMN-1"  # public-skill-ok: control

# Assembled rather than spelled. These are positive controls for the
# machine-path class, and spelling them would need a `# local-path-ok`
# annotation from the repo's existing local-paths check -- i.e. two more
# self-granted waivers on the pile this lane just filed OMN-18018 about.
MOUNTED_VOLUME_PATH = "/" + "Volumes/EXTERNAL/x"
RFC1918_10 = "10." + "1.2.3"
RFC1918_172 = "172." + "20.0.5"
CGNAT_ADDRESS = "100." + "109.4.5"
TAILNET_FQDN = "host.tail1234" + ".ts" + ".net"
HOST_NICKNAME = "the box." + "201 lane"
LINUX_HOME_PATH = "/" + "home/" + "runner-user/x"


def _load() -> ModuleType:
    spec = importlib.util.spec_from_file_location("prhg", GATE_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["prhg"] = module
    spec.loader.exec_module(module)
    return module


gate = _load()


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

VOCAB = r"""
schema_version: 1
private_repo_names_resolved_at: 2999-01-01T00:00:00Z
private_repo_cache_max_age_days: 3650
private_repo_names:
  - "omninode_infra"
internal_kb_prose:
  - "internal\s+knowledge\s+base"
  - "teammates?\s+have\s+access"
host_nicknames:
  - "(?<!\d)\.(?:200|201)\b"
machine_path_patterns:
  - "omni_worktrees/"
person_names:
  - "testpersonhandle"
tracker_url_patterns:
  - "https?://linear\.app/omninode\b"
sensitive_literal_patterns:
  - "AKIA[0-9A-Z]{16}"
sensitive_literal_exempt_globs:
  - "tests/**/fixtures/**"
"""

MINIMAL_CONFIG = """
mode: enforce
allowed_top_level:
  - "src"
  - "tests"
  - "README.md"
  - ".public-repo-hygiene.yaml"
  - ".public-repo-hygiene-suppressions.yaml"
"""


@pytest.fixture
def vocab(tmp_path: Path) -> Path:
    path = tmp_path / "vocabulary.yaml"
    path.write_text(VOCAB, encoding="utf-8")
    return path


def _make_repo(root: Path, files: dict[str, str], config: str = MINIMAL_CONFIG) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        ["git", "init", "-q"], cwd=root, check=True, env=scrub_git_location_env()
    )
    (root / ".public-repo-hygiene.yaml").write_text(config, encoding="utf-8")
    for rel, content in files.items():
        target = root / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
    subprocess.run(
        ["git", "add", "-A", "-f"],
        cwd=root,
        check=True,
        env=scrub_git_location_env(),
    )
    return root


# The lab vocabulary (OMN-19766). Synthetic lane ids only: a real lab lane id
# spelled in this public file is exactly what the lab-config class refuses.
LAB_VOCAB = """
schema_version: 1
lab_lane_ids:
  - "lane-alpha-lab"
  - "lane-alpha-lab-2"
"""
LAB_LANE = "lane-alpha-lab"


def _lab_vocab_for(vocab_path: Path) -> Path:
    """The lab vocabulary beside ``vocab_path``, written once if absent."""
    path = vocab_path.parent / "lab_vocabulary.yaml"
    if not path.exists():
        path.write_text(LAB_VOCAB, encoding="utf-8")
    return path


def _run(
    root: Path,
    vocab_path: Path,
    mode: str = "enforce",
    *,
    lab_vocab_path: Path | None = None,
    only_classes: frozenset[str] | None = None,
    added=None,
):
    return gate.run(
        root,
        vocab_path,
        mode,
        None,
        lab_vocab_path=lab_vocab_path or _lab_vocab_for(vocab_path),
        only_classes=only_classes,
        added_lines=added,
    )


def _classes(findings) -> set[str]:
    return {f.class_name for f in findings}


# ---------------------------------------------------------------------------
# Layer (a) — the top-level path allowlist
# ---------------------------------------------------------------------------


def test_undeclared_top_level_entry_fails(tmp_path: Path, vocab: Path) -> None:
    """The half that refuses the directory nobody has invented yet."""
    root = _make_repo(tmp_path / "r", {"vendor/thing.txt": "hello\n"})
    code, blocking, _ = _run(root, vocab)
    assert code == 1
    assert "top-level-not-allowed" in _classes(blocking)


def test_declared_top_level_entry_passes(tmp_path: Path, vocab: Path) -> None:
    root = _make_repo(tmp_path / "r", {"src/thing.txt": "hello\n"})
    code, blocking, _ = _run(root, vocab)
    assert code == 0, [f"{f.path}:{f.class_name}" for f in blocking]


def test_missing_repo_config_is_a_refusal_not_a_pass(
    tmp_path: Path, vocab: Path
) -> None:
    """An absent config is not an empty allowlist. Fail closed."""
    root = tmp_path / "r"
    root.mkdir()
    subprocess.run(
        ["git", "init", "-q"], cwd=root, check=True, env=scrub_git_location_env()
    )
    with pytest.raises(gate.ConfigError, match="THE GATE DID NOT RUN"):
        _run(root, vocab)


# ---------------------------------------------------------------------------
# Layer (b) — the path denylist is EXTENSION-AGNOSTIC
#
# Root cause 4.2: kb_doc_gate.py:216 is `path.lower().endswith(".md")`, and
# that one line is why every misplaced artifact in the inventory is a YAML,
# JSON, CSV, TSV, TXT, PNG or SVG. These are the positive controls for the
# extensions the doc gate cannot see.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("rel_path", "expected"),
    [
        (".onex/aislop-rules.yaml", "agent-state"),
        (".onex_state/evidence/report.json", "agent-state"),
        (".claude_scratch/notes.txt", "agent-state"),
        (".repowise-workspace/contracts.json", "agent-state"),
        ("merge-sweep/run.json", "agent-state"),
        ("docs/evidence/OMN-1.json", "evidence-tree"),
        (".evidence/run.csv", "evidence-tree"),
        ("drift/dod_receipts/OMN-1.yaml", "evidence-tree"),
        ("src/nodes/receipts/out.json", "evidence-tree"),
        ("docs/tracking/status.csv", "misplaced-doc"),
        ("docs/handoffs/2026-01-01-x.tsv", "misplaced-doc"),
        ("docs/2026-01-01-deep-dive.txt", "misplaced-doc"),
        ("docs/assets/brand/logo.svg", "brand-asset"),
        ("docs/assets/brand/logo.png", "brand-asset"),
        (".env.local", "env-file"),
        (".DS_Store", "os-junk"),
        ("src/run.log", "cache-or-log"),
        ("src/__pycache__/x.txt", "cache-or-log"),
    ],
)
def test_path_denylist_is_extension_agnostic(
    tmp_path: Path, vocab: Path, rel_path: str, expected: str
) -> None:
    root = _make_repo(tmp_path / "r", {rel_path: "x\n"})
    _, blocking, _ = _run(root, vocab)
    hits = [f for f in blocking if f.path == rel_path]
    assert expected in {f.class_name for f in hits}, (
        f"{rel_path} should be {expected}; got {[f.class_name for f in hits]}"
    )


def test_env_example_is_not_an_env_file_finding(tmp_path: Path, vocab: Path) -> None:
    """The one env file a public repo is supposed to ship."""
    root = _make_repo(
        tmp_path / "r",
        {"src/.env.example": "TOKEN=replace-me\n"},
    )
    _, blocking, _ = _run(root, vocab)
    assert "env-file" not in _classes(blocking)


# ---------------------------------------------------------------------------
# Content classes
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("payload", "expected"),
    [
        (ROLE_ARN, "cloud-identity"),
        (INSTANCE_ID, "cloud-identity"),
        ("123456789012.dkr.ecr.us-east-2.amazonaws.com/x", "cloud-identity"),
        (LAN_LITERAL, "private-network"),
        (RFC1918_10, "private-network"),
        (RFC1918_172, "private-network"),
        (CGNAT_ADDRESS, "private-network"),
        (TAILNET_FQDN, "private-network"),
        ("ssh user@somebox", "private-network"),
        (HOST_NICKNAME, "private-network"),
        (OPERATOR_HOME, "machine-path"),
        (MOUNTED_VOLUME_PATH, "machine-path"),
        (LINUX_HOME_PATH, "machine-path"),
        (f"see {PRIVATE_REPO} for details", "private-repo-name"),
        (KB_PROSE, "internal-kb-prose"),
        ("teammates have access", "internal-kb-prose"),
        (f"contact {PERSON}", "person-name"),
        (TRACKER_URL, "tracker-url"),
        ("AKIA" + "IOSFODNN7EXAMPLE", "secret-shaped"),
    ],
)
def test_content_classes_fire(
    tmp_path: Path, vocab: Path, payload: str, expected: str
) -> None:
    root = _make_repo(tmp_path / "r", {"src/thing.txt": f"value = {payload}\n"})
    _, blocking, _ = _run(root, vocab)
    assert expected in _classes(blocking), [f.class_name for f in blocking]


def test_bare_ticket_id_is_not_a_violation(tmp_path: Path, vocab: Path) -> None:
    """Operator ruling P3, 2026-09-06, firm.

    Internal ticket ids in public source are an accepted convention, not a
    violation — there are 8,826 in one repo and this programme does not
    propose mass-stripping them. The gate has no bare-ticket-id class at all.
    Workspace-scoped tracker URLs are removed either way, which is what the
    ``tracker-url`` class covers.
    """
    root = _make_repo(tmp_path / "r", {"src/thing.txt": "fixed in OMN-12345\n"})
    code, blocking, _ = _run(root, vocab)
    assert code == 0, [f"{f.path}:{f.class_name}:{f.snippet}" for f in blocking]


def test_rest_url_path_segments_are_not_machine_paths(
    tmp_path: Path, vocab: Path
) -> None:
    """``machine-path`` is NEVER-EXEMPTABLE, so a false positive in it cannot
    be waived — it can only be fixed by rewriting correct product code.

    The macOS home and mounted-volume prefixes are case-SENSITIVE in reality,
    as is the lowercase Linux home prefix. Compiling the whole class with
    IGNORECASE made every lowercase REST path segment bearing those words a
    never-exemptable finding. Measured live 2026-09-07 against the adoption
    branches: 11 such findings across knowledge-base (5), omnidash (4),
    omnibase_spi (1) and RSD (1) — and in RSD that one false positive was
    100% of the repo's residue, i.e. the difference between "can flip to
    enforce" and "can never be green".
    """
    root = _make_repo(
        tmp_path / "r",
        {
            "src/client.py": (
                'get("/api/v1/users/123")\n'
                'post(f"{prefix}/volumes/create")\n'
                'delete("/HOME/legacy/x")\n'
            )
        },
    )
    code, blocking, _ = _run(root, vocab)
    assert "machine-path" not in _classes(blocking), [
        f"{f.path}:{f.snippet}" for f in blocking if f.class_name == "machine-path"
    ]
    assert code == 0, [f"{f.path}:{f.class_name}:{f.snippet}" for f in blocking]


def test_real_machine_path_prefixes_still_fire_after_the_case_fix(
    tmp_path: Path, vocab: Path
) -> None:
    """Positive control for the test above: narrowing the case sensitivity
    must not disarm the class it narrows. A zero is only evidence when the
    same probe returns rows against input known to carry them.
    """
    root = _make_repo(
        tmp_path / "r",
        {
            "src/a.py": f"p = {OPERATOR_HOME!r}\n",
            "src/b.py": f"p = {MOUNTED_VOLUME_PATH!r}\n",
            "src/c.py": f"p = {LINUX_HOME_PATH!r}\n",
        },
    )
    _, blocking, _ = _run(root, vocab)
    hits = {f.path for f in blocking if f.class_name == "machine-path"}
    assert hits == {"src/a.py", "src/b.py", "src/c.py"}, hits


def test_secret_false_positive_glob_suppresses_only_the_secret_class(
    tmp_path: Path, vocab: Path
) -> None:
    """Three repos ship detector baselines and test corpora; without this the
    gate's first run is ~300 phantom criticals, and a gate whose first run is
    300 false positives is a gate nobody reads. It must not suppress anything
    else at the same path.
    """
    root = _make_repo(
        tmp_path / "r",
        {"tests/x/fixtures/corpus.txt": "AKIA" + f"IOSFODNN7EXAMPLE {LAN_LITERAL}\n"},
    )
    _, blocking, _ = _run(root, vocab)
    assert "secret-shaped" not in _classes(blocking)
    assert "private-network" in _classes(blocking)


# ---------------------------------------------------------------------------
# OMN-18017 — a public README may not name a private repository
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("doc", ["README.md", "CONTRIBUTING.md", "SECURITY.md"])
def test_public_doc_naming_a_private_repo_is_its_own_class(
    tmp_path: Path, vocab: Path, doc: str
) -> None:
    """The rule that did not exist anywhere in the org.

    A README naming a private repository is not the same finding as a script
    importing from one, so it is reported as its own never-exemptable class.
    """
    config = MINIMAL_CONFIG.replace('  - "README.md"', f'  - "README.md"\n  - "{doc}"')
    root = _make_repo(
        tmp_path / "r",
        {doc: f"Prose lives in {PRIVATE_REPO}, and teammates have access.\n"},
        config=config,
    )
    _, blocking, _ = _run(root, vocab)
    assert "public-doc-private-repo" in _classes(blocking)


def test_public_doc_naming_only_public_repos_passes(
    tmp_path: Path, vocab: Path
) -> None:
    root = _make_repo(
        tmp_path / "r",
        {"README.md": "Built on omnibase_core and omnibase_spi.\n"},
    )
    code, blocking, _ = _run(root, vocab)
    assert code == 0, [f"{f.path}:{f.class_name}" for f in blocking]


def test_a_script_naming_a_private_repo_is_not_the_public_doc_class(
    tmp_path: Path, vocab: Path
) -> None:
    root = _make_repo(tmp_path / "r", {"src/x.py": f"REPO = '{PRIVATE_REPO}'\n"})
    _, blocking, _ = _run(root, vocab)
    assert "private-repo-name" in _classes(blocking)
    assert "public-doc-private-repo" not in _classes(blocking)


# ---------------------------------------------------------------------------
# OMN-20150 — the upper-case environment variable is not the private slug
# ---------------------------------------------------------------------------

# The variable name is the same word as the private repository's slug, but it
# is an environment variable used across public repositories. The slug stays
# private; the variable does not name it. Assembled so this file spells
# neither form as a literal.
_SLUG = "omni" + "_home"
_ENV_VAR = _SLUG.upper()
_ENV_VAR_VOCAB = VOCAB.replace(PRIVATE_REPO, _SLUG)


@pytest.fixture
def env_var_vocab(tmp_path: Path) -> Path:
    path = tmp_path / "env_var_vocabulary.yaml"
    path.write_text(_ENV_VAR_VOCAB, encoding="utf-8")
    return path


@pytest.mark.parametrize(
    "payload",
    [
        f'cd "${_ENV_VAR}/scripts"',
        f'cd "${{{_ENV_VAR}}}/scripts"',
        f'ROOT="${{{_ENV_VAR}:?set {_ENV_VAR}}}"',
        f"export {_ENV_VAR}=/somewhere",
        f"{_ENV_VAR}=/somewhere ./run.sh",
        f"Set `{_ENV_VAR}` before running.",
        f'os.environ["{_ENV_VAR}"]',
    ],
)
def test_the_upper_case_env_var_is_not_a_private_repo_reference(
    tmp_path: Path, env_var_vocab: Path, payload: str
) -> None:
    root = _make_repo(tmp_path / "r", {"src/x.sh": payload + "\n"})
    code, blocking, _ = _run(root, env_var_vocab)
    assert "private-repo-name" not in _classes(blocking), payload
    assert code == 0, [f"{f.path}:{f.class_name}" for f in blocking]


@pytest.mark.parametrize(
    "payload",
    [
        f"clone {_SLUG} first",
        f"git clone https://github.com/OmniNode-ai/{_SLUG}",
        f"git clone https://github.com/OmniNode-ai/{_ENV_VAR}",
        f"OmniNode-ai/{_SLUG}",
        f"see [the repo](../{_SLUG}/README.md)",
        f"cd ${_ENV_VAR}/{_SLUG}",
        f"the {_SLUG.title()} repository",
        f"{_ENV_VAR}_EXTRA is not the env var either",
    ],
)
def test_the_slug_as_a_repo_name_still_fails(
    tmp_path: Path, env_var_vocab: Path, payload: str
) -> None:
    root = _make_repo(tmp_path / "r", {"src/x.sh": payload + "\n"})
    _, blocking, _ = _run(root, env_var_vocab)
    if "_EXTRA" in payload:
        # An identifier that merely starts with the variable is neither the
        # variable nor the slug, and the boundary lookahead already ignores it.
        assert "private-repo-name" not in _classes(blocking)
    else:
        assert "private-repo-name" in _classes(blocking), payload


def test_the_env_var_does_not_launder_the_slug_on_the_same_line(
    tmp_path: Path, env_var_vocab: Path
) -> None:
    root = _make_repo(
        tmp_path / "r", {"src/x.sh": f"cd ${_ENV_VAR} && git clone {_SLUG}\n"}
    )
    _, blocking, _ = _run(root, env_var_vocab)
    assert "private-repo-name" in _classes(blocking)


def test_a_public_doc_naming_only_the_env_var_is_clean(
    tmp_path: Path, env_var_vocab: Path
) -> None:
    root = _make_repo(tmp_path / "r", {"README.md": f"Export `${_ENV_VAR}` first.\n"})
    code, blocking, _ = _run(root, env_var_vocab)
    assert "public-doc-private-repo" not in _classes(blocking)
    assert code == 0, [f"{f.path}:{f.class_name}" for f in blocking]


# ---------------------------------------------------------------------------
# Mechanism 3 — suppression is two-party, scoped and expiring
# ---------------------------------------------------------------------------

REGISTRY_VALID = """
entries:
  - path_glob: "src/**"
    class: "person-name"
    reason_code: "fixture-identity"
    ticket: "OMN-1234"
    expires_at: "2999-01-01"
    approved_by: "codeowner"
"""

REGISTRY_EXPIRED = REGISTRY_VALID.replace("2999-01-01", "2020-01-01")


def test_annotation_without_a_registry_entry_is_a_failure(
    tmp_path: Path, vocab: Path
) -> None:
    """Root cause 4.3, mechanically closed.

    A self-written annotation is not an approval. It must be LOUDER than
    silence, not quieter — the finding it tried to hide is reported too.
    """
    root = _make_repo(
        tmp_path / "r",
        {
            "src/x.py": f"NAME = '{PERSON}'  # {gate.INLINE_MARKER}: fixture-identity OMN-1234\n"
        },
    )
    code, blocking, _ = _run(root, vocab)
    assert code == 1
    assert "unresolved-suppression" in _classes(blocking)
    assert "person-name" in _classes(blocking)


def test_annotation_with_a_matching_registry_entry_suppresses(
    tmp_path: Path, vocab: Path
) -> None:
    root = _make_repo(
        tmp_path / "r",
        {
            "src/x.py": f"NAME = '{PERSON}'  # {gate.INLINE_MARKER}: fixture-identity OMN-1234\n",
            ".public-repo-hygiene-suppressions.yaml": REGISTRY_VALID,
        },
    )
    code, blocking, _ = _run(root, vocab)
    assert code == 0, [f"{f.path}:{f.class_name}:{f.snippet}" for f in blocking]


def test_expired_registry_entry_stops_suppressing(tmp_path: Path, vocab: Path) -> None:
    """An allowlist granted under one policy must not silently outlive its
    premise — which is exactly what happened to omniintelligence's internal-IP
    waivers when that repository became public.
    """
    root = _make_repo(
        tmp_path / "r",
        {
            "src/x.py": f"NAME = '{PERSON}'  # {gate.INLINE_MARKER}: fixture-identity OMN-1234\n",
            ".public-repo-hygiene-suppressions.yaml": REGISTRY_EXPIRED,
        },
    )
    code, blocking, _ = _run(root, vocab)
    assert code == 1
    problems = [f.snippet for f in blocking if f.class_name == "unresolved-suppression"]
    assert any("expired" in p for p in problems), problems


def test_registry_entry_on_a_never_exemptable_class_is_refused(
    tmp_path: Path, vocab: Path
) -> None:
    """There is no legitimate fixture need for a real cloud identifier that a
    stable synthetic value cannot serve. The registry refuses to hold one.
    """
    registry = REGISTRY_VALID.replace('"person-name"', '"cloud-identity"')
    root = _make_repo(
        tmp_path / "r",
        {"src/x.py": "x = 1\n", ".public-repo-hygiene-suppressions.yaml": registry},
    )
    with pytest.raises(gate.ConfigError, match="NEVER-EXEMPTABLE"):
        _run(root, vocab)


@pytest.mark.parametrize(
    "payload", [ROLE_ARN, LAN_LITERAL, OPERATOR_HOME, PRIVATE_REPO, KB_PROSE]
)
def test_never_exemptable_classes_ignore_the_annotation(
    tmp_path: Path, vocab: Path, payload: str
) -> None:
    root = _make_repo(
        tmp_path / "r",
        {
            "src/x.py": f"V = '{payload}'  # {gate.INLINE_MARKER}: fixture-identity OMN-1234\n"
        },
    )
    code, _, _ = _run(root, vocab)
    assert code == 1


@pytest.mark.parametrize(
    "missing", ["ticket", "expires_at", "approved_by", "reason_code"]
)
def test_registry_entry_missing_a_required_field_is_a_config_error(
    tmp_path: Path, vocab: Path, missing: str
) -> None:
    registry = "\n".join(
        line for line in REGISTRY_VALID.splitlines() if f"{missing}:" not in line
    )
    root = _make_repo(
        tmp_path / "r",
        {"src/x.py": "x = 1\n", ".public-repo-hygiene-suppressions.yaml": registry},
    )
    with pytest.raises(gate.ConfigError, match="missing required"):
        _run(root, vocab)


def test_legacy_self_granted_annotations_are_counted_never_blocking(
    tmp_path: Path, vocab: Path
) -> None:
    """OMN-18018 is the migration. This gate reports the count and does not
    perform it: a lane that builds the registry and fills it in the same
    change has self-granted every entry a second time.
    """
    marker = "# onex-" + "allow-internal-ip"
    root = _make_repo(tmp_path / "r", {"src/x.py": f"HOST = 'placeholder'  {marker}\n"})
    code, blocking, info = _run(root, vocab)
    assert code == 0, [f.class_name for f in blocking]
    assert [f.class_name for f in info] == ["self-granted-annotation"]


# ---------------------------------------------------------------------------
# Fail-closed
# ---------------------------------------------------------------------------


def test_missing_vocabulary_is_a_refusal_not_a_pass(tmp_path: Path) -> None:
    """A gate that cannot read its own denylist has not passed; it has not run.

    This is the failure mode that produced four consecutive confident false
    "zero failures" readings during the trusted-CI canary: a sweep that
    errored and returned no rows reads exactly like a clean bill of health.
    """
    root = _make_repo(tmp_path / "r", {"src/x.py": "x = 1\n"})
    with pytest.raises(gate.ConfigError, match="THE GATE DID NOT RUN"):
        _run(root, tmp_path / "nope.yaml")


def test_unparseable_vocabulary_is_a_refusal(tmp_path: Path) -> None:
    bad = tmp_path / "v.yaml"
    bad.write_text("this line is not the supported subset\n", encoding="utf-8")
    root = _make_repo(tmp_path / "r", {"src/x.py": "x = 1\n"})
    with pytest.raises(gate.ConfigError):
        _run(root, bad)


def test_stale_visibility_cache_is_a_refusal(tmp_path: Path) -> None:
    """A stale private-repo list is the hardcoded-list failure the class
    exists to avoid, and a stale list that still reports green is worse than
    no list at all.
    """
    stale = tmp_path / "v.yaml"
    stale.write_text(
        VOCAB.replace("2999-01-01T00:00:00Z", "2020-01-01T00:00:00Z").replace(
            "private_repo_cache_max_age_days: 3650",
            "private_repo_cache_max_age_days: 30",
        ),
        encoding="utf-8",
    )
    root = _make_repo(tmp_path / "r", {"src/x.py": "x = 1\n"})
    with pytest.raises(gate.ConfigError, match="THE GATE DID NOT RUN"):
        _run(root, stale)


def test_undated_visibility_cache_is_a_refusal(tmp_path: Path) -> None:
    undated = tmp_path / "v.yaml"
    undated.write_text(
        "\n".join(
            line
            for line in VOCAB.splitlines()
            if "private_repo_names_resolved_at" not in line
        ),
        encoding="utf-8",
    )
    root = _make_repo(tmp_path / "r", {"src/x.py": "x = 1\n"})
    with pytest.raises(gate.ConfigError, match="live repository visibility"):
        _run(root, undated)


# ---------------------------------------------------------------------------
# Modes
# ---------------------------------------------------------------------------


def test_report_mode_records_findings_and_exits_zero(
    tmp_path: Path, vocab: Path
) -> None:
    config = MINIMAL_CONFIG.replace("mode: enforce", "mode: report")
    root = _make_repo(tmp_path / "r", {"src/x.py": f"H = '{LAN_LITERAL}'\n"}, config)
    code, blocking, _ = _run(root, vocab, mode="enforce")
    assert code == 0
    assert "private-network" in _classes(blocking)


def test_repo_config_mode_wins_over_the_cli_default(
    tmp_path: Path, vocab: Path
) -> None:
    """Both surfaces are set on purpose so they cannot silently disagree about
    which one is authoritative.
    """
    root = _make_repo(tmp_path / "r", {"src/x.py": f"H = '{LAN_LITERAL}'\n"})
    code, _, _ = _run(root, vocab, mode="report")
    assert code == 1


# ---------------------------------------------------------------------------
# The gate is stdlib-only, by contract
# ---------------------------------------------------------------------------


def test_gate_imports_no_third_party_module() -> None:
    """The structural precedent is RSD's validate_public_release.py: a gate
    that needs a dependency install to run is a gate that does not run in the
    window where it matters. Pinned as a test so the constraint survives the
    next convenience import.
    """
    import ast

    tree = ast.parse(GATE_PATH.read_text(encoding="utf-8"))
    stdlib = set(sys.stdlib_module_names)
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(a.name.split(".")[0] for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            imported.add(node.module.split(".")[0])
    assert imported <= stdlib, sorted(imported - stdlib)


def test_the_repo_declares_its_own_top_level_allowlist() -> None:
    """This repo runs the gate it ships. A config that drifted from the tree
    would make omniclaude the one repo the gate cannot govern.
    """
    config = gate.load_repo_config(REPO_ROOT / gate.CONFIG_BASENAME)
    assert config.mode in gate.MODES
    assert len(config.allowed_top_level) > 10


def test_misspelled_vocabulary_key_is_a_refusal(tmp_path: Path) -> None:
    """A fail-open hole this lane hit for real, now closed.

    The loader used to look up the key it expected, find nothing, and build a
    pattern that matches nothing — so renaming a class in the vocabulary
    without renaming it in the loader turned that class OFF and every test
    stayed green, because the fixtures carry their own vocabulary. The
    production run's own finding count was the only thing that caught it.
    """
    bad = tmp_path / "v.yaml"
    bad.write_text(VOCAB.replace("person_names:", "persn_names:"), encoding="utf-8")
    root = _make_repo(tmp_path / "r", {"src/x.py": "x = 1\n"})
    with pytest.raises(gate.ConfigError, match="unknown vocabulary key"):
        _run(root, bad)


def test_vocabulary_missing_a_required_class_is_a_refusal(tmp_path: Path) -> None:
    lines = VOCAB.splitlines()
    idx = lines.index("person_names:")
    trimmed = "\n".join(lines[:idx] + lines[idx + 2 :])
    bad = tmp_path / "v.yaml"
    bad.write_text(trimmed, encoding="utf-8")
    root = _make_repo(tmp_path / "r", {"src/x.py": "x = 1\n"})
    with pytest.raises(gate.ConfigError, match="missing required vocabulary"):
        _run(root, bad)


@pytest.mark.unit
def test_a_yaml_document_start_marker_is_not_a_parse_error() -> None:
    """`---` and `...` are document markers, not content. OMN-18016.

    Several repositories run a `yamlfmt` pre-commit hook that PREPENDS `---`
    to every YAML file it touches. The adoption script writes a config without
    one; the hook adds it on the very first commit; the gate then died with
    `unrecognized top-level line: '---'` and exit 2 -- which surfaces as a red
    check that reads like a verdict and is actually "the gate did not run".

    Measured on omnimemory, omniintelligence, omnibase_compat and omnidash: in
    each the adoption commit was rewritten by that hook and every one of those
    four gate runs failed this way, while omnibase_spi (no such hook) passed.

    A gate that cannot be adopted in a repo that formats its YAML is not a
    gate. Both markers are skipped, exactly like a blank line or a comment --
    and nothing else about the fail-closed posture changes: an unparseable
    line is still exit 2.
    """
    parsed = gate.parse_restricted_yaml(
        '---\nmode: report\nallowed_top_level:\n  - "README.md"\n...\n',
        "fixture.yaml",
    )

    assert parsed["mode"] == "report"
    assert parsed["allowed_top_level"] == ["README.md"]


@pytest.mark.unit
def test_a_genuinely_unparseable_line_is_still_a_hard_error() -> None:
    """Positive control for the skip above.

    Skipping `---` must not become skipping anything the parser dislikes. If
    this assertion ever stops holding, the fail-closed parser has become a
    fail-open one and the previous test is what let it happen.
    """
    with pytest.raises(gate.ConfigError):
        gate.parse_restricted_yaml("mode: report\n@ not yaml at all\n", "fixture.yaml")


# ---------------------------------------------------------------------------
# Lab configuration (OMN-19766): the lab-config class, per-class enforcement
# and --only-classes
#
# RULING 2026-09-26T15:24:56Z: no lab configuration of any kind in a public
# repository. A repository reaching zero for the lab classes turns them on in
# its own config (`enforce_classes`) while its other classes may still be red,
# which a single `mode:` switch could not express.
# ---------------------------------------------------------------------------

LAB_CONFIG = MINIMAL_CONFIG.replace("mode: enforce", "mode: report") + (
    'enforce_classes:\n  - "private-network"\n  - "lab-config"\n'
)


def test_lab_lane_id_is_the_lab_config_class(tmp_path: Path, vocab: Path) -> None:
    root = _make_repo(tmp_path / "r", {"src/x.txt": f"lane = {LAB_LANE}\n"})
    _, blocking, _ = _run(root, vocab)
    assert "lab-config" in _classes(blocking)
    assert "lab-config" in gate.NEVER_EXEMPTABLE


@pytest.mark.parametrize(
    ("payload", "hit"),
    [
        (f"project {LAB_LANE}-runtime", True),  # a compound name carries it
        (f"ONEX_RUNTIME_LANE={LAB_LANE.upper()}", True),  # case-insensitive
        (f"x{LAB_LANE}", False),  # not a whole token
        (f"{LAB_LANE}_suffix", False),
        ("lane-alpha", False),  # a prefix of an id is not the id
    ],
)
def test_lab_lane_id_matches_as_a_whole_token(
    tmp_path: Path, vocab: Path, payload: str, hit: bool
) -> None:
    root = _make_repo(tmp_path / "r", {"src/x.txt": payload + "\n"})
    _, blocking, _ = _run(root, vocab)
    assert ("lab-config" in _classes(blocking)) is hit


def test_enforce_classes_fail_the_run_in_report_mode(
    tmp_path: Path, vocab: Path
) -> None:
    """Positive control: a lab address and a lab lane id are both refused."""
    root = _make_repo(
        tmp_path / "r",
        {
            "src/address.py": f"H = '{LAN_LITERAL}'\n",
            "src/lane.py": f"L = '{LAB_LANE}'\n",
        },
        LAB_CONFIG,
    )
    code, blocking, _ = _run(root, vocab, mode="report")
    assert code == 1
    failing = {(f.path, f.class_name) for f in blocking}
    assert ("src/address.py", "private-network") in failing
    assert ("src/lane.py", "lab-config") in failing


def test_enforce_classes_pass_a_clean_repository(tmp_path: Path, vocab: Path) -> None:
    """Negative control: the same config over a clean file exits 0."""
    root = _make_repo(tmp_path / "r", {"src/x.py": "x = 1\n"}, LAB_CONFIG)
    code, blocking, _ = _run(root, vocab, mode="report")
    assert code == 0, [f"{f.path}:{f.class_name}" for f in blocking]


def test_classes_outside_enforce_classes_stay_report_only(
    tmp_path: Path, vocab: Path
) -> None:
    """Enforcing the lab classes does not flip the repository's other classes."""
    root = _make_repo(
        tmp_path / "r",
        {"src/x.txt": f"contact {PERSON}\n", "vendor/y.txt": "x\n"},
        LAB_CONFIG,
    )
    code, blocking, _ = _run(root, vocab, mode="report")
    assert code == 0
    assert {"person-name", "top-level-not-allowed"} <= _classes(blocking)


def test_an_unknown_class_in_enforce_classes_is_a_config_error(
    tmp_path: Path, vocab: Path
) -> None:
    config = MINIMAL_CONFIG + 'enforce_classes:\n  - "lab-confgi"\n'
    root = _make_repo(tmp_path / "r", {"src/x.py": "x = 1\n"}, config)
    with pytest.raises(gate.ConfigError, match="unknown class"):
        _run(root, vocab)


def test_missing_lab_vocabulary_is_a_refusal(tmp_path: Path, vocab: Path) -> None:
    root = _make_repo(tmp_path / "r", {"src/x.py": "x = 1\n"})
    with pytest.raises(gate.ConfigError, match="THE GATE DID NOT RUN"):
        _run(root, vocab, lab_vocab_path=tmp_path / "nope.yaml")


@pytest.mark.parametrize(
    ("body", "match"),
    [
        ("schema_version: 1\n", "missing_lab_lane_ids|lab_lane_ids"),
        ('schema_version: 1\nlab_lane_ids: ""\n', "empty"),
        (LAB_VOCAB + 'lab_lanes:\n  - "x"\n', "unknown lab vocabulary key"),
    ],
)
def test_missing_lab_lane_ids_is_refused_never_scanned(
    tmp_path: Path, vocab: Path, body: str, match: str
) -> None:
    lab = tmp_path / "bad_lab.yaml"
    lab.write_text(body, encoding="utf-8")
    root = _make_repo(tmp_path / "r", {"src/x.txt": f"L = {LAB_LANE}\n"})
    with pytest.raises(gate.ConfigError, match=match):
        _run(root, vocab, lab_vocab_path=lab)


def test_a_registry_entry_cannot_grant_lab_config(tmp_path: Path, vocab: Path) -> None:
    registry = (
        "entries:\n"
        '  - path_glob: "src/**"\n'
        '    class: "lab-config"\n'
        '    reason_code: "fixture"\n'
        '    ticket: "OMN-1"\n'
        '    expires_at: "2999-01-01"\n'
        '    approved_by: "a-reviewer"\n'
    )
    root = _make_repo(
        tmp_path / "r",
        {"src/x.txt": "x\n", ".public-repo-hygiene-suppressions.yaml": registry},
    )
    with pytest.raises(gate.ConfigError, match="NEVER-EXEMPTABLE"):
        _run(root, vocab)


def test_only_classes_restricts_the_scan(tmp_path: Path, vocab: Path) -> None:
    root = _make_repo(
        tmp_path / "r",
        {"src/x.txt": f"contact {PERSON}\n", "vendor/y.txt": "x\n"},
    )
    only = frozenset({"private-network", "lab-config"})
    code, blocking, _ = _run(root, vocab, only_classes=only)
    assert code == 0 and blocking == []
    (root / "src" / "x.txt").write_text(f"L = {LAB_LANE}\n", encoding="utf-8")
    code, blocking, _ = _run(root, vocab, only_classes=only)
    assert code == 1
    assert _classes(blocking) == {"lab-config"}


def _cli(root: Path, vocab: Path, *extra: str) -> int:
    return gate.main(
        [
            "--repo-root",
            str(root),
            "--vocabulary",
            str(vocab),
            "--lab-vocabulary",
            str(_lab_vocab_for(vocab)),
            *extra,
        ]
    )


def test_the_lab_class_gate_command(tmp_path: Path, vocab: Path) -> None:
    """The command every repository task runs: enforce, the two lab classes.

    The repository is still in report mode, and the targeted run's --mode
    wins, so it cannot read green over a lab address.
    """
    root = _make_repo(
        tmp_path / "r",
        {"src/x.txt": f"contact {PERSON}\n"},
        MINIMAL_CONFIG.replace("mode: enforce", "mode: report"),
    )
    args = ("--mode", "enforce", "--only-classes", "private-network,lab-config")
    assert _cli(root, vocab, *args) == 0
    (root / "src" / "x.txt").write_text(f"H = '{LAN_LITERAL}'\n", encoding="utf-8")
    assert _cli(root, vocab, *args) == 1


def test_the_lab_class_gate_refuses_an_unknown_class(
    tmp_path: Path, vocab: Path
) -> None:
    root = _make_repo(tmp_path / "r", {"src/x.py": "x = 1\n"})
    assert _cli(root, vocab, "--only-classes", "lab-confgi") == 2


def test_the_lab_vocabulary_defaults_beside_the_vocabulary(
    tmp_path: Path, vocab: Path
) -> None:
    """With no --lab-vocabulary, the gate reads the file beside the vocabulary
    and evaluates the lab-config class against it.
    """
    root = _make_repo(tmp_path / "r", {"src/x.txt": f"L = {LAB_LANE}\n"})
    argv = ["--repo-root", str(root), "--vocabulary", str(vocab)]
    (vocab.parent / gate.LAB_VOCABULARY_BASENAME).write_text(
        LAB_VOCAB, encoding="utf-8"
    )
    assert gate.main(argv) == 1


def test_an_old_caller_with_no_lab_vocabulary_runs_every_other_class(
    tmp_path: Path, vocab: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """A caller pinned before OMN-19766 passes no --lab-vocabulary and has none
    beside the vocabulary. The lab-config class is reported as NOT evaluated
    and every other class still runs, so a real finding still fails the run.
    Measured 2026-09-26: exit 2 here turned every such caller's required CI
    Summary red (onex_change_control#11491, #11528).
    """
    root = _make_repo(tmp_path / "r", {"src/x.txt": f"L = {LAB_LANE}\n"})
    argv = ["--repo-root", str(root), "--vocabulary", str(vocab)]
    assert gate.main(argv) == 0
    captured = capsys.readouterr()
    assert "lab-config class NOT evaluated" in captured.err
    assert "NOT EVALUATED: lab-config" in captured.out
    # Positive control: another class in the same run still fails it.
    (root / "src" / "x.txt").write_text(f"contact {PERSON}\n", encoding="utf-8")
    assert gate.main(argv) == 1


def test_a_requested_lab_class_with_no_lab_vocabulary_is_refused(
    tmp_path: Path, vocab: Path
) -> None:
    root = _make_repo(tmp_path / "r", {"src/x.py": "x = 1\n"})
    argv = ["--repo-root", str(root), "--vocabulary", str(vocab)]
    assert gate.main([*argv, "--only-classes", "private-network,lab-config"]) == 2
    assert gate.main([*argv, "--only-classes", "private-network"]) == 0


def test_an_enforced_lab_class_with_no_lab_vocabulary_is_refused(
    tmp_path: Path, vocab: Path
) -> None:
    config = MINIMAL_CONFIG.replace("mode: enforce", "mode: report") + (
        "enforce_classes:\n  - lab-config\n"
    )
    root = _make_repo(tmp_path / "r", {"src/x.py": "x = 1\n"}, config)
    argv = ["--repo-root", str(root), "--vocabulary", str(vocab)]
    assert gate.main(argv) == 2
    with pytest.raises(gate.ConfigError, match="enforced"):
        gate.run(root, vocab, "report", None, lab_vocab_path=None)


def test_an_explicit_lab_vocabulary_that_is_absent_is_still_refused(
    tmp_path: Path, vocab: Path
) -> None:
    root = _make_repo(tmp_path / "r", {"src/x.py": "x = 1\n"})
    argv = [
        "--repo-root",
        str(root),
        "--vocabulary",
        str(vocab),
        "--lab-vocabulary",
        str(tmp_path / "nope.yaml"),
    ]
    assert gate.main(argv) == 2


# ---------------------------------------------------------------------------
# Added-lines scope (OMN-19835)
# ---------------------------------------------------------------------------

SCOPE_CONFIG = MINIMAL_CONFIG.replace("mode: enforce", "mode: report") + (
    "enforce_scope: added-lines\n"
    "enforce_classes:\n"
    '  - "lab-config"\n'
    '  - "person-name"\n'
)
CLEAN_LINE = "nothing to see here\n"


def _git_in(root: Path, *args: str) -> str:
    """git in a fixture repository, with the hook-exported location scrubbed."""
    return subprocess.run(
        ["git", "-c", "user.name=t", "-c", "user.email=t@example.invalid", *args],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
        env=scrub_git_location_env(),
    ).stdout.strip()


def _commit(root: Path, message: str) -> str:
    _git_in(root, "add", "-A", "-f")
    _git_in(root, "commit", "-q", "--allow-empty", "-m", message)
    return _git_in(root, "rev-parse", "HEAD")


def _scoped_repo(tmp_path: Path, files: dict[str, str]) -> tuple[Path, str]:
    """A fixture repository whose base commit holds ``files``."""
    root = _make_repo(tmp_path / "r", files, SCOPE_CONFIG)
    return root, _commit(root, "base")


def _run_from_base(root: Path, vocab: Path, base: str):
    return _run(
        root, vocab, mode="report", added=gate.added_lines_from_base(root, base)
    )


def _failing(root: Path, vocab: Path, added) -> list:
    code, blocking, _ = _run(root, vocab, mode="report", added=added)
    config = gate.load_repo_config(root / gate.CONFIG_BASENAME)
    failing = gate.failing_findings(blocking, config, "report", added)
    assert (code == 1) is bool(failing)
    return failing


def test_added_lines_an_added_finding_blocks(tmp_path: Path, vocab: Path) -> None:
    root, base = _scoped_repo(tmp_path, {"src/a.txt": CLEAN_LINE})
    (root / "src" / "a.txt").write_text(
        CLEAN_LINE + f"lane {LAB_LANE}\n", encoding="utf-8"
    )
    _commit(root, "adds a lab lane id")
    code, _, _ = _run_from_base(root, vocab, base)
    assert code == 1
    failing = _failing(root, vocab, gate.added_lines_from_base(root, base))
    assert [(f.path, f.line_no, f.class_name) for f in failing] == [
        ("src/a.txt", 2, "lab-config")
    ]


def test_added_lines_an_untouched_existing_finding_does_not_block(
    tmp_path: Path, vocab: Path
) -> None:
    root, base = _scoped_repo(
        tmp_path, {"src/a.txt": f"lane {LAB_LANE}\n", "src/b.txt": CLEAN_LINE}
    )
    (root / "src" / "b.txt").write_text(CLEAN_LINE * 2, encoding="utf-8")
    _commit(root, "an unrelated change")
    code, blocking, _ = _run_from_base(root, vocab, base)
    assert code == 0
    # Still reported: the scope narrows the verdict, never the report.
    assert ("src/a.txt", "lab-config") in {(f.path, f.class_name) for f in blocking}


def test_added_lines_an_edit_elsewhere_in_the_same_file_does_not_charge_it(
    tmp_path: Path, vocab: Path
) -> None:
    root, base = _scoped_repo(tmp_path, {"src/a.txt": f"lane {LAB_LANE}\n"})
    (root / "src" / "a.txt").write_text(
        f"lane {LAB_LANE}\n" + CLEAN_LINE, encoding="utf-8"
    )
    _commit(root, "appends a clean line")
    code, _, _ = _run_from_base(root, vocab, base)
    assert code == 0


def test_added_lines_a_moved_line_counts_as_added(tmp_path: Path, vocab: Path) -> None:
    root, base = _scoped_repo(
        tmp_path, {"src/a.txt": f"lane {LAB_LANE}\n" + CLEAN_LINE * 3}
    )
    (root / "src" / "a.txt").write_text(
        CLEAN_LINE * 3 + f"lane {LAB_LANE}\n", encoding="utf-8"
    )
    _commit(root, "moves the line")
    failing = _failing(root, vocab, gate.added_lines_from_base(root, base))
    assert [(f.path, f.line_no) for f in failing] == [("src/a.txt", 4)]


def test_added_lines_a_line_moved_to_another_file_counts_as_added(
    tmp_path: Path, vocab: Path
) -> None:
    root, base = _scoped_repo(
        tmp_path, {"src/a.txt": f"lane {LAB_LANE}\n" + CLEAN_LINE}
    )
    (root / "src" / "a.txt").write_text(CLEAN_LINE, encoding="utf-8")
    (root / "src" / "b.txt").write_text(f"lane {LAB_LANE}\n", encoding="utf-8")
    _commit(root, "moves the line to another file")
    failing = _failing(root, vocab, gate.added_lines_from_base(root, base))
    assert [f.path for f in failing] == ["src/b.txt"]


def test_added_lines_a_renamed_file_counts_in_full(tmp_path: Path, vocab: Path) -> None:
    root, base = _scoped_repo(
        tmp_path, {"src/old.txt": f"lane {LAB_LANE}\n" + CLEAN_LINE * 5}
    )
    _git_in(root, "mv", "src/old.txt", "src/new.txt")
    _commit(root, "renames the file, content unchanged")
    added = gate.added_lines_from_base(root, base)
    assert "src/new.txt" in added.added_files
    failing = _failing(root, vocab, added)
    assert [(f.path, f.class_name) for f in failing] == [("src/new.txt", "lab-config")]


def test_added_lines_a_deleted_file_adds_nothing(tmp_path: Path, vocab: Path) -> None:
    root, base = _scoped_repo(
        tmp_path, {"src/a.txt": f"lane {LAB_LANE}\n", "src/b.txt": CLEAN_LINE}
    )
    (root / "src" / "a.txt").unlink()
    _commit(root, "deletes the file")
    code, _, _ = _run_from_base(root, vocab, base)
    assert code == 0


def test_added_lines_a_changed_binary_file_is_charged_whole(
    tmp_path: Path, vocab: Path
) -> None:
    """git gives a binary file no hunks, so it cannot say which line is new.

    The file is charged whole rather than not at all.
    """
    root, base = _scoped_repo(tmp_path, {"src/a.txt": CLEAN_LINE})
    blob = root / "src" / "blob.dat"
    blob.write_bytes(b"\x00header\n" + CLEAN_LINE.encode())
    _commit(root, "adds a clean binary")
    base = _git_in(root, "rev-parse", "HEAD")
    blob.write_bytes(b"\x00header\n" + f"lane {LAB_LANE}\n".encode())
    _commit(root, "rewrites the binary with a lab lane id")
    added = gate.added_lines_from_base(root, base)
    assert "src/blob.dat" in added.whole_files
    failing = _failing(root, vocab, added)
    assert [(f.path, f.class_name) for f in failing] == [("src/blob.dat", "lab-config")]


def test_added_lines_an_unchanged_binary_is_not_charged(
    tmp_path: Path, vocab: Path
) -> None:
    root = _make_repo(tmp_path / "r", {"src/a.txt": CLEAN_LINE}, SCOPE_CONFIG)
    (root / "src" / "blob.dat").write_bytes(b"\x00" + f"lane {LAB_LANE}\n".encode())
    base = _commit(root, "base carries the binary")
    (root / "src" / "a.txt").write_text(CLEAN_LINE * 2, encoding="utf-8")
    _commit(root, "unrelated")
    code, _, _ = _run_from_base(root, vocab, base)
    assert code == 0


def test_added_lines_a_path_with_spaces_and_unicode_is_attributed(
    tmp_path: Path, vocab: Path
) -> None:
    root, base = _scoped_repo(tmp_path, {"src/a.txt": CLEAN_LINE})
    odd = root / "src" / "dir with space" / 'café "q".txt'
    odd.parent.mkdir(parents=True)
    odd.write_text(CLEAN_LINE + f"lane {LAB_LANE}\n", encoding="utf-8")
    _commit(root, "an oddly named file")
    failing = _failing(root, vocab, gate.added_lines_from_base(root, base))
    assert [(f.path, f.line_no) for f in failing] == [
        ('src/dir with space/café "q".txt', 2)
    ]


def test_added_lines_diff_base_is_the_merge_base(tmp_path: Path, vocab: Path) -> None:
    """A finding the base branch gained after the fork point is not the PR's."""
    root, _ = _scoped_repo(tmp_path, {"src/a.txt": CLEAN_LINE})
    _git_in(root, "branch", "-M", "main")
    _git_in(root, "checkout", "-q", "-b", "pr")
    (root / "src" / "pr.txt").write_text(CLEAN_LINE, encoding="utf-8")
    _commit(root, "the pull request")
    _git_in(root, "checkout", "-q", "main")
    (root / "src" / "later.txt").write_text(f"lane {LAB_LANE}\n", encoding="utf-8")
    _commit(root, "the base moves on")
    _git_in(root, "checkout", "-q", "pr")
    code, _, _ = _run_from_base(root, vocab, "main")
    assert code == 0


def test_added_lines_staged_blocks_a_staged_finding(
    tmp_path: Path, vocab: Path
) -> None:
    root, _ = _scoped_repo(tmp_path, {"src/a.txt": f"contact {PERSON}\n"})
    assert _failing(root, vocab, gate.added_lines_staged(root)) == []
    (root / "src" / "b.txt").write_text(f"contact {PERSON}\n", encoding="utf-8")
    _git_in(root, "add", "src/b.txt")
    failing = _failing(root, vocab, gate.added_lines_staged(root))
    assert [(f.path, f.class_name) for f in failing] == [("src/b.txt", "person-name")]


def test_added_lines_staged_first_commit_charges_everything(
    tmp_path: Path, vocab: Path
) -> None:
    root = _make_repo(tmp_path / "r", {"src/a.txt": f"lane {LAB_LANE}\n"}, SCOPE_CONFIG)
    failing = _failing(root, vocab, gate.added_lines_staged(root))
    assert [f.path for f in failing] == ["src/a.txt"]


def test_added_lines_staged_merge_charges_only_what_the_merge_adds(
    tmp_path: Path, vocab: Path
) -> None:
    """A clean merge brings the other branch's lines in; they are not the
    merge author's. A line added relative to EVERY parent still is.
    """
    root, _ = _scoped_repo(tmp_path, {"src/a.txt": CLEAN_LINE})
    _git_in(root, "branch", "-M", "main")
    _git_in(root, "checkout", "-q", "-b", "side")
    (root / "src" / "side.txt").write_text(f"lane {LAB_LANE}\n", encoding="utf-8")
    _commit(root, "the other branch carries a finding")
    _git_in(root, "checkout", "-q", "main")
    (root / "src" / "main.txt").write_text(CLEAN_LINE, encoding="utf-8")
    _commit(root, "main moves")
    _git_in(root, "merge", "--no-commit", "--no-ff", "-q", "side")
    assert _failing(root, vocab, gate.added_lines_staged(root)) == []
    (root / "src" / "resolution.txt").write_text(
        f"contact {PERSON}\n", encoding="utf-8"
    )
    _git_in(root, "add", "src/resolution.txt")
    failing = _failing(root, vocab, gate.added_lines_staged(root))
    assert [f.path for f in failing] == ["src/resolution.txt"]


def test_scope_without_a_diff_source_is_refused(tmp_path: Path, vocab: Path) -> None:
    root, _ = _scoped_repo(tmp_path, {"src/a.txt": CLEAN_LINE})
    with pytest.raises(gate.ConfigError, match="no diff source"):
        _run(root, vocab, mode="report")
    assert _cli(root, vocab) == 2


def test_scope_a_targeted_only_classes_run_keeps_its_whole_file_verdict(
    tmp_path: Path, vocab: Path
) -> None:
    """The lab-class gate command works unchanged in an added-lines repository."""
    root, _ = _scoped_repo(tmp_path, {"src/a.txt": f"lane {LAB_LANE}\n"})
    args = ("--mode", "enforce", "--only-classes", "private-network,lab-config")
    assert _cli(root, vocab, *args) == 1
    (root / "src" / "a.txt").write_text(CLEAN_LINE, encoding="utf-8")
    assert _cli(root, vocab, *args) == 0


def test_scope_whole_tree_ignores_a_diff_source(tmp_path: Path, vocab: Path) -> None:
    """Never weaker: a repository that does not declare the scope keeps its
    whole-tree verdict even when CI hands the gate a diff base.
    """
    config = LAB_CONFIG
    root = _make_repo(tmp_path / "r", {"src/a.txt": f"lane {LAB_LANE}\n"}, config)
    base = _commit(root, "base")
    (root / "src" / "b.txt").write_text(CLEAN_LINE, encoding="utf-8")
    _commit(root, "unrelated")
    assert gate.load_repo_config(root / gate.CONFIG_BASENAME).enforce_scope == (
        gate.WHOLE_TREE_SCOPE
    )
    code, _, _ = _run_from_base(root, vocab, base)
    assert code == 1
    assert _cli(root, vocab, "--diff-base", base) == 1


def test_scope_an_unknown_value_is_a_config_error(tmp_path: Path, vocab: Path) -> None:
    config = MINIMAL_CONFIG + "enforce_scope: added_lines\n"
    root = _make_repo(tmp_path / "r", {"src/x.py": "x = 1\n"}, config)
    with pytest.raises(gate.ConfigError, match="enforce_scope"):
        _run(root, vocab)


def test_scope_cli_diff_base_and_diff_staged(
    tmp_path: Path, vocab: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root, base = _scoped_repo(tmp_path, {"src/a.txt": f"lane {LAB_LANE}\n"})
    assert _cli(root, vocab, "--diff-base", base) == 0
    assert _cli(root, vocab, "--diff-staged") == 0
    (root / "src" / "b.txt").write_text(f"lane {LAB_LANE}\n", encoding="utf-8")
    _git_in(root, "add", "src/b.txt")
    capsys.readouterr()
    assert _cli(root, vocab, "--diff-staged") == 1
    out = capsys.readouterr().out
    assert "ADDED src/b.txt:1: lab-config" in out
    assert "ADDED src/a.txt" not in out
    _commit(root, "commits it")
    assert _cli(root, vocab, "--diff-base", base) == 1


def test_scope_an_unresolvable_diff_base_is_a_refusal(
    tmp_path: Path, vocab: Path
) -> None:
    root, _ = _scoped_repo(tmp_path, {"src/a.txt": CLEAN_LINE})
    assert _cli(root, vocab, "--diff-base", "no-such-ref") == 2


def test_the_repo_enforces_the_five_classes_on_added_lines() -> None:
    """omniclaude's own config: the five classes fail a run, on added lines.

    OMN-19835 enforced the first four; OMN-19837 added private-network (lab
    addresses and host nicknames), which was already a fully implemented
    content class but was left unenforced on purpose in OMN-19835's own PR.
    """
    config = gate.load_repo_config(REPO_ROOT / gate.CONFIG_BASENAME)
    assert config.enforce_scope == gate.ADDED_LINES_SCOPE
    assert {
        "private-repo-name",
        "internal-kb-prose",
        "lab-config",
        "person-name",
        "private-network",
    } <= config.enforce_classes


def test_vocabulary_environment_path_reaches_the_real_gate(
    tmp_path: Path, vocab: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _make_repo(tmp_path / "repo", {"README.md": "clean document\n"})
    monkeypatch.setenv("OMNI_HYGIENE_VOCAB_PATH", str(vocab))
    monkeypatch.delenv("OMNI_HOME", raising=False)
    assert gate.main(["--repo-root", str(root)]) == 0


def test_old_workspace_path_is_never_a_vocabulary_fallback(
    tmp_path: Path, vocab: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _make_repo(tmp_path / "repo", {"README.md": "clean document\n"})
    monkeypatch.delenv("OMNI_HYGIENE_VOCAB_PATH", raising=False)
    monkeypatch.setenv("OMNI_HOME", str(tmp_path))
    assert gate.main(["--repo-root", str(root)]) == 2
