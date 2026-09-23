# Board readback — re-read last, quote raw

```
/onex:board_readback [--intent quiet|normal|tick] [--dry-run]
```

| Argument | Type |
|----------|------|
| `--intent` | string |
| `--dry-run` | boolean, flag |

1. Resolve the overlay: `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/resolve_skill_overlay.py" board_readback`.
   It tries `BOARD_READBACK_OVERLAY_PATH`, then each root in
   `ONEX_SKILL_OVERLAY_ROOTS`. A non-zero exit is a hard stop: report its
   standard error, which names every location tried, and stop.
2. Run the session preflight at the given intent. A blocker stops the run.
3. Read the board through `board_locator`.
4. Re-read **every** input through `input_locators`, as the last action before
   landing. Record each read's raw output and the time it was taken.
5. Compare. With `--dry-run`, stop here and report the comparison.
6. Quote the raw re-read into `landing_surface` and land the change.

## Present the result

- **Verdict** — `agrees` or `diverged`, per input.
- **Re-read time** — for each input, so the reader can check it is the last act.
- **Raw output** — quoted, not summarised.

`diverged` is not a reason to regenerate and land in the same run. Report it and
stop: the refresh row owns regeneration, and running both in one pass hides
which of the two moved the board.
