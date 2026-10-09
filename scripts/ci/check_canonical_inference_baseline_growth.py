# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Compare core baselines at the git SHAs pinned by the inference workflow.

Only the omniclaude fingerprint subset may shrink. Changed pins require both
baselines to be obtainable and valid; unchanged pins need no network access.
"""

from __future__ import annotations

import argparse
import http.client
import json
import re
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
WORKFLOW_PATH = ".github/workflows/canonical-inference-gate.yml"
PIN_PATTERN = re.compile(r"omnibase_core\.git@([0-9a-fA-F]{40})(?![0-9a-fA-F])")
BASELINE_URL = (
    "https://raw.githubusercontent.com/OmniNode-ai/omnibase_core/{sha}/"
    "src/omnibase_core/validation/baselines/canonical_inference_baseline.json"
)
DOWNLOAD_TIMEOUT = 15
DOWNLOAD_RETRIES = 3


def parse_pin(workflow_text: str) -> str | None:
    """Require every matching pin in a workflow to identify the same commit."""
    pins = {sha.lower() for sha in PIN_PATTERN.findall(workflow_text)}
    if len(pins) > 1:
        raise ValueError("inconsistent omnibase_core SHAs within workflow")
    return next(iter(pins), None)


def read_pin(ref: str) -> str | None:
    if ref == "HEAD":
        workflow_text = (REPO_ROOT / WORKFLOW_PATH).read_text(encoding="utf-8")
    else:
        try:
            workflow_text = subprocess.check_output(
                ["git", "show", f"{ref}:{WORKFLOW_PATH}"],
                cwd=REPO_ROOT,
                text=True,
                stderr=subprocess.PIPE,
                timeout=30,
            )
        except subprocess.CalledProcessError:
            # Distinguish an absent workflow from an invalid/unobtainable ref.
            paths = subprocess.check_output(
                ["git", "ls-tree", "--name-only", ref, "--", WORKFLOW_PATH],
                cwd=REPO_ROOT,
                text=True,
                stderr=subprocess.PIPE,
                timeout=30,
            )
            if not paths.strip():
                return None
            raise
    pin = parse_pin(workflow_text)
    if ref != "HEAD" and pin is None:
        raise ValueError(f"{ref}:{WORKFLOW_PATH} has no 40-hex omnibase_core git pin")
    return pin


def repo_fingerprints(baseline_text: str) -> set[str]:
    baseline: object = json.loads(baseline_text)
    if not isinstance(baseline, dict) or not isinstance(
        baseline.get("violations"), list
    ):
        raise ValueError("baseline must contain a violations list")
    fingerprints: set[str] = set()
    for entry in baseline["violations"]:
        if (
            not isinstance(entry, dict)
            or not isinstance(entry.get("repo"), str)
            or not isinstance(entry.get("fingerprint"), str)
        ):
            raise ValueError(
                "baseline entries must contain repo and fingerprint strings"
            )
        if entry["repo"] == "omniclaude":
            fingerprints.add(entry["fingerprint"])
    return fingerprints


def obtain_baseline(sha: str) -> set[str]:
    """Fetch an immutable baseline with a timeout and three network retries."""
    url = BASELINE_URL.format(sha=sha)
    opener = urllib.request.build_opener()
    for attempt in range(DOWNLOAD_RETRIES + 1):
        try:
            with opener.open(url, timeout=DOWNLOAD_TIMEOUT) as response:
                baseline_text = response.read().decode("utf-8")
        except (urllib.error.URLError, OSError, http.client.HTTPException) as exc:
            if attempt == DOWNLOAD_RETRIES:
                raise RuntimeError(
                    f"download failed after {attempt + 1} attempts from {url}: {exc}"
                ) from exc
        else:
            return repo_fingerprints(baseline_text)
    raise RuntimeError(f"baseline download did not complete: {url}")


def check_growth(base_ref: str) -> int:
    try:
        head_pin = read_pin("HEAD")
        if head_pin is None:
            raise ValueError(
                f"HEAD:{WORKFLOW_PATH} has no 40-hex omnibase_core git pin"
            )
        prior_pin = read_pin(base_ref)
        if prior_pin is None:
            print(
                "CANONICAL-INFERENCE BASELINE OK: no base workflow pin; "
                "nothing to compare (new gate)."
            )
            return 0
        if prior_pin == head_pin:
            print(
                "CANONICAL-INFERENCE BASELINE OK: pin unchanged; "
                f"the baseline cannot have grown ({head_pin})."
            )
            return 0
        baselines: list[set[str]] = []
        for label, pin in (("prior", prior_pin), ("HEAD", head_pin)):
            try:
                baselines.append(obtain_baseline(pin))
            except Exception as exc:
                raise RuntimeError(
                    f"cannot obtain or parse {label} baseline at omnibase_core {pin}: {exc}"
                ) from exc
        prior, head = baselines
        grew = head - prior
        if grew:
            print(
                "CANONICAL-INFERENCE BASELINE GREW: "
                f"{len(grew)} new omniclaude fingerprint(s) "
                f"({prior_pin} -> {head_pin}); baseline is burn-down only.\n"
                + "\n".join(sorted(grew)),
                file=sys.stderr,
            )
            return 1
        print(
            "CANONICAL-INFERENCE BASELINE OK: "
            f"omniclaude subset {len(head)} (<= prior {len(prior)}); "
            f"omnibase_core {prior_pin} -> {head_pin}."
        )
        return 0
    except (RuntimeError, ValueError, OSError, subprocess.SubprocessError) as exc:
        print(f"CANONICAL-INFERENCE BASELINE CHECK FAILED: {exc}", file=sys.stderr)
        return 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-ref", required=True)
    return check_growth(parser.parse_args().base_ref)


if __name__ == "__main__":
    raise SystemExit(main())
