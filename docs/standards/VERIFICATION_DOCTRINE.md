# Verification Doctrine

> Source audit: `omni_home/docs/audits/2026-06-19-ratchet-enforcement-audit.md`.

A claim about system state — "the node exists", "the check passed", "escalation
never fires", "the PR is green" — is only true if it is verified against an
**authoritative, live truth surface**. Local clones, ticket prose, and
`statusCheckRollup` are convenient but they **drift from live truth**, and acting
on drifted evidence produces confident-but-wrong conclusions.

This doctrine codifies which surfaces are authoritative, which are not, and the
exact commands to use. It is enforced by the `verification-evidence-lint` gate
(see [Enforcement](#enforcement)).

---

## Why this exists (three observed failures, one session)

Every rule below was written against a real failure on 2026-06-19, documented in
the ratchet-enforcement audit:

1. **Stale local clone produced a false `node NOT_FOUND`.** A probe checked a
   local canonical clone that was behind `origin/dev`; the node existed on the
   live branch. The clone, not the platform, was wrong.
2. **Stale ticket text said "escalation never fires."** The materialized
   projection `projection_delegation_model_routing.decision_traces` showed
   escalation re-dispatching up-tier (corr `11880229` → `gemini-2.5-flash-lite`,
   corr `31c0cf4e` → `glm-4.5`). The ticket prose was outdated narrative, not
   current truth.
3. **`statusCheckRollup` reported `FAILURE` after passing reruns.** The rollup
   summary cached a stale terminal state; `gh pr checks` against the live run set
   reported the true (green) state.

In all three the evidence source was *easy to reach* and *wrong*. The doctrine
forces the harder, correct source.

---

## Authoritative truth surfaces (verify against these)

| Question | Authoritative surface | Command |
|----------|----------------------|---------|
| Does a file / node / symbol exist on the branch? | `origin/dev` (the live remote branch), never a local clone | `git fetch origin dev && git show origin/dev:<path>` or `git ls-tree origin/dev <path>` |
| What is the current runtime / data state? | The **live materialized projection** (durable control-plane authority) | `docker exec <pg-container> psql -U postgres -d omnidash_analytics -c 'SELECT ... FROM projection_<name>'` (or the projection HTTP API) |
| Did a PR's checks pass? | The live run set via `gh pr checks` | `gh pr checks <num> --repo OmniNode-ai/<repo>` |
| Is a check a **required** gate (not merely present)? | Live branch protection | `gh api repos/OmniNode-ai/<repo>/branches/dev/protection --jq '.required_status_checks.checks[]?.context'` |
| What is on the event bus right now? | The live broker (correct lane) | `rpk topic consume <topic>` against the verified lane/broker |

**Why the projection counts as truth:** per the OmniNode deterministic-truth
doctrine, a materialized projection is a durable control-plane surface produced
by deterministic replay of the event log. It is an *authority*, not a *cache*.
A stale local clone and an outdated ticket are neither.

---

## Non-authoritative surfaces (never assert state from these)

| Surface | Failure mode | Use it only for |
|---------|-------------|-----------------|
| **Local canonical clone** (`omni_home/<repo>/`) | Drifts behind `origin/dev` between `pull-all.sh` runs; "file/node missing" is usually "clone stale" | Reading code you then re-verify against `origin/dev`; never as proof a thing is absent |
| **Ticket text / prose** (Linear description, handoff narrative) | Frozen at write time; describes intent or a past state, not current truth | Intent and history; never as proof of current behavior |
| **`statusCheckRollup`** (`gh pr view --json statusCheckRollup`) | Caches a stale terminal state; does not reflect reruns | A rough overview; never as the green/red verdict — use `gh pr checks` |
| **An agent's self-report** ("done", "tests pass") | Agents claim success they did not achieve (CLAUDE.md Rule #3) | Nothing load-bearing; re-verify via `gh pr checks` |

If the only evidence for a claim is one of these surfaces, the claim is
**unverified**. State it as inference or speculation, or go get the
authoritative surface.

---

## The rules

1. **Existence claims verify against `origin/dev`, not a local clone.** Run
   `git fetch origin dev` first, then read from `origin/dev:<path>`. A local
   clone may be behind. "NOT_FOUND" against a stale clone is not evidence of
   absence.
2. **Runtime/data-state claims verify against the live materialized
   projection** (or the live bus on the verified lane), never against ticket
   prose or remembered behavior. Cite the exact `psql`/`rpk` command and its
   output.
3. **PR check verdicts use `gh pr checks <num>`, never `statusCheckRollup`.**
   The rollup caches stale state. `gh pr checks` reads the live run set.
4. **"Required gate" claims verify against live branch protection.** A workflow
   file or pre-commit hook existing is *not* the same as it being a required
   status check. Probe `branches/dev/protection`; where inventory and
   required-checks disagree, the required-checks probe wins.
5. **Verifier ≠ runner.** The agent that produced an artifact does not get to
   attest its own success. A separate probe, with `probe_stdout`, attests it
   (CLAUDE.md Rule #3; memory `feedback_adversarial_receipts`).
6. **Cite the command and its output, not a conclusion.** "CI is green" is a
   conclusion. `gh pr checks 1781 --repo OmniNode-ai/omniclaude` plus its output
   is evidence. Worker prompts and receipts must carry the command, not just the
   verdict.

---

## Quick reference (copy-paste)

```bash
# Existence on the live branch (NOT a local clone)
git fetch origin dev --quiet
git ls-tree origin/dev <path>            # listed = exists on dev
git show origin/dev:<path>               # contents on dev

# PR check verdict (NOT statusCheckRollup)
gh pr checks <num> --repo OmniNode-ai/<repo>

# Required-gate verification (presence != required)
gh api repos/OmniNode-ai/<repo>/branches/dev/protection \
  --jq '.required_status_checks.checks[]?.context'

# Live runtime/data state (projection = durable authority)
docker exec <pg-container> psql -U postgres -d omnidash_analytics \
  -c 'SELECT <cols> FROM projection_<name>'

# Live bus state on the verified lane
rpk topic consume <topic>                # confirm lane/broker first
```

---

## Enforcement

A pre-commit hook and CI gate (`verification-evidence-lint`) flag worker prompts,
receipts, and handoff/evidence docs that cite a **local-clone path** or
**ticket text** as proof of state, or that use `statusCheckRollup` as a PR
verdict. The gate is blocking — advisory checks get ignored (CLAUDE.md Rule #5).

- Lint script: `scripts/lint_verification_evidence.py`
- Pre-commit hook id: `lint-verification-evidence`
- CI workflow: `.github/workflows/verification-evidence-lint.yml`
- Suppression (per line, with a real reason): `# verification-evidence-ok: <reason>`

The lint does not (and cannot) verify that you actually *ran* the authoritative
command — that is a human/review judgment. What it mechanically prevents is the
regression of writing "verified against the local clone" or "the ticket says X,
so X" or "statusCheckRollup shows PASS" into a prompt or receipt as if it were
proof.

---

## References

- Audit: `omni_home/docs/audits/2026-06-19-ratchet-enforcement-audit.md`
- CLAUDE.md Rule #3 (verify via `gh pr checks`, never agent self-reports)
- CLAUDE.md Rule #5 (enforcement, not detection)
- OmniNode deterministic-truth doctrine (`omni_home/docs/standards/OMNINODE_DETERMINISTIC_TRUTH_DOCTRINE.md`)
- Memory: `feedback_check_remote_before_stall`, `feedback_adversarial_receipts`,
  `feedback_use_local_git_not_github_api`
