# Linear Handler Coverage Inventory

**Date:** 2026-06-22
**Scope:** Audit `omnimarket/src/omnimarket/nodes/` for backing handlers covering
each Linear (`mcp__linear-server__*`) call category used by the 9 named skill
prompt files in `omniclaude`. Produce an EXIST/MISSING mapping and file one
sub-ticket per MISSING handler category.

---

## Method

1. Resolved the 9 wave-named skills to their on-disk directories under
   `omniclaude/plugins/onex/skills/` (three carry historical alias names):

   | Wave name          | On-disk skill dir       |
   |--------------------|-------------------------|
   | `ticket_pipeline`  | `ticket_pipeline`       |
   | `decompose_epic`   | `decompose_epic`        |
   | `ticket_work`      | `ticket_work`           |
   | `linear_epic_org`  | `ticketing_epic_org`    |
   | `linear_triage`    | `ticketing_triage`      |
   | `linear_insights`  | `ticketing_insights`    |
   | `auto_merge`       | `auto_merge`            |
   | `compliance_sweep` | `compliance_sweep`      |
   | `plan_audit`       | `plan_audit`            |

2. Extracted Linear operations from each skill's `SKILL.md` + `prompt.md`. In
   the current tree the skills express Linear access through a `tracker.*`
   provider abstraction (the `ProtocolProvider` / `ProtocolLinearClient` seam),
   not raw `mcp__linear-server__*` strings — that migration is the goal of the
   skill-to-node runtime-handler migration. Each `tracker.<op>` maps 1:1 to an
   `mcp__linear-server__<op>` call category.

3. For dispatch-only shims (`ticket_pipeline`, `ticketing_triage`,
   `auto_merge`, `compliance_sweep`) the Linear logic lives entirely in the
   backing node; operations were read from that node's handler.

4. For each operation category, located the backing handler in omnimarket and
   classified **EXIST** (concrete Linear EFFECT handler present) vs **MISSING**
   (only a protocol port / agent-executed MCP call; no concrete EFFECT handler
   inside an omnimarket node).

---

## Per-skill Linear operation extraction

| Skill                | Backing node                              | Linear operations referenced |
|----------------------|-------------------------------------------|------------------------------|
| `ticket_pipeline`    | `node_ticket_pipeline`                    | get_issue, save_issue (state→In Review), save_comment (worktree-block note) — via sub-nodes |
| `decompose_epic`     | `node_decompose_epic_orchestrator`        | get_issue, create_issue (sub-ticket w/ parentId), list_issue_labels, save_issue (embed contract) |
| `ticket_work`        | `node_ticket_work`                        | get_issue, update_issue_description, update_issue_state (list_states) |
| `linear_epic_org`    | `node_ticketing_epic_org_orchestrator`    | list_issues (orphans, parentId==null), create_issue (epic), save_issue (set parentId), create_comment |
| `linear_triage`      | `node_linear_triage`                      | list_issues, list_children, get_issue, save_issue (state), save_comment |
| `linear_insights`    | `node_ticketing_insights_compute`         | list_issues, get_issue, list_projects, get_project, list_teams, list_users (all agent-executed; compute node does no I/O) |
| `auto_merge`         | `node_auto_merge_effect`                  | (none — GitHub-only; no Linear ops) |
| `compliance_sweep`   | `node_compliance_sweep`                   | (none — repo scan; ticket creation delegated, not inline) |
| `plan_audit`         | `node_plan_audit` (MISSING node)          | get_issue (verify each referenced ticket exists) |

---

## Operation → Handler coverage map (EXIST / MISSING)

"EXIST" = a concrete Linear EFFECT handler implementing the operation lives
inside an omnimarket node. "MISSING" = the operation is only declared as a
protocol port (injected) or executed by the agent against raw MCP — there is no
concrete omnimarket EFFECT handler the skill can resolve via `ProtocolProvider`.

