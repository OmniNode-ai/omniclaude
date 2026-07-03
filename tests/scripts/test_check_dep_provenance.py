# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""Tests for the dependency-provenance gate (OMN-13873).

Covers the full policy surface of scripts/check_dep_provenance.py:

- hard-fail: omnibase-core rev=<sha>
- hard-fail: omnibase-core rev="v0.43.0" (tag-shaped value under rev= key)
- hard-fail: omnibase-core branch=<name>
- allow:     only onex-change-control rev= present (exempt)
- allow:     omnibase-infra rev= present (exempt), omninode-* exempt
- warn:      omnibase-core tag=v0.42.0 (released ref) — exit 0 + WARNING
- escape:    core rev= + '# raw-override-ok: OMN-13873' → exit 0
- escape:    empty '# raw-override-ok:' token does NOT exempt → exit 1
- repro:     omnimarket's real pyproject (core rev + compat rev) → exit 1
- fail-closed: missing file and unparseable TOML → exit 1
- report-only: hard-fail present but advisory mode → exit 0
- json:      structured report with hard_fail flag
"""

from __future__ import annotations

import importlib.util
import json
import sys
import textwrap
from pathlib import Path
from types import ModuleType

import pytest

# `import sys` is used by _load_module (sys.modules registration); keep it.

_MODULE_PATH = (
    Path(__file__).resolve().parents[2] / "scripts" / "check_dep_provenance.py"
)


def _load_module() -> ModuleType:
    spec = importlib.util.spec_from_file_location("check_dep_provenance", _MODULE_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    # Register before exec so @dataclass can resolve the module in sys.modules.
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


dep = _load_module()


def _write(tmp_path: Path, sources_block: str) -> Path:
    """Write a minimal valid pyproject with the given [tool.uv.sources] block."""
    path = tmp_path / "pyproject.toml"
    path.write_text(
        textwrap.dedent(
            f"""\
            [project]
            name = "example"
            version = "0.0.0"

            [tool.uv.sources]
            {sources_block}
            """
        )
    )
    return path


# ---------------------------------------------------------------------------
# Hard-fail cases
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_reject_core_rev_sha(tmp_path: Path) -> None:
    path = _write(
        tmp_path,
        'omnibase-core = { git = "https://github.com/OmniNode-ai/omnibase_core.git", '
        'rev = "29e9057b4a3604c8add623eacac86f1b537defdb" }',
    )
    assert dep.main(["--pyproject", str(path)]) == 1


@pytest.mark.unit
def test_reject_core_rev_tag_shaped(tmp_path: Path) -> None:
    # A tag-shaped VALUE under a rev= KEY is still a hard fail (key-based).
    path = _write(
        tmp_path,
        'omnibase-core = { git = "https://github.com/OmniNode-ai/omnibase_core.git", '
        'rev = "v0.43.0" }',
    )
    assert dep.main(["--pyproject", str(path)]) == 1


@pytest.mark.unit
def test_reject_core_branch(tmp_path: Path) -> None:
    path = _write(
        tmp_path,
        'omnibase-core = { git = "https://github.com/OmniNode-ai/omnibase_core.git", '
        'branch = "dev" }',
    )
    assert dep.main(["--pyproject", str(path)]) == 1


@pytest.mark.unit
def test_reject_underscore_spelling(tmp_path: Path) -> None:
    # uv treats omnibase_spi and omnibase-spi as the same dist.
    path = _write(
        tmp_path,
        'omnibase_spi = { git = "https://github.com/OmniNode-ai/omnibase_spi.git", '
        'rev = "abcdef1234567890" }',
    )
    assert dep.main(["--pyproject", str(path)]) == 1


# ---------------------------------------------------------------------------
# Allow cases (exempt packages)
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_allow_only_occ_rev(tmp_path: Path) -> None:
    path = _write(
        tmp_path,
        "onex-change-control = { git = "
        '"https://github.com/OmniNode-ai/onex_change_control.git", '
        'rev = "4877d3c223517cb0c7e1eca462ba0f4d38916314" }',
    )
    assert dep.main(["--pyproject", str(path)]) == 0


@pytest.mark.unit
def test_allow_infra_and_omninode_rev(tmp_path: Path) -> None:
    path = _write(
        tmp_path,
        'omnibase-infra = { git = "https://github.com/OmniNode-ai/omnibase_infra.git", '
        'rev = "7e52d5b0046c394b38454b97157e7a7191e6f008" }\n'
        'omninode-intelligence = { git = "https://github.com/OmniNode-ai/omniintelligence.git", '
        'rev = "deadbeefdeadbeef" }',
    )
    assert dep.main(["--pyproject", str(path)]) == 0


@pytest.mark.unit
def test_allow_no_uv_sources(tmp_path: Path) -> None:
    path = tmp_path / "pyproject.toml"
    path.write_text('[project]\nname = "x"\nversion = "0.0.0"\n')
    assert dep.main(["--pyproject", str(path)]) == 0


# ---------------------------------------------------------------------------
# Warn case (tag = released ref)
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_warn_core_tag(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    path = _write(
        tmp_path,
        'omnibase-core = { git = "https://github.com/OmniNode-ai/omnibase_core.git", '
        'tag = "v0.42.0" }',
    )
    assert dep.main(["--pyproject", str(path)]) == 0
    out = capsys.readouterr().out
    assert "WARNING" in out
    assert "v0.42.0" in out


# ---------------------------------------------------------------------------
# Escape hatch
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_escape_hatch_with_ticket(tmp_path: Path) -> None:
    path = _write(
        tmp_path,
        'omnibase-core = { git = "https://github.com/OmniNode-ai/omnibase_core.git", '
        'rev = "abcdef1234567890" }  # raw-override-ok: OMN-13873',
    )
    assert dep.main(["--pyproject", str(path)]) == 0


@pytest.mark.unit
def test_escape_hatch_empty_token_still_fails(tmp_path: Path) -> None:
    path = _write(
        tmp_path,
        'omnibase-core = { git = "https://github.com/OmniNode-ai/omnibase_core.git", '
        'rev = "abcdef1234567890" }  # raw-override-ok:',
    )
    assert dep.main(["--pyproject", str(path)]) == 1


@pytest.mark.unit
def test_escape_hatch_is_per_package(tmp_path: Path) -> None:
    # An annotation on core must NOT exempt an un-annotated compat override.
    path = _write(
        tmp_path,
        'omnibase-core = { git = "https://github.com/OmniNode-ai/omnibase_core.git", '
        'rev = "aaaa1111" }  # raw-override-ok: OMN-13873\n'
        'omnibase-compat = { git = "https://github.com/OmniNode-ai/omnibase_compat.git", '
        'rev = "bbbb2222" }',
    )
    assert dep.main(["--pyproject", str(path)]) == 1


# ---------------------------------------------------------------------------
# omnimarket real-pyproject reproduction
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_omnimarket_repro_fixture(tmp_path: Path) -> None:
    # Mirrors omnimarket's real [tool.uv.sources]: core rev + compat rev
    # (hard-fail) alongside infra rev + occ rev (exempt).
    path = _write(
        tmp_path,
        'omnibase-core = { git = "https://github.com/OmniNode-ai/omnibase_core.git", '
        'rev = "29e9057b4a3604c8add623eacac86f1b537defdb" }\n'
        'omnibase-compat = { git = "https://github.com/OmniNode-ai/omnibase_compat.git", '
        'rev = "c0fc71681d046e840e0997c04bd26176785a2992" }\n'
        'omnibase-infra = { git = "https://github.com/OmniNode-ai/omnibase_infra.git", '
        'rev = "7e52d5b0046c394b38454b97157e7a7191e6f008" }\n'
        "onex-change-control = { git = "
        '"https://github.com/OmniNode-ai/onex_change_control.git", '
        'rev = "dd2620d18001495b8d0f493b421b38399e9aab4b" }',
    )
    assert dep.main(["--pyproject", str(path)]) == 1


# ---------------------------------------------------------------------------
# Fail-closed
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_missing_file_fails_closed(tmp_path: Path) -> None:
    assert dep.main(["--pyproject", str(tmp_path / "nope.toml")]) == 1


@pytest.mark.unit
def test_unparseable_toml_fails_closed(tmp_path: Path) -> None:
    path = tmp_path / "pyproject.toml"
    path.write_text("this is = = not valid toml [[[\n")
    assert dep.main(["--pyproject", str(path)]) == 1


@pytest.mark.unit
def test_non_table_uv_sources_fails_closed(tmp_path: Path) -> None:
    path = tmp_path / "pyproject.toml"
    path.write_text("[tool]\n[tool.uv]\nsources = []\n")
    assert dep.main(["--pyproject", str(path)]) == 1


# ---------------------------------------------------------------------------
# --report-only and --json
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_report_only_never_fails(tmp_path: Path) -> None:
    path = _write(
        tmp_path,
        'omnibase-core = { git = "https://github.com/OmniNode-ai/omnibase_core.git", '
        'rev = "abcdef1234567890" }',
    )
    assert dep.main(["--pyproject", str(path), "--report-only"]) == 0


@pytest.mark.unit
def test_report_only_missing_file_never_fails(tmp_path: Path) -> None:
    assert dep.main(["--pyproject", str(tmp_path / "nope.toml"), "--report-only"]) == 0


@pytest.mark.unit
def test_json_output_hard_fail_flag(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = _write(
        tmp_path,
        'omnibase-core = { git = "https://github.com/OmniNode-ai/omnibase_core.git", '
        'rev = "abcdef1234567890" }',
    )
    rc = dep.main(["--pyproject", str(path), "--json"])
    assert rc == 1
    payload = json.loads(capsys.readouterr().out)
    assert payload["hard_fail"] is True
    assert payload["findings"][0]["package"] == "omnibase-core"
    assert payload["findings"][0]["severity"] == "hard_fail"
