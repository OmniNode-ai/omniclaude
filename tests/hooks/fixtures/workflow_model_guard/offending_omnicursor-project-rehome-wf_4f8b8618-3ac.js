agent(`Linear-only lane. Operator ruling (paraphrase, never quote): cursor-team work does NOT belong in the beta sprint — it gets its own project. Earlier today six cursor-closure tickets were placed into project 'Sprint 2026-09-07 → 2026-09-13' by mistake.

1. FIND the right project: list Linear projects matching cursor/omnicursor. If a live OmniCursor project exists, use it. If none, CREATE one: name 'OmniCursor', team Omninode, description one line ('Cursor plugin: never-loaded-plugin fix set, measurement parity, producer hardening — external contractor track'), no dates.
2. MOVE these tickets into it (removing them from the sprint project): OMN-17479 (tracking parent — check whether it was ever put in the sprint; move it to the project regardless), OMN-16597, OMN-16596, OMN-16598, OMN-17480, OMN-17481, OMN-17482. OMN-17481 lives under parent OMN-14749 — keep that parent link, just set the project. Do NOT change states, priorities, assignees, or parents — project field only.
3. Verify each move by re-reading the ticket (project field) — the earlier lane's saves were trusted; this one confirms by readback.
4. One comment on OMN-17479 only (not all seven): cursor-track work is homed in this project and stays out of the beta sprint per operator direction (professional paraphrase).

RETURN: project (name + id, found-or-created), moved (ticket ids with readback confirmation), notes.`, { label: 'cursor-rehome', phase: 'Rehome tickets', schema: SCHEMA })
