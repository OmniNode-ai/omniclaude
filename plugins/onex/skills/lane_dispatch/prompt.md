# Lane dispatch — claim first, rules injected, model named

```
/onex:lane_dispatch --brief <name> --lane <name> --model <model> [--intent quiet|normal|tick] [--dry-run]
```

| Argument | Type |
|----------|------|
| `--brief` | string, required |
| `--lane` | string, required |
| `--model` | string, required |
| `--intent` | string |
| `--dry-run` | boolean, flag |

1. Resolve the overlay: `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/resolve_skill_overlay.py" lane_dispatch`.
   It tries `LANE_DISPATCH_OVERLAY_PATH`, then each root in
   `ONEX_SKILL_OVERLAY_ROOTS`. A non-zero exit is a hard stop: report its
   standard error, which names every location tried, and stop.
2. Run the session preflight at the given intent. A blocker stops the dispatch.
3. Resolve `--brief` inside `brief_directory`. Not found is a hard stop; do not
   dispatch the closest match.
4. Read `rules_block_path` in full. Zero bytes is a hard stop.
5. Check `--lane` against the live lane set. A name already in use is a hard
   stop — the identifier is what every later row cites.
6. Append the claim row through `claim_command`, naming the lane, the ticket and
   the scope, **before** anything else is written.
7. Dispatch, with the rules block injected as text ahead of the brief, and the
   model set from `--model`.

With `--dry-run`, run steps 1 to 5 and report what would be dispatched. Append
no claim and dispatch nothing.

## Present the result

| Line | What it carries |
|------|-----------------|
| Claim | the surface and line the claim was appended at |
| Rules | the byte count injected, and the source it was read from |
| Model | the model the lane was given, verbatim |
| Brief | the brief that resolved, by name |
| Lane | the lane identifier |

A dispatch reporting zero bytes of rules, or no claim line, did not meet the
contract. Say so rather than reporting the lane as started.
