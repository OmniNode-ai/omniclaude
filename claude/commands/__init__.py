"""Claude Code custom slash commands.

This package contains custom slash commands that extend Claude Code:

Available Commands:
- /parallel-solve: Execute any task (bugs, features, optimizations, requirements)
  in parallel using polymorphic agents
- /ci-failures: Fetch and analyze GitHub Actions CI failures for debugging with
  severity classification (CRITICAL/MAJOR/MINOR) and quick fix guidance
- /pr-dev-review: Fix Critical/Major/Minor issues from PR review + CI failures
  (excludes nitpicks by default)
- /pr-release-ready: Fix ALL issues from PR review including nitpicks
  (for production releases)
- /ultimate_validate_command: Generate comprehensive validation command for
  this codebase with linting, type checking, unit tests, and E2E tests

Path References (may need updating if commands are moved):
- ci-failures.md references: ~/.claude/skills/onex/ci-failures/ci-quick-review
- pr-dev-review.md references:
  - ~/.claude/skills/onex/pr-review/collate-issues
  - ~/.claude/skills/onex/pr-review/collate-issues-with-ci
  - ~/.claude/skills/onex/ci-failures/ci-quick-review
- pr-release-ready.md references: ~/.claude/skills/onex/pr-review/collate-issues
"""
