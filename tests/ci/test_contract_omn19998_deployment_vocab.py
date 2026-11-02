# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""The OMN-19998 contract names no lab runner host (OMN-19998).

The hostile-reviewer runner-placement requirement once named a lab runner host
in its prose. The deployment-config baseline may only shrink, so the contract
states the exclusion by what the excluded runners cannot do instead.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

pytestmark = pytest.mark.unit

CONTRACT = Path(__file__).resolve().parents[2] / "contracts" / "OMN-19998.yaml"
HYGIENE_CONFIG = Path(__file__).resolve().parents[2] / ".public-repo-hygiene.yaml"
LAB_RUNNER_HOST = "h2" + "03"


def test_contract_names_no_lab_runner_host() -> None:
    text = CONTRACT.read_text(encoding="utf-8")
    assert LAB_RUNNER_HOST not in text


def test_deployment_residue_baseline_has_shrunk_past_nineteen_files() -> None:
    """The baseline held 19 files before the contract dropped its lab runner host."""
    config = yaml.safe_load(HYGIENE_CONFIG.read_text(encoding="utf-8"))
    residue = json.loads(config["deployment_residue"])
    assert residue["file_count"] <= 18
