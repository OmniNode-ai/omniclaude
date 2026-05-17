# design_to_plan prompt

You are executing the **design_to_plan** skill.

## Announce

Say: "I'm using the design-to-plan skill."

## Parse arguments

Extract from `$ARGUMENTS`:

- `--phase <brainstorm|plan|launch>` — default: brainstorm
- `--topic <text>` — topic for Phase 1 (default: prompt user)
- `--plan-path <path>` — existing plan file (skip to Phase 2 or 3)
- `--no-launch` — default: false

## Dispatch

```bash
uv run onex run-node node_design_to_plan --input '{
  "phase": "<phase>",
  "topic": "<topic or null>",
  "plan_path": "<path or null>",
  "no_launch": <bool>
}'
```

If the command exits non-zero, stop and surface the error directly. Do not produce prose.

## Error handling

- Never run brainstorming, plan generation, or adversarial review inline.
- On routing failure, raise `SkillRoutingError`; do not fall back.
