# _lib/dependency-tiers/helpers.md

**Shared tier graph for cross-repo dependency ordering.**

Used by `/integration-gate` and `/release` to determine merge and release order.
Repos are organized into tiers where tier N depends only on tiers < N.

## Import

```
@_lib/dependency-tiers/helpers.md
```

---

## Constants

```python
# Dependency tier graph: tier -> [repos]
# Tier N depends only on tiers < N
TIER_GRAPH: dict[int, list[str]] = {
    1: ["omnibase_spi"],
    2: ["omnibase_core"],
    3: ["omnibase_infra", "omniintelligence", "omnimemory"],
    4: ["omniclaude"],
}

# All repos in tier order (flattened)
ALL_REPOS: list[str] = [
    "omnibase_spi",
    "omnibase_core",
    "omnibase_infra",
    "omniintelligence",
    "omnimemory",
    "omniclaude",
]

# Known inter-repo dependencies (downstream -> upstream list)
DEPENDENCY_MAP: dict[str, list[str]] = {
    "omnibase_spi": [],
    "omnibase_core": ["omnibase_spi"],
    "omnibase_infra": ["omnibase_core", "omnibase_spi"],
    "omniintelligence": ["omnibase_core", "omnibase_spi"],
    "omnimemory": ["omnibase_core", "omnibase_spi"],
    "omniclaude": ["omnibase_core", "omnibase_infra", "omniintelligence"],
}

# GitHub org
GITHUB_ORG = "OmniNode-ai"
```

---

## get_tier(repo_name)

Return the tier number for a given repo name.

```python
def get_tier(repo_name: str) -> int:
    """Return the tier number for repo_name.

    Args:
        repo_name: Short repo name (e.g., "omnibase_core").

    Returns:
        Tier number (1-4).

    Raises:
        ValueError: If repo_name is not in the tier graph.
    """
    for tier, repos in TIER_GRAPH.items():
        if repo_name in repos:
            return tier
    raise ValueError(
        f"get_tier: unknown repo '{repo_name}'. "
        f"Known repos: {ALL_REPOS}"
    )
```

---

## get_repos_in_tier(tier)

Return all repos in the given tier.

```python
def get_repos_in_tier(tier: int) -> list[str]:
    """Return all repos in the given tier.

    Args:
        tier: Tier number (1-4).

    Returns:
        List of repo names in the tier. Empty if tier is invalid.
    """
    return TIER_GRAPH.get(tier, [])
```

---

## get_upstream_repos(repo_name)

Return all repos that the given repo depends on.

```python
def get_upstream_repos(repo_name: str) -> list[str]:
    """Return all repos that repo_name depends on.

    Args:
        repo_name: Short repo name.

    Returns:
        List of upstream repo names. Empty if repo has no dependencies.
    """
    return DEPENDENCY_MAP.get(repo_name, [])
```

---

## get_downstream_repos(repo_name)

Return all repos that depend on the given repo.

```python
def get_downstream_repos(repo_name: str) -> list[str]:
    """Return all repos that depend on repo_name.

    Args:
        repo_name: Short repo name.

    Returns:
        List of downstream repo names.
    """
    return [
        name
        for name, deps in DEPENDENCY_MAP.items()
        if repo_name in deps
    ]
```

---

## repos_in_tier_order(repo_names)

Sort a list of repo names by their tier order.

```python
def repos_in_tier_order(repo_names: list[str]) -> list[str]:
    """Sort repo names by tier order (ascending).

    Repos in the same tier are sorted alphabetically for stability.

    Args:
        repo_names: List of repo names to sort.

    Returns:
        Sorted list.
    """
    return sorted(repo_names, key=lambda r: (get_tier(r), r))
```

---

## Usage

```python
# In release skill:
for tier_num in sorted(TIER_GRAPH.keys()):
    repos = get_repos_in_tier(tier_num)
    for repo in repos:
        upstream = get_upstream_repos(repo)
        # Wait for upstream repos to complete before processing this tier
        ...

# In integration-gate:
ordered_repos = repos_in_tier_order(candidate_repos)
for repo in ordered_repos:
    # Process in dependency order
    ...
```
