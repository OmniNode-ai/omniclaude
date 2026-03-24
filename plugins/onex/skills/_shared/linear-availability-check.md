# Linear MCP Availability Check

> Referenced by: executing_plans, design_to_plan. To use this pattern, read this file
> and apply the check at the appropriate point in your skill's flow.

## Quick Check (add to any skill that calls `mcp__linear-server__*`)

Before calling any `mcp__linear-server__*` tool, verify availability:

1. Call `mcp__linear-server__list_teams` (fast, read-only, minimal data)
2. If it returns data: Linear is available — proceed normally
3. If it fails or times out: Linear is unavailable — enter local mode or fail with a clear message

## Local Mode Behavior

When Linear is unavailable and the skill supports `--local` mode:

1. Skip all `mcp__linear-server__*` calls
2. Create local ticket files in `docs/tickets/local/` using this YAML format:

   ```yaml
   # Auto-generated local ticket (Linear unavailable)
   local_id: "LOCAL-<plan-slug>-<task_number>"  # e.g., LOCAL-friction-fixes-3
   title: "<task title from plan>"
   description: |
     <full task content>
   priority: medium
   labels: [from-plan]
   source_plan: "<plan file path>"
   task_number: <N>
   status: todo
   created_at: "<ISO 8601 timestamp>"
   ```

3. Route to direct implementation instead of Linear-dependent pipelines.
   **Important:** `onex:ticket-work` requires a Linear `ticket_id` and cannot accept local
   YAML stubs. In local mode, dispatch a `general-purpose` agent with the task content
   from the YAML file as the prompt. Do NOT dispatch `onex:ticket-work` or
   `onex:ticket-pipeline` — they will fail without Linear.

## Failure Message (when --local not specified)

If Linear is unavailable and the skill does NOT support `--local`:

> "Linear MCP is not available. Ensure the Linear MCP server is running, or use `--local`
> to create local ticket files instead."

## Limitations

Local ticket files are write-once. Status transitions (todo → done) require manual
editing or a future `local-ticket-update` utility. The `local_id` field provides a
stable identifier for correlating work back to tickets.
