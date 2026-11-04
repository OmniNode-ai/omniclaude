# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""OMN-22181: the onboarding disk minimum and the guide's recommended VM agree.

The preflight demanded 20 GB of free disk while the guide recommended a VM that
has 17 GB free on the stock Tart macOS image, so the documented VM could not
pass the script's own minimum (clean-VM walk of 2026-11-02, exit 3).

``plugins/onex/skills/_bin/onboarding_disk_floor.yaml`` is the one declared
source of the figures: the stock image, the recommended VM, the measured use per
path and the margin. The script is downloaded as a single pinned file, so it
cannot read that file at run time; its constants are checked against the file
here instead, along with the guide's VM text and its "Free disk" row.
"""

from __future__ import annotations

import math
import re
from pathlib import Path
from typing import Any

import pytest
import yaml

REPO = Path(__file__).resolve().parents[2]
SCRIPT = REPO / "plugins" / "onex" / "skills" / "_bin" / "lab-onboarding.sh"
GUIDE = REPO / "plugins" / "onex" / "ONBOARDING.md"
FLOOR = REPO / "plugins" / "onex" / "skills" / "_bin" / "onboarding_disk_floor.yaml"

pytestmark = pytest.mark.unit


def _floor() -> dict[str, Any]:
    data = yaml.safe_load(FLOOR.read_text(encoding="utf-8"))
    assert isinstance(data, dict)
    return data


def _constant(name: str) -> int:
    match = re.search(rf"^{name}=(\d+)", SCRIPT.read_text(encoding="utf-8"), re.M)
    assert match, f"{name} is not declared in {SCRIPT.name}"
    return int(match.group(1))


def _vm_spec() -> str:
    match = re.search(r'^VM_SPEC="(.*)"$', SCRIPT.read_text(encoding="utf-8"), re.M)
    assert match, "VM_SPEC is not declared in the script"
    return match.group(1)


def _guide_free_disk_row() -> list[str]:
    for line in GUIDE.read_text(encoding="utf-8").splitlines():
        if line.startswith("| Free disk"):
            return [cell.strip() for cell in line.strip("|").split("|")]
    raise AssertionError("the guide has no 'Free disk' row")


def test_each_path_minimum_is_measured_use_plus_the_stated_margin() -> None:
    floor = _floor()
    margin = floor["margin_gb"]
    assert margin > 0
    for name, path in floor["paths"].items():
        assert path["measured_use_gb"] == math.ceil(path["peak_use_gib"]), name
        assert path["min_gb"] == path["measured_use_gb"] + margin, name


def test_every_path_fits_the_stock_image_free_space() -> None:
    floor = _floor()
    for name, path in floor["paths"].items():
        assert path["min_gb"] <= floor["image"]["free_gb"], name


def test_the_script_constant_is_the_declared_minimum_of_the_native_paths() -> None:
    paths = _floor()["paths"]
    assert _constant("M1_DISK_GB") == paths["local_model"]["min_gb"]
    assert paths["hosted_key"]["min_gb"] <= _constant("M1_DISK_GB")


def test_the_ollama_path_minimum_is_the_native_minimum_plus_the_model_download() -> (
    None
):
    ollama = _floor()["paths"]["ollama_model"]
    assert ollama["min_gb"] == _constant("M1_DISK_GB") + ollama["model_download_gb"]


def test_the_guide_vm_leaves_at_least_the_minimum_free_on_the_stock_image() -> None:
    floor = _floor()
    free = floor["image"]["free_gb"]
    assert free >= _constant("M1_DISK_GB"), (
        f"the stock image leaves {free} GB free; preflight needs {_constant('M1_DISK_GB')} GB"
    )
    assert free >= floor["paths"]["local_model"]["min_gb"]


def test_the_recommended_vm_is_the_stock_image_and_is_never_grown_past_it() -> None:
    floor = _floor()
    vm, image = floor["vm"], floor["image"]
    assert vm["disk_gb"] == image["disk_gb"], (
        "the disk cannot be grown past the image from inside the guest (it needs "
        "csrutil disable), and Tart cannot shrink it"
    )
    assert vm["vcpu"] == floor["requirements"]["cpus"]
    assert vm["ram_gb"] == floor["requirements"]["ram_gb"]


def test_the_script_vm_spec_states_the_declared_vm() -> None:
    vm = _floor()["vm"]
    spec = _vm_spec()
    assert f"{vm['vcpu']} vCPU" in spec
    assert f"{vm['ram_gb']} GB RAM" in spec
    assert f"{vm['disk_gb']} GB disk" in spec
    assert f"{_floor()['image']['free_gb']} GB free" in spec
    assert "40 GB" not in spec


def test_the_guide_states_the_declared_vm() -> None:
    vm = _floor()["vm"]
    text = " ".join(GUIDE.read_text(encoding="utf-8").split())
    needle = f"{vm['vcpu']} vCPU, {vm['ram_gb']} GB RAM and {vm['disk_gb']} GB disk"
    assert needle in text
    assert "40 GB disk" not in text


def test_the_guide_free_disk_row_is_the_script_minimum() -> None:
    cells = _guide_free_disk_row()
    assert cells[1] == f"{_constant('M1_DISK_GB')} GB"
