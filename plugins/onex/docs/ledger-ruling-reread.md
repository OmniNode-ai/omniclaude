# Re-read ledger rulings before publishing

The Git effect admission handler re-reads the ledger before a lane's `git push`
or `gh pr merge` (including automatic merge requests). It surfaces **every**
RULING timestamped after the lane's latest CLAIM and refuses publishing until
the lane acknowledges each ruling in the ledger. The registered Bash guard and
`HandlerGitSubprocess` use the same check.

`ONEX_LANE` (or `ONEX_LANE_ID`) identifies the executing lane;
`ONEX_LEDGER_PATH` identifies its ledger; `ONEX_STATE_DIR` stores the journal.
A lane with missing state, an unreadable ledger, or no CLAIM is refused.
Read-only commands do not trigger this check.

Before push or merge, **re-read the ledger for RULING rows appended after CLAIM**.
Apply each ruling. Append an ACK through the existing ledger writer, with your
lane in both `lane=` and `from=`, the ruling's author in `to=`, and copy the refusal's `re=`, `ruling=` and
`ruling-sha256=` cells exactly. The ACK needs its own timestamp and id and must
postdate the ruling. `re=` is the ruling's id, when present, or its timestamp.
`ruling=` is the surfaced file-and-line citation; the SHA-256 pins the entire
surfaced row. A prose assertion that it was read is insufficient.

The ACK records reading and applying the ruling. It grants no permission to
disregard it. Other admission checks continue to apply after acknowledgement.

The check reads live rows and archive rolls. Its locked, append-only journal
at `hooks/ruling-reread.jsonl` under the state directory retains first-seen
text, digest and citation. Once surfaced, an edited, deleted or rolled ruling
remains pending until its exact ACK is present. A fresh CLAIM cannot erase an
observed pending ruling, and removing an ACK reinstates the refusal. The
journal stores observations, never an acknowledged/ignore flag. There is no
per-lane or per-ticket exemption, suppression flag, or journal-clear command.

This protects the hook and Git effect handler seams; it does not intercept
commands issued outside those seams or prove compliance with a ruling's prose.
The journal assumes the existing trusted state directory. A ruling deleted
before its first read cannot be reconstructed from the surviving ledger.

`tests/hooks/test_ledger_ruling_reread.py` exercises refusal and positive
controls through the actual adapter and handler, archive retention, durable ACKs,
tampering, corruption and the instruction in dispatched worker prompts. It
runs in pre-commit and the fail-closed CI job.
