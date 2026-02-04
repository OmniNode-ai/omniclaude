# Dependency Architecture Validator

Shared validation logic for ticket creation commands. Enforces the OmniNode dependency architecture: application repos can only depend on foundation repos, and foundation repos can NEVER depend on application repos.

---

## Architecture Rule

```
FOUNDATION REPOS (can depend on each other):
  omnibase_core
  omnibase_spi
  omnibase_infra

APPLICATION REPOS (can only depend on foundation):
  omniclaude
  omniintelligence
  omnidash
  omnimemory
  omniagent
  (any repo not in foundation list)

VALID:
  app → foundation (OK)
  foundation → foundation (OK)

INVALID:
  app → app (REJECT)
  foundation → app (REJECT)
```

---

## Constants

```python
# Foundation repositories - shared infrastructure layer
FOUNDATION_REPOS = frozenset({
    "omnibase_core",
    "omnibase_spi",
    "omnibase_infra"
})
```

---

## Helper Functions

```python
def is_foundation_repo(repo: str) -> bool:
    """Check if repository is in the foundation layer."""
    if not repo:
        return False
    # Normalize repo name (handle variations like "omnibase-core" vs "omnibase_core")
    normalized = repo.lower().replace("-", "_").strip()
    return normalized in FOUNDATION_REPOS


def is_application_repo(repo: str) -> bool:
    """Check if repository is in the application layer.

    Any repo not in FOUNDATION_REPOS is considered an application repo.
    """
    if not repo:
        return False
    return not is_foundation_repo(repo)


def get_repo_type(repo: str) -> str:
    """Get human-readable repo type for error messages."""
    return "foundation" if is_foundation_repo(repo) else "application"
```

---

## Ticket Repo Label Extraction

```python
def get_ticket_repo_label(ticket: dict) -> str | None:
    """Extract repository label from a Linear ticket.

    Args:
        ticket: Linear issue dict from MCP (must include 'labels' field)

    Returns:
        Repository label string or None if not found

    Note:
        Repository labels follow the pattern: omniclaude, omnibase_core, etc.
        The ticket must have been fetched with labels included.
    """
    labels = ticket.get('labels', [])

    # Known repo labels (extend as needed)
    known_repos = {
        'omniclaude', 'omniintelligence', 'omnidash', 'omnimemory', 'omniagent',
        'omnibase_core', 'omnibase_spi', 'omnibase_infra',
        'omniarchon'
    }

    # Labels can be strings or dicts with 'name' field
    for label in labels:
        label_name = label if isinstance(label, str) else label.get('name', '')
        label_lower = label_name.lower().replace("-", "_")
        if label_lower in known_repos:
            return label_lower

    return None
```

---

## Core Validation Function

```python
def validate_dependencies(
    ticket_repo: str,
    blocked_by_ids: list[str],
    fetch_ticket_fn: callable
) -> list[str]:
    """Validate that dependencies respect the OmniNode architecture.

    Args:
        ticket_repo: Repository label for the ticket being created
        blocked_by_ids: List of ticket identifiers (e.g., ["OMN-1234", "OMN-1235"])
        fetch_ticket_fn: Function to fetch ticket details: fn(id: str) -> dict

    Returns:
        List of violation error messages (empty if all valid)

    Rules enforced:
        1. app → app is INVALID (application cannot depend on application)
        2. foundation → app is INVALID (foundation cannot depend on application)
        3. app → foundation is VALID
        4. foundation → foundation is VALID
    """
    if not ticket_repo:
        return ["Cannot validate dependencies: ticket_repo not specified"]

    if not blocked_by_ids:
        return []

    errors = []
    ticket_is_foundation = is_foundation_repo(ticket_repo)
    ticket_type = get_repo_type(ticket_repo)

    for blocker_id in blocked_by_ids:
        try:
            blocker = fetch_ticket_fn(blocker_id)
            blocker_repo = get_ticket_repo_label(blocker)

            if not blocker_repo:
                # Can't determine blocker repo - warn but don't block
                errors.append(
                    f"Warning: Cannot determine repository for {blocker_id}. "
                    f"Add a repository label to validate architecture."
                )
                continue

            blocker_is_foundation = is_foundation_repo(blocker_repo)
            blocker_type = get_repo_type(blocker_repo)

            # Rule 1: app → app is INVALID
            if not ticket_is_foundation and not blocker_is_foundation:
                errors.append(
                    f"Architecture violation: {ticket_repo} ({ticket_type}) cannot depend on "
                    f"{blocker_id} which is in {blocker_repo} ({blocker_type}). "
                    f"Application repos can only depend on foundation repos."
                )

            # Rule 2: foundation → app is INVALID
            elif ticket_is_foundation and not blocker_is_foundation:
                errors.append(
                    f"Architecture violation: {ticket_repo} ({ticket_type}) cannot depend on "
                    f"{blocker_id} which is in {blocker_repo} ({blocker_type}). "
                    f"Foundation repos cannot depend on application repos."
                )

        except Exception as e:
            errors.append(f"Failed to fetch {blocker_id} for validation: {e}")

    return errors
```

