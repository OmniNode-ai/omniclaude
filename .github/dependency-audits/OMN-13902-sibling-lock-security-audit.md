# OMN-13902 Sibling Lock Security Audit

PR: OmniNode-ai/omniclaude#2188

Changed package:

- `omnibase-infra`: `0.38.26` to `0.38.27`

## First-Party Source Readback

`omnibase-infra` is a first-party OmniNode package. The locked version
corresponds to the published GitHub release:

- release: `https://github.com/OmniNode-ai/omnibase_infra/releases/tag/v0.38.27`
- published at: `2026-09-15T01:38:28Z`
- tag: `v0.38.27`
- tag target commit: `00d4d4bd8c4f47cc11b67eb006ee618c45dc65da`
- target commit subject: `chore(OMN-17802): pin omnibase-core 0.47.14 and cut the omnibase-infra release omnimarket needs (#3553)`
- previous release commit checked for comparison: `v0.38.26^{}` =
  `45bb2fd1161da06dfa4970425332e7edd52e7755`

Source diff scope from `v0.38.26^{}` to `v0.38.27^{}`:

- 24 changed files under `.github`, `pyproject.toml`, `uv.lock`, `src`, and
  `tests`
- 3166 insertions and 98 deletions
- release PR: `OmniNode-ai/omnibase_infra#3553`

The changed source areas are release pinning, drift/receipt CLI handling,
topic suffix exports, runtime compatibility, workflow checks, and matching
tests. This sibling lock refresh does not change omniclaude source code.

## Artifact Integrity

The `uv.lock` entries point to PyPI artifacts whose downloaded SHA-256 hashes
match the lock exactly:

- sdist URL:
  `https://files.pythonhosted.org/packages/7c/50/3a07ec6b5643d1b118cd92a40326a9cce6a65f9603d9e54273321c1aa9a9/omnibase_infra-0.38.27.tar.gz`
- sdist hash:
  `sha256:bb99289c98cdccd779c3353ade0e3518d1cf0a31a00ee2177b964e2fcc1c4570`
- wheel URL:
  `https://files.pythonhosted.org/packages/e2/0e/12a93c01abb35c4a0d2cd1da819e21c6b97fbaf50cfb2214f441f78b42a4/omnibase_infra-0.38.27-py3-none-any.whl`
- wheel hash:
  `sha256:cf902d35e47b9c2b48c0f37bb22cb6f12d44b6b57fa8a7f48dba740c6979dd84`
- PyPI upload times: wheel `2026-09-15T01:38:15.743Z`; sdist
  `2026-09-15T01:38:18.073Z`

Verification command:

```bash
artifact_dir=/tmp/omniclaude-2188-artifacts-$(date +%s)
mkdir -p "$artifact_dir"
curl -fsSL 'https://files.pythonhosted.org/packages/7c/50/3a07ec6b5643d1b118cd92a40326a9cce6a65f9603d9e54273321c1aa9a9/omnibase_infra-0.38.27.tar.gz' -o "$artifact_dir/omnibase_infra-0.38.27.tar.gz"
curl -fsSL 'https://files.pythonhosted.org/packages/e2/0e/12a93c01abb35c4a0d2cd1da819e21c6b97fbaf50cfb2214f441f78b42a4/omnibase_infra-0.38.27-py3-none-any.whl' -o "$artifact_dir/omnibase_infra-0.38.27-py3-none-any.whl"
shasum -a 256 "$artifact_dir/omnibase_infra-0.38.27.tar.gz" "$artifact_dir/omnibase_infra-0.38.27-py3-none-any.whl"
```

Observed hash output:

```text
bb99289c98cdccd779c3353ade0e3518d1cf0a31a00ee2177b964e2fcc1c4570  omnibase_infra-0.38.27.tar.gz
cf902d35e47b9c2b48c0f37bb22cb6f12d44b6b57fa8a7f48dba740c6979dd84  omnibase_infra-0.38.27-py3-none-any.whl
```

Archive shape readback:

- sdist opened successfully and contains 7524 files.
- wheel opened successfully and contains 3225 files.
- wheel contains a `.dist-info/RECORD` manifest.

## Advisory Scan

Audit command:

```bash
uv export --format requirements-txt --no-hashes --output-file /tmp/omniclaude-2188-requirements.txt
uvx pip-audit -r /tmp/omniclaude-2188-requirements.txt --skip-editable --disable-pip --no-deps --progress-spinner off --format json --output /tmp/omniclaude-2188-pip-audit.json
jq -r '.dependencies[] | select(.name=="omnibase-infra") | {name,version,vulns}' /tmp/omniclaude-2188-pip-audit.json
```

Audit result for the changed package:

```json
{
  "name": "omnibase-infra",
  "version": "0.38.27",
  "vulns": []
}
```

The full lock audit returned existing advisories in unchanged transitive
packages: `h2==4.3.0`, `idna==3.11`, `kafka-python==2.3.0`, `mako==1.3.11`,
`tuf==6.0.0`, and `urllib3==2.6.3`. The PR lock delta is limited to
`omnibase-infra`; those advisory-bearing package versions are not changed by
this sibling lock refresh.
