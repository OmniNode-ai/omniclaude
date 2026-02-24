# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""Epic decomposer: maps Linear tickets to repos using label overrides + keyword scoring.

Priority order:
1. part1:repo + part2:repo labels (explicit override, both required)
2. multi-repo:repo1,repo2 label (bare multi-repo → unmatched)
3. depends-on:repo label
4. Single exact label match to repo name
5. Keyword scoring (presence/absence, each keyword counted once per ticket)
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml

# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------


@dataclass
class CrossRepoTicket:
    ticket_id: str
    repos: list[
        str
    ]  # repos[0]=part1 (primary/foundational), repos[1]=part2 (dependent)
    ordering_rationale: str  # human-readable, required


@dataclass
class DecompositionResult:
    assignments: dict[str, list[str]]  # repo_name → [ticket_ids]
    cross_repo: list[CrossRepoTicket]
    unmatched: list[str]
    ticket_scores: dict[str, dict]  # every ticket, always populated


# ---------------------------------------------------------------------------
# Manifest loading
# ---------------------------------------------------------------------------


def _load_manifest(manifest_path: str) -> tuple[int, list[dict]]:
    """Load repo_manifest.yaml and return (MIN_TOP_SCORE, repos list)."""
    data = yaml.safe_load(Path(manifest_path).read_text())
    min_top_score: int = int(data.get("MIN_TOP_SCORE", 4))
    repos: list[dict] = data.get("repos", [])
    return min_top_score, repos


# ---------------------------------------------------------------------------
# Label parsing helpers
# ---------------------------------------------------------------------------


def _parse_labels(labels: list[str]) -> dict[str, list[str]]:
    """Parse label strings into a dict of {prefix: [values]}."""
    parsed: dict[str, list[str]] = {}
    for label in labels:
        if ":" in label:
            prefix, _, value = label.partition(":")
            parsed.setdefault(prefix, []).append(value)
        else:
            parsed.setdefault(label, []).append("")
    return parsed


# ---------------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------------


def _score_ticket(ticket: dict, repos: list[dict]) -> dict[str, int]:
    """Score a ticket against all repos using keyword presence/absence (each keyword once)."""
    text = (
        (ticket.get("title") or "") + " " + (ticket.get("description") or "")
    ).lower()

    scores: dict[str, int] = {}
    for repo in repos:
        count = 0
        for keyword in set(repo.get("keywords", [])):
            if keyword.lower() in text:
                count += 1
        scores[repo["name"]] = count
    return scores


# ---------------------------------------------------------------------------
# Sanity validator
# ---------------------------------------------------------------------------


def validate_decomposition(result: DecompositionResult) -> list[str]:
    """Return list of validation errors; empty = valid."""
    errors: list[str] = []
    for cr in result.cross_repo:
        if not cr.ordering_rationale:
            errors.append(
                f"CrossRepoTicket {cr.ticket_id!r} has empty ordering_rationale"
            )
        if cr.ticket_id not in result.ticket_scores:
            errors.append(
                f"CrossRepoTicket {cr.ticket_id!r} missing from ticket_scores"
            )
        elif not result.ticket_scores[cr.ticket_id].get("ordering_rationale"):
            errors.append(
                f"ticket_scores[{cr.ticket_id!r}]['ordering_rationale'] is empty for cross-repo ticket"
            )
    return errors


# ---------------------------------------------------------------------------
# Main decomposition
# ---------------------------------------------------------------------------


