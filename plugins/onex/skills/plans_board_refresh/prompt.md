# Plans board refresh — one process, one readback

```
/onex:plans_board_refresh [--intent quiet|normal|tick] [--dry-run]
```

| Argument | Type |
|----------|------|
| `--intent` | string |
| `--dry-run` | boolean, flag |

1. Resolve the overlay: `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/resolve_skill_overlay.py" plans_board_refresh`.
   It tries `PLANS_BOARD_REFRESH_OVERLAY_PATH`, then each root in
   `ONEX_SKILL_OVERLAY_ROOTS`. A non-zero exit is a hard stop: report its
   standard error, which names every location tried, and stop. Do not guess a generator.
2. Run the session preflight at the given intent. A blocker stops the run.
3. Read the board's published timestamp through the overlay's `board_locator`
   and record it as the **before** value.
4. Run the overlay's `generator_command` from its `working_directory`. With
   `--dry-run`, stop here and report what would have run.
5. Read the timestamp again and record it as the **after** value.

## Present the result

Report, in this order:

- **Verdict** — `advanced` or `stalled`.
- **Before / after** — both timestamps, and the delta.
- **Generator output** — the tail of the run, surfaced directly.

`stalled` means the generator exited zero and published nothing. Report it as a
failure with the two timestamps attached. Do not report the generator's exit
code as the verdict.
