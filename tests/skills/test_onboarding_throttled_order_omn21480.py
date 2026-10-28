# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""OMN-21480: a model the pre-menu probe saw throttled is ordered after the ones that answered.

The probe keeps a 429 model (busy is not unusable, OMN-21464), but the order
onboarding stores and recommends tested it first, so one upstream throttle
decided the provider's verdict while a working model sat second. The provider
is stubbed; no real provider is called.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

_PROBE_TESTS = Path(__file__).with_name("test_onboarding_model_probe_omn21465.py")
_spec = importlib.util.spec_from_file_location("_omn21465_probe_helpers", _PROBE_TESTS)
assert _spec is not None and _spec.loader is not None
_h = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_h)

THROTTLED = (429, {"error": {"message": "Rate limit reached"}})


def test_ac3_a_throttled_model_is_ordered_after_the_one_that_answered(
    tmp_path: Path,
) -> None:
    """AC3: gpt-4o probes 429 and is listed and recommended first; gpt-4.1 probes ok.
    The stored order puts gpt-4.1 first and Enter takes it first."""
    models = ["gpt-4o", "gpt-4.1"]
    chat = {"gpt-4o": THROTTLED}
    with _h._provider(models, chat) as served:
        cat = _h._catalogue(tmp_path, served["url"], models)
        out = _h._run(
            tmp_path,
            cat,
            _h.MENU
            + 'echo "list=$(echo $MODEL_LIST)"; echo "recommended=$RECOMMENDED"\n'
            + 'choose_models openai <<< ""\necho "chosen=$CHOSEN_OPENAI"',
        )
    assert "list=gpt-4.1 gpt-4o" in out
    assert "recommended=1,2" in out
    assert "chosen=gpt-4.1 gpt-4o" in out
    assert "gpt-4o  (recommended)  (busy just now, HTTP 429)" in out


def test_ac3_models_that_all_answered_keep_their_order(tmp_path: Path) -> None:
    models = ["gpt-4o", "gpt-4.1"]
    with _h._provider(models, {}) as served:
        cat = _h._catalogue(tmp_path, served["url"], models)
        out = _h._run(tmp_path, cat, _h.MENU + 'echo "list=$(echo $MODEL_LIST)"')
    assert "list=gpt-4o gpt-4.1" in out


def test_ac1_the_first_model_onex_tests_is_one_that_answered(tmp_path: Path) -> None:
    """AC1 (onboarding side): the order stored leads with the model that answered, so
    the provider test's first call is not the throttled one."""
    models = ["gpt-4o", "gpt-4.1"]
    with _h._provider(models, {"gpt-4o": THROTTLED}) as served:
        cat = _h._catalogue(tmp_path, served["url"], models)
        out = _h._run(
            tmp_path,
            cat,
            _h.MENU + 'choose_models openai <<< "1"\necho "chosen=$CHOSEN_OPENAI"',
        )
    assert "chosen=gpt-4.1\n" in out


def test_ac2_every_model_throttled_is_kept_and_said_to_be_a_busy_provider(
    tmp_path: Path,
) -> None:
    """AC2 (onboarding side): all models probing 429 keep the provider (busy is not a
    failed key) and the menu says so; a provider with answering models says nothing."""
    models = ["gpt-4o", "gpt-4.1"]
    with _h._provider(models, dict.fromkeys(models, THROTTLED)) as served:
        cat = _h._catalogue(tmp_path, served["url"], models)
        out = _h._run(
            tmp_path,
            cat,
            _h.MENU + 'choose_models openai <<< ""\necho "chosen=$CHOSEN_OPENAI"',
        )
    assert "rc=0" in out
    assert "Every model above is busy just now (HTTP 429). Your key is fine" in out
    assert "chosen=gpt-4o gpt-4.1" in out
    with _h._provider(models, {"gpt-4o": THROTTLED}) as served:
        cat = _h._catalogue(tmp_path, served["url"], models)
        out = _h._run(tmp_path, cat, _h.MENU + 'choose_models openai <<< ""')
    assert "Every model above is busy" not in out
