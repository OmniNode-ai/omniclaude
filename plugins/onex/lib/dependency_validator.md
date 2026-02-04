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

## Validation Result Structure

All validation functions return structured results with explicit severity levels:

```python
from enum import Enum
from dataclasses import dataclass


class ValidationSeverity(Enum):
    """Severity levels for validation results."""
    ERROR = "error"      # Blocks ticket creation (architecture violation)
    WARNING = "warning"  # Informational, does not block


@dataclass
class ValidationResult:
    """Structured validation result with explicit severity.

    Attributes:
        severity: ERROR for violations that block creation, WARNING for info
        message: Human-readable description (no severity prefix embedded)
        ticket_id: The ticket being validated (if applicable)
        blocker_id: The blocking ticket (if applicable)
        ticket_repo: Repository of the ticket being validated
        blocker_repo: Repository of the blocking ticket
    """
    severity: ValidationSeverity
    message: str
    ticket_id: str | None = None
    blocker_id: str | None = None
    ticket_repo: str | None = None
    blocker_repo: str | None = None

    def __str__(self) -> str:
        """Format for display (severity is separate, not in message)."""
        return self.message


def filter_errors(results: list[ValidationResult]) -> list[ValidationResult]:
    """Extract ERROR-level results that block ticket creation."""
    return [r for r in results if r.severity == ValidationSeverity.ERROR]


def filter_warnings(results: list[ValidationResult]) -> list[ValidationResult]:
    """Extract WARNING-level results that are informational."""
    return [r for r in results if r.severity == ValidationSeverity.WARNING]
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
) -> list[ValidationResult]:
    """Validate that dependencies respect the OmniNode architecture.

    Args:
        ticket_repo: Repository label for the ticket being created
        blocked_by_ids: List of ticket identifiers (e.g., ["OMN-1234", "OMN-1235"])
        fetch_ticket_fn: Function to fetch ticket details: fn(id: str) -> dict

    Returns:
        List of ValidationResult objects (empty if all valid)

    Rules enforced:
        1. app -> app is INVALID (application cannot depend on application)
        2. foundation -> app is INVALID (foundation cannot depend on application)
        3. app -> foundation is VALID
        4. foundation -> foundation is VALID
    """
    if not ticket_repo:
        return [ValidationResult(
            severity=ValidationSeverity.ERROR,
            message="Cannot validate dependencies: ticket_repo not specified",
            ticket_repo=None
        )]

    if not blocked_by_ids:
        return []

    results = []
    ticket_is_foundation = is_foundation_repo(ticket_repo)
    ticket_type = get_repo_type(ticket_repo)

    for blocker_id in blocked_by_ids:
        try:
            blocker = fetch_ticket_fn(blocker_id)
            blocker_repo = get_ticket_repo_label(blocker)

            if not blocker_repo:
                # Can't determine blocker repo - warn but don't block
                results.append(ValidationResult(
                    severity=ValidationSeverity.WARNING,
                    message=(
                        f"Cannot determine repository for {blocker_id}. "
                        f"Add a repository label to validate architecture."
                    ),
                    blocker_id=blocker_id,
                    ticket_repo=ticket_repo,
                    blocker_repo=None
                ))
                continue

            blocker_is_foundation = is_foundation_repo(blocker_repo)
            blocker_type = get_repo_type(blocker_repo)

            # Rule 1: app -> app is INVALID
            if not ticket_is_foundation and not blocker_is_foundation:
                results.append(ValidationResult(
                    severity=ValidationSeverity.ERROR,
                    message=(
                        f"{ticket_repo} ({ticket_type}) cannot depend on "
                        f"{blocker_id} which is in {blocker_repo} ({blocker_type}). "
                        f"Application repos can only depend on foundation repos."
                    ),
                    blocker_id=blocker_id,
                    ticket_repo=ticket_repo,
                    blocker_repo=blocker_repo
                ))

            # Rule 2: foundation -> app is INVALID
            elif ticket_is_foundation and not blocker_is_foundation:
                results.append(ValidationResult(
                    severity=ValidationSeverity.ERROR,
                    message=(
                        f"{ticket_repo} ({ticket_type}) cannot depend on "
                        f"{blocker_id} which is in {blocker_repo} ({blocker_type}). "
                        f"Foundation repos cannot depend on application repos."
                    ),
                    blocker_id=blocker_id,
                    ticket_repo=ticket_repo,
                    blocker_repo=blocker_repo
                ))

        except Exception as e:
            results.append(ValidationResult(
                severity=ValidationSeverity.ERROR,
                message=f"Failed to fetch {blocker_id} for validation: {e}",
                blocker_id=blocker_id,
                ticket_repo=ticket_repo
            ))

    return results
```

---

## Batch Validation (for plan-to-tickets)

