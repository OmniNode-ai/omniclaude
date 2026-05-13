# Reviewdog Proof of Life — OMN-10938

**Status:** PENDING — awaiting prerequisite PR merges

## What this PR verifies

`src/omniclaude/_reviewdog_test.py` is a new file introduced in this PR.
The file is intentionally clean (passes all pre-commit hooks), but its presence
in the PR diff triggers the reviewdog workflow. The check runs appearing in the
PR status checks — even with zero findings — proves the plumbing is wired correctly:

- ruff converter (`ruff-to-rdjsonl.py`) ran and produced output
- mypy converter (`mypy-to-rdjsonl.py`) ran and produced output
- reviewdog posted all check runs to the PR
- trivy and bandit security scans completed

Zero annotations on a clean file is the expected and correct outcome for this PR.
A separate PR with an intentional violation can be used to verify annotation rendering
once the plumbing is confirmed live.

## Prerequisites (must merge first)

- [ ] PR #1575 (OMN-10929): `reviewdog-review.yml` reusable workflow
- [ ] PR #1580 (OMN-10930): `ruff-to-rdjsonl.py` converter
- [ ] PR #1581 (OMN-10931): `mypy-to-rdjsonl.py` converter
- [ ] PR #1582 (OMN-10936): `reviewdog-caller.yml` in omniclaude

## Verification Checklist (complete after prereqs merge and PR opened)

- [ ] PR opened from branch `test/omn-10938-reviewdog-proof-of-life`
- [ ] Check run named `ruff` appears in PR checks (pass, 0 findings)
- [ ] Check run named `mypy` appears in PR checks (pass, 0 findings)
- [ ] Check run named `trivy-security` appears in PR checks
- [ ] Check run named `bandit-security` appears in PR checks
- [ ] No spurious annotations on unchanged files
- [ ] Workflow run URL captured below

## Evidence (populate after verification)

- PR URL: (pending — open after #1575, #1580, #1581, #1582 merge)
- Workflow run URL: (pending)
- Date completed: 2026-05-13
