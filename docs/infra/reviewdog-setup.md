# Reviewdog Integration Setup

## Overview

Reviewdog posts inline PR annotations and code suggestions from linters (ruff, mypy)
and security scanners (Trivy, Bandit). It runs as a reusable GitHub Actions workflow
in omniclaude, consumed by all OmniNode repos.

## PAT Secret: REVIEWDOG_PAT

### Required Permissions (fine-grained PAT)

- **Resource owner:** OmniNode-ai
- **Repository access:** All repositories
- **Permissions:**
  - Pull requests: Read and write (post review comments)
  - Contents: Read (read PR diff)

### Setup Steps

1. Generate fine-grained PAT: https://github.com/settings/tokens?type=beta
2. Add as org-level Actions secret:
   - Go to: OmniNode-ai → Settings → Secrets and variables → Actions
   - Click "New organization secret"
   - Name: `REVIEWDOG_PAT`
   - Value: paste the generated token
   - Access: All repositories

### Why not GITHUB_TOKEN?

We use `REVIEWDOG_PAT` because `github-pr-review` suggestion behavior is more
reliable with a PAT across OmniNode repos. The built-in `GITHUB_TOKEN` has limited
ability to post review comments with suggestion blocks depending on workflow
trigger and permission configuration.

On `merge_group` events and fork PRs, the workflow automatically falls back to
`github-pr-check` reporter which uses `GITHUB_TOKEN` — no PAT needed.

## Adding Reviewdog to a New Repo

Copy this caller workflow to `<repo>/.github/workflows/reviewdog.yml`:

```yaml
name: reviewdog
on:
  pull_request:
    types: [opened, synchronize, reopened]
  merge_group:

jobs:
  reviewdog:
    uses: OmniNode-ai/omniclaude/.github/workflows/reviewdog-review.yml@main
    with:
      src-dir: "src/"
      ruff-enabled: true       # false for non-Python repos
      mypy-enabled: true       # false for non-Python repos
      security-enabled: true
      fail-level: "error"
      # install-command: ""    # override if repo uses custom install
      # working-directory: "." # override if monorepo
    secrets:
      REVIEWDOG_PAT: ${{ secrets.REVIEWDOG_PAT }}
```

Note: REVIEWDOG_PAT is optional. On `merge_group` and fork PR events, the workflow
uses `GITHUB_TOKEN` automatically. The PAT is required only for `github-pr-review`
mode (ruff suggestions) on trusted PRs — the workflow fails clearly if missing.

## Reporter Behavior

| Event | Scanner | Reporter | Suggestions? | Token |
|-------|---------|----------|--------------|-------|
| `pull_request` (trusted) | ruff | `github-pr-review` | Yes (one-click accept) | REVIEWDOG_PAT |
| `pull_request` (trusted) | mypy/trivy/bandit | `github-pr-check` | No (annotations only) | REVIEWDOG_PAT |
| `pull_request` (fork) | all | `github-pr-check` | No (annotations only) | GITHUB_TOKEN |
| `merge_group` | all | `github-pr-check` | No (annotations only) | GITHUB_TOKEN |