```python
@dataclass
class BatchValidationResult:
    """Validation result with entry context for batch operations.

    Attributes:
        result: The underlying ValidationResult
        entry_title: Title of the plan entry (truncated for display)
        entry_id: ID of the plan entry (e.g., "P1", "M1")
    """
    result: ValidationResult
    entry_title: str
    entry_id: str | None = None

    @property
    def severity(self) -> ValidationSeverity:
        """Delegate to underlying result."""
        return self.result.severity

    @property
    def message(self) -> str:
        """Delegate to underlying result."""
        return self.result.message

    def __str__(self) -> str:
        """Format with entry context."""
        return f"[{self.entry_title}] {self.result.message}"


def filter_batch_errors(results: list[BatchValidationResult]) -> list[BatchValidationResult]:
    """Extract ERROR-level results from batch validation."""
    return [r for r in results if r.severity == ValidationSeverity.ERROR]


def filter_batch_warnings(results: list[BatchValidationResult]) -> list[BatchValidationResult]:
    """Extract WARNING-level results from batch validation."""
    return [r for r in results if r.severity == ValidationSeverity.WARNING]


def validate_batch_dependencies(
    entries: list[dict],
    repo_for_entry_fn: callable,
    fetch_ticket_fn: callable
) -> list[BatchValidationResult]:
    """Validate all dependencies in a batch of plan entries before creation.

    Args:
        entries: List of plan entries with 'id', 'title', 'dependencies' fields
        repo_for_entry_fn: Function to get repo label for an entry: fn(entry) -> str
        fetch_ticket_fn: Function to fetch external ticket details

    Returns:
        List of BatchValidationResult objects across the batch

    Note:
        For internal dependencies (P1 -> P2), both entries must be from same repo
        (which is typically true for a single plan), so no cross-repo violation.
        External dependencies (OMN-1234) are validated against architecture rules.
    """
    results = []

    for entry in entries:
        entry_repo = repo_for_entry_fn(entry)
        if not entry_repo:
            continue

        entry_title = entry.get('title', 'Unknown')[:30] + "..."
        entry_id = entry.get('id')

        for dep in entry.get('dependencies', []):
            # Skip internal plan refs (P1, M1) - same plan, same repo
            if dep.startswith('P') or dep.startswith('M'):
                continue

            # Validate external ticket refs (OMN-1234)
            if dep.startswith('OMN-'):
                entry_results = validate_dependencies(
                    ticket_repo=entry_repo,
                    blocked_by_ids=[dep],
                    fetch_ticket_fn=fetch_ticket_fn
                )
                for result in entry_results:
                    results.append(BatchValidationResult(
                        result=result,
                        entry_title=entry_title,
                        entry_id=entry_id
                    ))

    return results
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

    results = validate_dependencies(
        ticket_repo=ticket_repo,
        blocked_by_ids=blocked_by_ids,
        fetch_ticket_fn=lambda id: mcp__linear-server__get_issue(id=id)
    )

    # Filter using structured severity field
    errors = filter_errors(results)
    warnings = filter_warnings(results)

    for w in warnings:
        print(f"[WARNING] {w.message}")

    if errors:
        if not args.allow_arch_violation:
            print("\nDependency architecture violations detected:\n")
            for err in errors:
                print(f"  - {err.message}\n")
            print("\nTo proceed anyway, use --allow-arch-violation flag.")
            raise SystemExit(1)
        else:
            print("\n[WARNING] Proceeding with architecture violations (--allow-arch-violation):\n")
            for err in errors:
                print(f"  - {err.message}\n")
```

### /plan-to-tickets Integration

Before Step 8 (batch creation), validate all external dependencies:

```python
# In Step 7.5: Validate Architecture Dependencies
# (assumes --repo is provided or detected for the plan)
plan_repo = args.repo or detect_repo_from_content(content)

if plan_repo:
    results = validate_batch_dependencies(
        entries=entries,
        repo_for_entry_fn=lambda e: plan_repo,  # All entries use same repo
        fetch_ticket_fn=lambda id: mcp__linear-server__get_issue(id=id)
    )

    # Filter using structured severity field
    errors = filter_batch_errors(results)
    warnings = filter_batch_warnings(results)

    for w in warnings:
        print(f"[WARNING] {w}")  # Uses __str__ which includes entry context

    if errors:
        if not args.allow_arch_violation:
            print("\nDependency architecture violations detected in plan:\n")
            for err in errors:
                print(f"  - {err}\n")  # Uses __str__ which includes entry context
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

| Ticket Repo | Blocked By Repo | Severity | Result |
|-------------|-----------------|----------|--------|
| omniclaude | omniintelligence | `ERROR` | app cannot depend on app |
| omnibase_infra | omniclaude | `ERROR` | foundation cannot depend on app |
| omniclaude | omnibase_core | (none) | Valid: app can depend on foundation |
| omnibase_infra | omnibase_core | (none) | Valid: foundation can depend on foundation |
| omniclaude | OMN-1234 (no label) | `WARNING` | Cannot determine repository |

### Example ValidationResult Objects

```python
# Architecture violation (ERROR)
ValidationResult(
    severity=ValidationSeverity.ERROR,
    message="omniclaude (application) cannot depend on OMN-1234 which is in omniintelligence (application). Application repos can only depend on foundation repos.",
    blocker_id="OMN-1234",
    ticket_repo="omniclaude",
    blocker_repo="omniintelligence"
)

# Missing label (WARNING)
ValidationResult(
    severity=ValidationSeverity.WARNING,
    message="Cannot determine repository for OMN-5678. Add a repository label to validate architecture.",
    blocker_id="OMN-5678",
    ticket_repo="omniclaude",
    blocker_repo=None
)
```
