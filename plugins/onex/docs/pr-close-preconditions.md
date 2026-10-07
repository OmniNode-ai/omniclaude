# PR close preconditions

OMN-19160: an explicit ownership claim is required **before the first close
attempt**. The registered PR ownership hook refuses an absent or expired claim;
it never claims a PR for the caller. A shared GitHub account is insufficient
attribution.

Before using the close template, read the ledger inbox and the active claim
list. Stop if a peer holds the target. Use the lane, run and session identity
from the executing harness for both claim and close. The claim CLI resolves
that identity using the same resolver as the hook; an arbitrary `--lane` alias
cannot establish it. When the harness supplies no identity, set `ONEX_LANE_ID`
to the lane registered in the ledger before either command.

The other guarded actions keep their existing preconditions: Linear comment
bodies start with `actor: <lane or agent> (<model>)`; background dispatches name
an explicit allowed model and a valid `ROUTE:` line; checkout follows a commit
of the affected work; worktree paths are built from the configured `OMNI_HOME`
under its sanctioned `omni_worktrees/<ticket>/<repo>` root. This guide changes
only the PR close path.

Set `pr_repo` to the explicit owner/repository, `pr_number` to the PR number,
and `close_comment` to the reviewed close reason. Run this template in the
same harness as the guarded close. `set -e` prevents the close after a refused
claim. The claim key lowercases the owner/repository to match the hook's
canonical target key. The dry-run path reports the proposed close and executes none of these
commands.

```bash
set -e
python3 "$OMNI_HOME/omniclaude/scripts/pr_claim_registry_cli.py" list
: "${pr_repo:?}"
python3 "$OMNI_HOME/omniclaude/scripts/pr_claim_registry_cli.py" claim "${pr_repo,,}#${pr_number:?}" --action close
gh pr close "${pr_number:?}" --repo "${pr_repo:?}" --comment "${close_comment:?}"
```

A missing claim produces `Missing PR claim:` as the first nonblank line,
followed immediately by the exact claim command, including `--action close`
and the target key. That remedy preserves the hook's resolved identity even
when run from another directory. Claim acquisition is an explicit attribution
act. A peer claim, malformed claim or unresolved identity still refuses.

Invalid fixtures refuse once with the documented reason: an expired claim
uses `Missing PR claim:`; a corrupt claim `exists but is unreadable or malformed`;
an unattributable caller reports `this lane has no resolvable identity`.

The adjacent `fr-pr-close-guard-lane-identity-mismatch-self-lockout` mode is
outside this change: the existing shared lane/run/session resolver and its
identity regression tests are retained. Replacing identity policy would be a
separate repair; no identity or ownership checks are relaxed here.

The message and template contract is exercised through the registered shell
entrypoint in `tests/hooks/test_pr_close_preconditions.py`. The
`pr-close-preconditions` pre-commit hook runs that file; CI's Hooks tests and
full test job also collect it. Fixtures keep claims and hook outputs in a
temporary state directory and never execute a GitHub mutation.
