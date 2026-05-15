# OMN-10979 Security Scanner Blocking Evidence

Date: 2026-05-15
Worktree: `$OMNI_HOME/omni_worktrees/OMN-10979/omniclaude`
Base: `origin/main` at `f1ed6ee50`

## Workflow checks

- `actionlint .github/workflows/security-scan.yml`
  - Result: PASS
- `uv run python -c 'import yaml; yaml.safe_load(open(".github/workflows/security-scan.yml")); print("security-scan.yml: valid YAML")'`
  - Result: PASS
- `rg -n "continue-on-error:\s*true|soft_fail:\s*true" .github/workflows/security-scan.yml`
  - Result: no matches

## PR trigger scope

- `security-scan.yml` now runs on `pull_request`.
- PR runs execute the OMN-10979 blockers:
  - `Container Security Scan` builds the image and runs Dockle.
  - `IaC Security Scan` runs Checkov.
- PR runs skip pre-existing non-ticket container/dependency work that was not previously part of PR execution:
  - `Dependency Security Scan`
  - Trivy image SARIF scan
  - Trivy filesystem scan

## Checkov threshold validation

Command:

```bash
uvx --from checkov==3.2.527 checkov -d . \
  --framework dockerfile,github_actions \
  --soft-fail-on LOW,MEDIUM,CKV_DOCKER_2,CKV_DOCKER_3,CKV_GHA_7,CKV2_GHA_1 \
  --hard-fail-on HIGH,CRITICAL \
  --output cli \
  --quiet
```

Result: PASS, exit code 0.

Observed advisory findings remain visible:

- `CKV_DOCKER_2`
- `CKV_DOCKER_3`
- `CKV_GHA_7`
- `CKV2_GHA_1`

## Dockle threshold validation

Setup:

```bash
docker build -f deployment/Dockerfile -t omniclaude:omn-10979-scan .
```

Result: PASS, exit code 0.

Command:

```bash
/tmp/dockle --timeout 600s --exit-code 1 --exit-level fatal \
  --accept-file settings.py \
  --ignore DKL-DI-0005 \
  omniclaude:omn-10979-scan
```

Result: PASS, exit code 0.

Observed advisory findings remain visible:

- `CIS-DI-0001`
- `CIS-DI-0005`
- `CIS-DI-0006`
- `CIS-DI-0008`
- `DKL-LI-0003`
