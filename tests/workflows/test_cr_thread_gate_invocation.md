# Manual Smoke-Test: cr-thread-gate.yml Invocation

## Purpose

Verify that `cr-thread-gate.yml` is callable via `workflow_call` and the job name produces
the expected required-check string: `cr-thread-gate / CodeRabbit Thread Check`.

## Prerequisites

- `cr-thread-gate.yml` merged to `main` on `OmniNode-ai/omniclaude`
- A caller repo with a test PR that has at least one open CodeRabbit review thread

## Recipe

### 1. Add a minimal caller workflow to any repo under `OmniNode-ai/`

```yaml
name: Test CR Thread Gate
on:
  pull_request:
    types: [opened, synchronize, reopened]

jobs:
  cr-thread-gate:
    uses: OmniNode-ai/omniclaude/.github/workflows/cr-thread-gate.yml@main
    with:
      github-token: ${{ secrets.GITHUB_TOKEN }}
      pr-number: ${{ github.event.pull_request.number }}
```

### 2. Open a PR in the caller repo with an unresolved CR thread

Expected: the `cr-thread-gate / CodeRabbit Thread Check` check fails with
`::error:: N unresolved CodeRabbit thread(s)`.

### 3. Resolve all CR threads

Expected: re-run triggers green `cr-thread-gate / CodeRabbit Thread Check`.

### 4. Confirm required-check string

```bash
gh api repos/OmniNode-ai/<repo>/branches/main/protection \
  --jq '.required_status_checks.checks[].context' \
  | grep "cr-thread-gate / CodeRabbit Thread Check"
```

## Local jq filter verification

Run the unit-level smoke test without GitHub credentials:

```bash
bash tests/scripts/test_check_unresolved_threads.sh
```

Expected output:
```
PASS: count=1 for one unresolved CR thread
PASS: count=0 when all threads resolved
ALL TESTS PASSED
```