def decompose_epic(tickets: list[dict], manifest_path: str) -> DecompositionResult:
    """Decompose an epic's tickets into per-repo assignments.

    Args:
        tickets: list of dicts with keys: id, title, description, labels
        manifest_path: path to repo_manifest.yaml

    Returns:
        DecompositionResult with assignments, cross_repo, unmatched, and ticket_scores
    """
    min_top_score, repos = _load_manifest(manifest_path)

    repo_names = {r["name"] for r in repos}
    repo_precedence = {r["name"]: r.get("precedence", 999) for r in repos}

    assignments: dict[str, list[str]] = {r["name"]: [] for r in repos}
    cross_repo: list[CrossRepoTicket] = []
    unmatched: list[str] = []
    ticket_scores: dict[str, dict] = {}

    for ticket in tickets:
        tid = ticket["id"]
        labels: list[str] = ticket.get("labels", [])
        parsed = _parse_labels(labels)

        # ----------------------------------------------------------------
        # Priority 1: explicit part1:repo + part2:repo (both required)
        # ----------------------------------------------------------------
        if "part1" in parsed and "part2" in parsed:
            p1_repo = parsed["part1"][0]
            p2_repo = parsed["part2"][0]
            rationale = f"Explicit label override: part1={p1_repo}, part2={p2_repo}"
            cross_repo.append(
                CrossRepoTicket(
                    ticket_id=tid,
                    repos=[p1_repo, p2_repo],
                    ordering_rationale=rationale,
                )
            )
            ticket_scores[tid] = {
                "decision": "cross-repo",
                "top_repo": p1_repo,
                "top_score": None,
                "second_repo": p2_repo,
                "second_score": None,
                "candidates_top3": [],
                "ordering_rationale": rationale,
            }
            continue

        # ----------------------------------------------------------------
        # Priority 2: multi-repo:repo1,repo2 label
        # ----------------------------------------------------------------
        if "multi-repo" in parsed:
            value = parsed["multi-repo"][0]
            if not value:
                # Bare multi-repo → unmatched
                unmatched.append(tid)
                ticket_scores[tid] = {
                    "decision": "unmatched",
                    "top_repo": None,
                    "top_score": None,
                    "second_repo": None,
                    "second_score": None,
                    "candidates_top3": [],
                    "ordering_rationale": "bare multi-repo label with no repos specified",
                }
                continue
            repo_parts = [r.strip() for r in value.split(",")]
            if len(repo_parts) >= 2:
                p1, p2 = repo_parts[0], repo_parts[1]
                rationale = (
                    f"multi-repo label: {value} (label order determines part ordering)"
                )
                cross_repo.append(
                    CrossRepoTicket(
                        ticket_id=tid,
                        repos=[p1, p2],
                        ordering_rationale=rationale,
                    )
                )
                ticket_scores[tid] = {
                    "decision": "cross-repo",
                    "top_repo": p1,
                    "top_score": None,
                    "second_repo": p2,
                    "second_score": None,
                    "candidates_top3": [],
                    "ordering_rationale": rationale,
                }
                continue
            else:
                # Only one repo in multi-repo → treat as unmatched
                unmatched.append(tid)
                ticket_scores[tid] = {
                    "decision": "unmatched",
                    "top_repo": None,
                    "top_score": None,
                    "second_repo": None,
                    "second_score": None,
                    "candidates_top3": [],
                    "ordering_rationale": f"multi-repo label has only one repo: {value}",
                }
                continue

        # ----------------------------------------------------------------
        # Priority 3: depends-on:repo label
        # ----------------------------------------------------------------
        if "depends-on" in parsed:
            dep_repo = parsed["depends-on"][0]
            # Score to find the primary repo (not the dependency)
            scores = _score_ticket(ticket, repos)
            # Remove dep_repo from candidates for primary
            primary_candidates = {
                name: score for name, score in scores.items() if name != dep_repo
            }
            if primary_candidates:
                primary_repo = max(
                    primary_candidates,
                    key=lambda r: (primary_candidates[r], -repo_precedence.get(r, 999)),
                )
            else:
                # No other repo — fall back to unmatched
                unmatched.append(tid)
                rationale = f"depends-on:{dep_repo} but no other repo matched"
                ticket_scores[tid] = {
                    "decision": "unmatched",
                    "top_repo": dep_repo,
                    "top_score": None,
                    "second_repo": None,
                    "second_score": None,
                    "candidates_top3": [],
                    "ordering_rationale": rationale,
                }
                continue
            rationale = (
                f"depends-on label: {dep_repo} is part2 (dependent); "
                f"{primary_repo} is part1 (primary)"
            )
            cross_repo.append(
                CrossRepoTicket(
                    ticket_id=tid,
                    repos=[primary_repo, dep_repo],
                    ordering_rationale=rationale,
                )
            )
            ticket_scores[tid] = {
                "decision": "cross-repo",
                "top_repo": primary_repo,
                "top_score": scores.get(primary_repo),
                "second_repo": dep_repo,
                "second_score": scores.get(dep_repo),
                "candidates_top3": [],
                "ordering_rationale": rationale,
            }
            continue

        # ----------------------------------------------------------------
        # Priority 4: single exact label match to repo name
        # ----------------------------------------------------------------
        exact_matches = [lbl for lbl in labels if lbl in repo_names]
        if len(exact_matches) == 1:
            matched_repo = exact_matches[0]
            assignments[matched_repo].append(tid)
            ticket_scores[tid] = {
                "decision": "assigned",
                "top_repo": matched_repo,
                "top_score": None,
                "second_repo": None,
                "second_score": None,
                "candidates_top3": [{"repo": matched_repo, "score": None}],
                "ordering_rationale": f"exact label match to repo name: {matched_repo}",
            }
            continue

        # ----------------------------------------------------------------
        # Priority 5: keyword scoring
        # ----------------------------------------------------------------
        scores = _score_ticket(ticket, repos)

        # Build sorted candidates (score DESC, precedence ASC)
        sorted_repos = sorted(
            repos,
            key=lambda r: (-scores[r["name"]], r.get("precedence", 999)),
        )

        if not sorted_repos:
            unmatched.append(tid)
            ticket_scores[tid] = {
                "decision": "unmatched",
                "top_repo": None,
                "top_score": 0,
                "second_repo": None,
                "second_score": None,
                "candidates_top3": [],
                "ordering_rationale": "no repos in manifest",
            }
            continue

        top3 = [
            {"repo": r["name"], "score": scores[r["name"]]} for r in sorted_repos[:3]
        ]

        top_repo = sorted_repos[0]["name"]
        top_score = scores[top_repo]

        if top_score == 0:
            # No keyword matches → unmatched
            unmatched.append(tid)
            ticket_scores[tid] = {
                "decision": "unmatched",
                "top_repo": top_repo,
                "top_score": top_score,
                "second_repo": sorted_repos[1]["name"]
                if len(sorted_repos) > 1
                else None,
                "second_score": scores.get(sorted_repos[1]["name"])
                if len(sorted_repos) > 1
                else None,
                "candidates_top3": top3,
                "ordering_rationale": "no keyword matches found",
            }
            continue

        second_repo = sorted_repos[1]["name"] if len(sorted_repos) > 1 else None
        second_score = scores[second_repo] if second_repo is not None else None

        # MIN_TOP gate: if below threshold, assign regardless of ratio
        if top_score < min_top_score:
            assignments[top_repo].append(tid)
            ticket_scores[tid] = {
                "decision": "assigned",
                "top_repo": top_repo,
                "top_score": top_score,
                "second_repo": second_repo,
                "second_score": second_score,
                "candidates_top3": top3,
                "ordering_rationale": (
                    f"top_score {top_score} < MIN_TOP_SCORE {min_top_score}; "
                    f"assigned to {top_repo} on weak evidence"
                ),
            }
            continue

        # Cross-repo split check: second_score >= 0.8 * top_score
        if second_repo is not None and second_score >= 0.8 * top_score:
            rationale = (
                f"keyword scores close: {top_repo}={top_score}, "
                f"{second_repo}={second_score} (ratio={second_score / top_score:.2f} >= 0.8); "
                f"ordered by (score DESC, precedence ASC)"
            )
            cross_repo.append(
                CrossRepoTicket(
                    ticket_id=tid,
                    repos=[top_repo, second_repo],
                    ordering_rationale=rationale,
                )
            )
            ticket_scores[tid] = {
                "decision": "cross-repo",
                "top_repo": top_repo,
                "top_score": top_score,
                "second_repo": second_repo,
                "second_score": second_score,
                "candidates_top3": top3,
                "ordering_rationale": rationale,
            }
        else:
            # Top scorer wins clearly
            assignments[top_repo].append(tid)
            rationale = f"keyword scoring: {top_repo}={top_score}" + (
                f", {second_repo}={second_score} (ratio={second_score / top_score:.2f} < 0.8)"
                if second_repo is not None and top_score > 0
                else ""
            )
            ticket_scores[tid] = {
                "decision": "assigned",
                "top_repo": top_repo,
                "top_score": top_score,
                "second_repo": second_repo,
                "second_score": second_score,
                "candidates_top3": top3,
                "ordering_rationale": rationale,
            }

    # Validate and fail-fast
    errors = validate_decomposition(
        DecompositionResult(
            assignments=assignments,
            cross_repo=cross_repo,
            unmatched=unmatched,
            ticket_scores=ticket_scores,
        )
    )
    if errors:
        raise ValueError("decompose_epic validation failed:\n" + "\n".join(errors))

    return DecompositionResult(
        assignments=assignments,
        cross_repo=cross_repo,
        unmatched=unmatched,
        ticket_scores=ticket_scores,
    )
