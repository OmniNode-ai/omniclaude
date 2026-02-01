# Ticket Work Orchestration

You are executing contract-driven ticket work. This prompt defines the complete orchestration logic.

## Initialization

When `/ticket-work {ticket_id}` is invoked:

1. **Fetch the ticket:**
   ```
   mcp__linear-server__get_issue(id="{ticket_id}")
   ```

2. **Parse the contract** from the ticket description:
   - Look for `## Contract` section followed by a YAML code block
   - If found: parse and validate the YAML
   - If not found: create initial contract (phase: intake)

3. **Announce current state:**
   ```
   Resuming {ticket_id} in {phase} phase.

   Pending items:
   - {list pending questions if any}
   - {list blocking verification if any}
   - {list pending gates if any}
   ```

4. **Guide based on current phase** (see Phase Handlers below)

---

## Contract Schema

```yaml
# Identity (set at intake)
ticket_id: "OMN-1234"
title: "Feature title"
repo: "omnibase_core"
branch: null  # set during implementation

# State
phase: intake  # intake|research|questions|spec|implementation|review|done
created_at: "2026-02-01T12:00:00Z"
updated_at: "2026-02-01T12:00:00Z"

# Research context (populated during research phase)
context:
  relevant_files: []
  patterns_found: []
  notes: ""

# Clarification (populated during questions phase)
questions:
  - id: "q1"
    text: "What authentication method should we use?"
    category: "architecture"  # architecture|behavior|integration|scope
    required: true
    answer: null
    answered_at: null

# Specification (populated during spec phase)
requirements:
  - id: "r1"
    statement: "System shall authenticate users via OAuth2"
    rationale: "Matches existing auth patterns"
    acceptance:
      - "OAuth2 flow implemented"
      - "Token refresh works"

verification:
  - id: "v1"
    title: "Unit tests pass"
    kind: "unit_tests"  # unit_tests|lint|mypy|integration|manual_check|script
    command: "uv run pytest tests/"
    expected: "exit 0"
    blocking: true
    status: "pending"  # pending|passed|failed|skipped
    evidence: null
    executed_at: null

gates:
  - id: "g1"
    title: "Human approval"
    kind: "human_approval"  # human_approval|policy_check|security_check
    required: true
    status: "pending"  # pending|approved|rejected|skipped
    notes: null
    resolved_at: null

# Completion tracking
commits: []
pr_url: null
hardening_tickets: []
```

---

## Phase Handlers

### Phase: intake

**Entry:** Always allowed (initial phase)

**Actions:**
1. Create contract if not exists
2. Set `ticket_id`, `title`, `repo` from Linear ticket
3. Save contract to ticket description
4. **Auto-advance to research phase** (no human gate needed)

**Mutations allowed:** Create contract only

**Exit to research:** Automatic after contract creation (no confirmation needed)

---

### Phase: research

**Entry invariant:** Contract exists

**Actions:**
1. Analyze the ticket requirements
2. Use codebase exploration to identify:
   - Relevant files (`context.relevant_files`)
   - Existing patterns (`context.patterns_found`)
   - Notes about approach (`context.notes`)
3. Generate clarifying questions (add to `questions[]`)
4. Save contract after each mutation

**Mutations allowed:**
- `context.relevant_files`
- `context.patterns_found`
- `context.notes`
- `questions[]` (append only)

**Research boundaries:**
- MAY populate context
- MAY generate questions
- MAY NOT add requirements
- MAY NOT add verification steps
- MAY NOT answer questions
- MAY NOT advance phase

**Exit to questions:**
- Invariant: `len(context.relevant_files) >= 1`
- User says "questions ready" or similar

---

### Phase: questions

**Entry invariant:** `len(context.relevant_files) >= 1`

**Actions:**
1. Present unanswered questions one at a time using `AskUserQuestion`
2. Record answers in `questions[].answer` and `questions[].answered_at`
3. Save contract after each answer

**Mutations allowed:**
- `questions[].answer`
- `questions[].answered_at`

**Exit to spec:**
- Invariant: All required questions have non-empty answers
- Human gate: User says "requirements clear", "proceed to spec", or confirms via AskUserQuestion:
  ```
  All questions answered. Ready to proceed to spec phase?
  - Yes, requirements are clear
  - No, I have more questions
  ```

---

### Phase: spec

**Entry invariant:** `is_questions_complete()` AND human signal