| # | Linear call category (`mcp__linear-server__*`) | Used by skills | Backing handler | Status |
|---|-----------------------------------------------|----------------|-----------------|--------|
| 1 | `get_issue`        | ticket_pipeline, decompose_epic, ticket_work, linear_triage, linear_insights, plan_audit | `node_linear_triage` `_LinearGraphQLClient.get_issue`; `node_ticket_query` (read); `node_ticket_work` protocol port | **EXIST** (read path covered by `node_linear_triage` + `node_ticket_query`) |
| 2 | `list_issues`      | linear_epic_org, linear_triage, linear_insights | `node_linear_triage` `.list_issues`; `node_ticket_query` declares it in contract | **EXIST** |
| 3 | `list_children` / sub-issue listing | linear_triage | `node_linear_triage` `.list_children` | **EXIST** |
| 4 | `save_issue` (state transition) | ticket_pipeline, ticket_work, linear_triage, linear_epic_org, decompose_epic | `node_linear_triage` `.save_issue(state=...)` | **EXIST** (state write); description/parentId write **MISSING** (see 4a) |
| 4a| `save_issue` (description / parentId / contract-embed write) | decompose_epic, ticket_work, linear_epic_org | `node_ticket_work` `update_issue_description` is **protocol port only** (no concrete EFFECT in omnimarket); `node_linear_triage` writes state only | **MISSING** |
| 5 | `create_issue` (new ticket / sub-ticket / epic) | decompose_epic, linear_epic_org | `node_decompose_epic_orchestrator` + `node_ticketing_epic_org_orchestrator` expose `ProtocolTicketCreator.create_subticket` / `create_epic` **ports**; `node_create_ticket` handler defines no concrete Linear write. No concrete `issueCreate` EFFECT handler in omnimarket. | **MISSING** |
| 6 | `list_issue_labels` | decompose_epic | none (best-effort, agent/MCP only) | **MISSING** |
| 7 | `create_comment` / `save_comment` | linear_epic_org, linear_triage, ticket_pipeline | `node_linear_triage` `.save_comment` | **EXIST** (covered by `node_linear_triage`; `node_ticketing_epic_org` uses agent path) |
| 8 | `list_projects`    | linear_insights | none (compute node; agent-executed) | **MISSING** |
| 9 | `get_project`      | linear_insights | none (compute node; agent-executed) | **MISSING** |
| 10| `list_teams`       | linear_insights | none (compute node; agent-executed) | **MISSING** |
| 11| `list_users`       | linear_insights | none (compute node; agent-executed) | **MISSING** |

### Node existence note
- `node_plan_audit` does **not** exist in omnimarket; `plan_audit`'s only Linear
  op (`get_issue`) is covered by the existing read handler (category 1), so the
  missing node is a separate concern (skill-shim migration), not a missing
  Linear handler. Tracked under the parent epic, not duplicated here.

---

## MISSING handler categories → sub-tickets

Six distinct MISSING Linear EFFECT handler categories. One sub-ticket filed per
category (categories 8–11 are grouped as one read-effect node since they are the
same omission — Linear project/team/user reads for `linear_insights`):

| Sub-ticket | Scope | Categories | Recommended node |
|------------|-------|------------|------------------|
| Linear issue **write** EFFECT | description + parentId + contract-embed | 4a | extend `node_linear_updater_effect` or new `node_linear_issue_write_effect` |
| Linear issue **create** EFFECT | `create_issue` (sub-ticket/epic) behind a concrete handler | 5 | `node_linear_issue_create_effect` (back `ProtocolTicketCreator`) |
| Linear **metadata read** EFFECT | `list_issue_labels` + `list_projects` / `get_project` / `list_teams` / `list_users` | 6, 8, 9, 10, 11 | `node_linear_metadata_read_effect` |

> Categories 6, 8–11 collapse onto one shared Linear metadata/read EFFECT node,
> giving **3** net new handler nodes to build.

---

## Summary

- **11** distinct Linear call categories used across the 9 skills.
- **5 EXIST** (read + state-write + comment via `node_linear_triage` /
  `node_ticket_query`).
- **6 MISSING** concrete EFFECT handlers (issue-write metadata, issue-create,
  labels read, project/team/user reads) — currently agent-executed against raw
  MCP or exposed only as injected protocol ports.
- Net **3** new Linear EFFECT nodes needed to close the gap and let the
  `ProtocolProvider` migration resolve every skill `tracker.*` call
  to an omnimarket handler instead of a hardcoded `mcp__linear-server__*` string.