---

## Batch Validation (for plan-to-tickets)

```python
def validate_batch_dependencies(
    entries: list[dict],
    repo_for_entry_fn: callable,
    id_map: dict[str, str],
    fetch_ticket_fn: callable
) -> list[str]:
    """Validate all dependencies in a batch of plan entries before creation.

    Args:
        entries: List of plan entries with 'id', 'title', 'dependencies' fields
        repo_for_entry_fn: Function to get repo label for an entry: fn(entry) -> str
        id_map: Mapping of internal IDs (P1, P2) to repos (from same plan)
        fetch_ticket_fn: Function to fetch external ticket details

    Returns:
        List of all violation error messages across the batch

    Note:
        For internal dependencies (P1 → P2), both entries must be from same repo
        (which is typically true for a single plan), so no cross-repo violation.
        External dependencies (OMN-1234) are validated against architecture rules.
    """
    errors = []

    for entry in entries:
        entry_repo = repo_for_entry_fn(entry)
        if not entry_repo:
            continue

        for dep in entry.get('dependencies', []):
            # Skip internal plan refs (P1, M1) - same plan, same repo
            if dep.startswith('P') or dep.startswith('M'):
                continue

            # Validate external ticket refs (OMN-1234)
            if dep.startswith('OMN-'):
                entry_errors = validate_dependencies(
                    ticket_repo=entry_repo,
                    blocked_by_ids=[dep],
                    fetch_ticket_fn=fetch_ticket_fn
                )
                for err in entry_errors:
                    errors.append(f"[{entry['title'][:30]}...] {err}")

    return errors
```

---

## Usage in Commands

### /create-ticket Integration

After parsing `--blocked-by` argument and before creating ticket:

```python
# In Step 4.5: Validate Architecture Dependencies
if args.blocked_by:
    blocked_by_ids = [id.strip() for id in args.blocked_by.split(",") if id.strip()]
    ticket_repo = args.repo or get_current_repo()

    violations = validate_dependencies(
        ticket_repo=ticket_repo,
        blocked_by_ids=blocked_by_ids,
        fetch_ticket_fn=lambda id: mcp__linear-server__get_issue(id=id)
    )

    # Filter out warnings vs errors
    errors = [v for v in violations if not v.startswith("Warning:")]
    warnings = [v for v in violations if v.startswith("Warning:")]

    for w in warnings:
        print(w)

    if errors:
        if not args.allow_arch_violation:
            print("\nDependency architecture violations detected:\n")
            for err in errors:
                print(f"  - {err}\n")
            print("\nTo proceed anyway, use --allow-arch-violation flag.")
            raise SystemExit(1)
        else:
            print("\n[WARNING] Proceeding with architecture violations (--allow-arch-violation):\n")
            for err in errors:
                print(f"  - {err}\n")
```

### /plan-to-tickets Integration

Before Step 8 (batch creation), validate all external dependencies:

```python
# In Step 7.5: Validate Architecture Dependencies
# (assumes --repo is provided or detected for the plan)
plan_repo = args.repo or detect_repo_from_content(content)

if plan_repo:
    violations = validate_batch_dependencies(
        entries=entries,
        repo_for_entry_fn=lambda e: plan_repo,  # All entries use same repo
        id_map={},  # Will be built during creation
        fetch_ticket_fn=lambda id: mcp__linear-server__get_issue(id=id)
    )

    errors = [v for v in violations if "Architecture violation" in v]
    warnings = [v for v in violations if "Warning:" in v]

    for w in warnings:
        print(w)

    if errors:
        if not args.allow_arch_violation:
            print("\nDependency architecture violations detected in plan:\n")
            for err in errors:
                print(f"  - {err}\n")
            print("\nFix the plan or use --allow-arch-violation to proceed.")
            raise SystemExit(1)
        else:
            print("\n[WARNING] Proceeding with architecture violations:\n")
            for err in errors:
                print(f"  - {err}\n")
```

---

## Override Flag

All commands should support `--allow-arch-violation` flag:

```yaml
args:
  - name: allow-arch-violation
    description: Bypass architecture dependency validation (use with caution)
    required: false
```

When this flag is set:
- Violations are logged as warnings
- Ticket creation proceeds
- A note is added to ticket description: `**Warning**: This ticket has dependencies that violate architecture guidelines.`

---

## Example Violations

| Ticket Repo | Blocked By Repo | Verdict | Message |
|-------------|-----------------|---------|---------|
| omniclaude | omniintelligence | INVALID | app→app |
| omnibase_infra | omniclaude | INVALID | foundation→app |
| omniclaude | omnibase_core | VALID | app→foundation |
| omnibase_infra | omnibase_core | VALID | foundation→foundation |
| omniclaude | OMN-1234 (no label) | WARNING | Can't determine repo |