**Actions:**
1. Generate requirements based on ticket + context + answers
2. Generate verification steps (default: unit_tests, lint, mypy)
3. Generate gates (default: human_approval)
4. Present spec for review
5. Allow edits via user feedback

**Mutations allowed:**
- `requirements[]` (append; edits allowed during spec phase only)
- `verification[]` (append; edits allowed during spec phase only)
- `gates[]` (append; edits allowed during spec phase only)

**Exit to implementation:**
- Invariant: `len(requirements) >= 1` AND `len(verification) >= 1`
- Human gate: User says "approve spec", "build it", or confirms via AskUserQuestion:
  ```
  Spec complete with {N} requirements and {M} verification steps. Ready to implement?
  - Yes, build it
  - No, needs changes
  ```

---

### Phase: implementation

**Entry invariant:** `is_spec_complete()` AND human signal

**Actions:**
1. Create git branch if not exists (set `branch`)
2. Implement requirements
3. Commit changes (append to `commits[]`)
4. Update `pr_url` if PR created

**Mutations allowed:**
- `branch`
- `commits[]` (append only)
- `pr_url`

**Exit to review:**
- Invariant: `len(commits) >= 1`
- Human gate: User says "create PR", "ready for review", or confirms via AskUserQuestion:
  ```
  Implementation complete with {N} commits. Ready for review?
  - Yes, run verification
  - No, more changes needed
  ```

---

### Phase: review

**Entry invariant:** `len(commits) >= 1` AND human signal

**Actions:**

1. **Push branch and create PR:**
   ```bash
   git push -u origin {branch}
   gh pr create --title "{ticket_id}: {title}" --body "..."
   ```
   Update `pr_url` in contract.

2. **Code review loop** (repeat until done):
   ```
   Review code locally → Find issues → Fix issues → Commit → Re-review
   ```

   - Review all changed files for:
     - Logic errors
     - Missing edge cases
     - Inconsistencies with requirements
     - Documentation accuracy
   - Fix issues found (do NOT push between iterations)
   - Re-review locally
   - Continue until:
     - All issues fixed, OR
     - Only nitpicks/minor issues remain (can defer)

3. **Run verification steps:**
   ```bash
   uv run pytest tests/           # unit_tests
   uv run ruff check .            # lint
   uv run mypy src/               # mypy
   ```

4. **Update contract:**
   - `verification[].status` (passed/failed)
   - `verification[].evidence` (command output)
   - `verification[].executed_at`

5. **Return to user** with review summary:
   - Issues found and fixed
   - Remaining minor/nitpick issues (if any)
   - Verification results
   - Ask for approval to proceed

6. If hardening tickets needed, create and add to `hardening_tickets[]`

**Important:** Do NOT merge the PR. That decision belongs to the user.

**Mutations allowed:**
- `commits[]` (append only - from review fixes)
- `verification[].status`
- `verification[].evidence`
- `verification[].executed_at`
- `gates[].status`
- `gates[].notes`
- `gates[].resolved_at`
- `hardening_tickets[]` (append only)

**Exit to done:**
- Invariant: All blocking verification passed/skipped AND all required gates approved
- Human gate: User says "approve merge", "ship it", or confirms via AskUserQuestion:
  ```
  All verification passed and gates approved. Ready to complete?
  - Yes, ship it
  - No, not yet
  ```

---

### Phase: done

**Entry invariant:** `is_verification_complete()` AND `is_gates_complete()` AND human signal

**Actions:**
1. Mark contract as complete
2. Update Linear ticket status
3. Announce completion

**Mutations allowed:** None (contract is immutable in done phase)

---

## Contract Persistence

### Reading Contract

```python
def extract_contract(description: str) -> dict | None:
    """Extract contract YAML from ticket description."""
    marker = "## Contract"
    if marker not in description:
        return None

    # Find last occurrence of ## Contract
    idx = description.rfind(marker)
    contract_section = description[idx:]

    # Extract YAML from fenced code block
    import re
    match = re.search(r'```(?:yaml|YAML)?\s*\n(.*?)\n\s*```', contract_section, re.DOTALL)
    if not match:
        return None

    import yaml
    try:
        return yaml.safe_load(match.group(1))
    except yaml.YAMLError:
        return None
```

### Writing Contract

