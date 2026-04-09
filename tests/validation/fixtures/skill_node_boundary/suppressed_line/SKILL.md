---
description: Skill with inline suppression comments
mode: full
version: 1.0.0
---

# Skill with Suppressed Lines

This skill shows how to suppress individual false positives.

<!-- skill-boundary-ok: historical example showing old pattern, not executed -->
gh pr list --repo example/repo

The above line is suppressed because it's a historical example, not executed code.
