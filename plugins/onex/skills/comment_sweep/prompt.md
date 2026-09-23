# Comment sweep — read only, draft to files, control every zero

```
/onex:comment_sweep [--intent quiet|normal|tick] [--since <duration>] [--dry-run]
```

| Argument | Type |
|----------|------|
| `--intent` | string |
| `--since` | string |
| `--dry-run` | boolean, flag |

1. Resolve the overlay: `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/resolve_skill_overlay.py" comment_sweep`.
   It tries `COMMENT_SWEEP_OVERLAY_PATH`, then each root in
   `ONEX_SKILL_OVERLAY_ROOTS`. A non-zero exit is a hard stop: report its
   standard error, which names every location tried, and stop.
2. Run the session preflight at the given intent. A tracker-connectivity blocker
   stops the sweep — do not sweep a tracker you could not reach.
3. Run `tracker_read_command` over the window from `--since`, defaulting to the
   overlay's `cadence`. Do not redirect standard error away.
4. Run `positive_control_command` in the same pass, whatever the first result
   was.
5. Write one draft file per comment awaiting a reply, into `draft_directory`.
   With `--dry-run`, list the drafts that would be written and write none.

## Present the result

| Line | What it carries |
|------|-----------------|
| Rows found | the count, and the window it covers |
| Positive control | the control's row count — a zero here invalidates the sweep |
| Write calls | the count of writes made against the tracker; it is zero |
| Drafts | one path per draft written |

Report a zero-row sweep as **`zero, control passed`** or **`zero, control also
empty — sweep did not run`**. Those are different findings and the second one is
not good news.