```python
def update_description_with_contract(description: str, contract: dict) -> str:
    """Update ticket description with contract, preserving original content."""
    import yaml

    marker = "## Contract"
    contract_yaml = yaml.dump(contract, default_flow_style=False, sort_keys=False)
    contract_block = f"\n---\n{marker}\n\n```yaml\n{contract_yaml}```\n"

    if marker in description:
        # Replace existing contract section
        idx = description.rfind(marker)
        # Find --- on its own line immediately before ## Contract
        delimiter_match = re.search(r'\n---\n\s*$', description[:idx])
        if delimiter_match:
            return description[:delimiter_match.start()] + contract_block
        return description[:idx] + contract_block
    else:
        # Append new contract section
        return description.rstrip() + contract_block
```

### Saving to Linear

After any contract mutation:
```
mcp__linear-server__update_issue(
    id="{ticket_id}",
    description="{updated_description}"
)
```

---

## Verification Commands (v1 Hardcoded)

```python
VERIFICATION_COMMANDS = {
    "unit_tests": "uv run pytest tests/",
    "lint": "uv run ruff check .",
    "mypy": "uv run mypy src/",
    "integration": "uv run pytest tests/integration/",
}
```

For `manual_check` kind: Present description and ask user to confirm pass/fail.
For `script` kind: Use the `command` field from the verification step.

---

## Error Handling

| Error | Behavior |
|-------|----------|
| Linear MCP failure | Fail closed, explain, do not advance |
| YAML parse failure | Fail closed, show raw content, ask user to fix |
| Contract validation failure | Fail closed, show errors, do not persist |
| Verification crash | Mark `failed`, capture error output, do not advance |
| Invariant violation | Refuse transition, explain which invariant failed |

**Never:**
- Silently swallow errors
- Persist invalid contract state
- Advance phase without explicit human signal (except intake→research which is automatic)

---

## Completion Checks

These are the logic for completion checks (mirrors ModelTicketContract from omnibase_core):

```python
def is_questions_complete(contract) -> bool:
    """All required questions have non-empty answers."""
    return all(
        q.get("answer") and q["answer"].strip()
        for q in contract.get("questions", [])
        if q.get("required", True)
    )

def is_spec_complete(contract) -> bool:
    """At least one requirement with acceptance criteria."""
    reqs = contract.get("requirements", [])
    return len(reqs) > 0 and all(
        len(r.get("acceptance", [])) > 0
        for r in reqs
    )

def is_verification_complete(contract) -> bool:
    """All blocking verification passed or skipped."""
    return all(
        v.get("status") in ("passed", "skipped")
        for v in contract.get("verification", [])
        if v.get("blocking", True)
    )

def is_gates_complete(contract) -> bool:
    """All required gates approved."""
    return all(
        g.get("status") == "approved"
        for g in contract.get("gates", [])
        if g.get("required", True)
    )

def is_done(contract) -> bool:
    """Contract is complete."""
    return (
        contract.get("phase") == "done"
        and is_questions_complete(contract)
        and is_spec_complete(contract)
        and is_verification_complete(contract)
        and is_gates_complete(contract)
    )
```

---

## Mutation Rules

| Rule | Description |
|------|-------------|
| Active phase only | Only mutate fields belonging to active phase |
| No deletion | Never delete answered questions |
| No rewrite of history | Never rewrite past commits or verification results |
| Append-only | Questions, requirements, verification, commits are append-only (requirements/verification/gates editable during spec phase) |

---

## Human Gate Detection

When detecting human signals for phase transitions:

1. **Keyword matching:** Look for trigger keywords in user messages
2. **Explicit confirmation:** Use AskUserQuestion for critical transitions
3. **Phase-gated:** Only accept signals relevant to current phase

**Do not:**
- Auto-advance based on task completion alone (except intake→research)
- Skip confirmation for meaningful phase transitions
- Accept signals for phases we're not ready to enter

---

## Resume Behavior

When `/ticket-work {ticket_id}` is invoked on an existing contract:

1. Fetch ticket, parse contract
2. Validate contract structure
3. Report current state:
   ```
   Resuming {ticket_id} in {phase} phase.

   Status:
   - Questions: {N} answered / {M} total ({K} pending)
   - Requirements: {N} defined
   - Verification: {N} passed / {M} total
   - Gates: {N} approved / {M} total
   - Commits: {N}

   Next action: {describe what needs to happen in current phase}
   ```
4. Continue from current phase
