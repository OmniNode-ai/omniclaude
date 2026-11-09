---
description: Bootstrap skill for running a plan through a set of reviewers, ending with Fable 5.2 as the final reviewer, whose only output is a unified diff against the plan file. Use when asked to review a plan, run a plan review set, or get a plan ready to show. No node replaces it yet; replace it if the review set is built as a node.
mode: full
version: 1.0.0
level: basic
debug: false
category: process
bootstrap: true
skill_kind: methodology
tags:
  - planning
  - review
  - bootstrap
author: omninode
---

# Plan review set

A plan is reviewed in rounds. The earlier reviewers find problems and the author fixes them. The last reviewer is the strongest model, and it does not write a critique: it writes the fix itself, as a unified diff against the plan file, so every change it wants is exact and can be applied or refused hunk by hunk.

## Before you start

You need the plan as a committed file in a git worktree, so a diff has a base. If the plan exists only as a page, copy its source into the worktree first.

Confirm the final reviewer's model id from the session environment. Do not guess it. If the environment does not list Fable 5.2, or a dispatch guard refuses it, stop and say which of the two blocked; never substitute another model for the final pass.

## Round 1: find problems

Send the plan to the first reviewers, for example Codex at high effort, Sonnet and Opus. Give each reviewer the plan and the rules it must fit (contracts, nodes and overlays, no new scripts, no hard-coded values), and ask for findings only: what is wrong, unbuildable, untestable, missing, or contradicts a decision already made, each with the line it concerns. Not a rewrite.

## Round 2: fix

Fix every finding you agree with in the plan file, and write down the ones you reject with a one-line reason. Commit. A finding that needs a decision only the plan's owner can make stays in the plan as an open decision; do not decide it yourself.

Repeat rounds 1 and 2 until a round returns no finding you agree with. Two rounds is usual.

## Final round: Fable 5.2, diffs only

Send Fable 5.2 the committed plan file with its path, and these instructions, word for word:

> You are the final reviewer of this plan. Do not write a review, a summary or any explanation. Return only a unified diff against the file at the given path that fixes every problem you find: wrong facts, steps that cannot be built or tested, missing acceptance checks, contradictions, unclear wording. If the plan needs no change, return an empty diff. Each hunk must apply cleanly to the file as given. Nothing outside the diff.

## Apply

Check the diff with `git apply --check`. Apply the hunks you agree with, refuse the others, and commit with a message that lists which hunks were applied and which refused and why. A hunk that does not apply is refused, never hand-edited into shape and passed off as the reviewer's.

## Report

Show the plan's owner the plan as a rendered page link, not the plan text. With the link give: the reviewers and rounds run, the number of findings fixed and rejected, the final reviewer's hunks applied and refused, and any open decision the plan still holds.
