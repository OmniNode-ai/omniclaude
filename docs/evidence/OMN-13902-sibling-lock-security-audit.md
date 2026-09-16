# OMN-13902 sibling lock security audit

PR: OmniNode-ai/omniclaude#2188

Changed package:

- `omnibase-infra`: `0.38.26` to `0.38.27`

Lock evidence:

- sdist hash: `sha256:bb99289c98cdccd779c3353ade0e3518d1cf0a31a00ee2177b964e2fcc1c4570`
- wheel hash: `sha256:cf902d35e47b9c2b48c0f37bb22cb6f12d44b6b57fa8a7f48dba740c6979dd84`
- upload time: `2026-09-15T01:38:15.743Z` for the wheel and `2026-09-15T01:38:18.073Z` for the sdist

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

The full lock audit returned existing advisories in unchanged transitive packages:
`h2==4.3.0`, `idna==3.11`, `kafka-python==2.3.0`, `mako==1.3.11`,
`tuf==6.0.0`, and `urllib3==2.6.3`. The PR lock delta is limited to
`omnibase-infra`; those advisory-bearing package versions are not changed by
this sibling lock refresh.
