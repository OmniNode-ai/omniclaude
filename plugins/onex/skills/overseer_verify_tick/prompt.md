# Overseer verify tick — name the stalled lanes, or control the zero

```
/onex:overseer_verify_tick [--intent quiet|normal|tick] [--stall-threshold-minutes <n>] [--dry-run]
```

| Argument | Type |
|----------|------|
| `--intent` | string |
| `--stall-threshold-minutes` | integer |
| `--dry-run` | boolean, flag |

1. Resolve the overlay: `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/resolve_skill_overlay.py" overseer_verify_tick`.
   It tries `OVERSEER_VERIFY_TICK_OVERLAY_PATH`, then each root in
   `ONEX_SKILL_OVERLAY_ROOTS`. A non-zero exit is a hard stop: report its
   standard error, which names every location tried, and stop.
2. Run the session preflight at the given intent.
3. Enumerate lanes with `lane_inventory_command`. Do not discard standard error.
4. For each lane, read its last write through `last_write_locator` and compute
   the age against `--stall-threshold-minutes`, defaulting to the overlay value.
5. Run `positive_control_command` in the same pass, whatever the result was.
6. Record each stall on `finding_surface`. With `--dry-run`, report and record
   nothing.

## Present the result

| Line | What it carries |
|------|-----------------|
| Lanes enumerated | the count |
| Positive control | the control's count — a zero here invalidates the tick |
| Stalled | one row per lane: its identifier and the age of its last write |
| Delta | what this tick added to or removed from the live set, or why neither |

Never report `0 stalled` on its own. Report `0 stalled, control returned <n>`, or
report that the tick did not run.
