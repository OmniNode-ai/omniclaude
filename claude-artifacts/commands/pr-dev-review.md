# PR Dev Review - Development-Focused Review

**Purpose**: Identify issues that should be fixed during development to prevent tech debt.

**Philosophy**: Fix anything that affects code quality, correctness, or maintainability. Skip nitpicks (use `/pr-release-ready` for those).

---

## Execution

Execute the optimized `collate-issues` script which handles all fetching, parsing, and categorization automatically:

```bash
# PR number is provided as argument
PR_NUM="${1:-}"

if [[ -z "$PR_NUM" ]]; then
    echo "Usage: /pr-dev-review <PR#>"
    echo "Example: /pr-dev-review 33"
    exit 1
fi

# Use optimized collate-issues script (excludes nitpicks by default)
~/.claude/skills/pr-review/collate-issues "$PR_NUM"
```

**What this provides**:
- ✅ 🔴 Critical issues (must fix before merge)
- ✅ 🟠 Major issues (should fix to prevent tech debt)
- ✅ 🟡 Minor issues (fix now to maintain quality)
- ❌ ⚪ Nitpicks (excluded - use `/pr-release-ready` for those)

**Performance**:
- < 3 seconds with caching
- ~600 tokens (vs 10K+ with polymorphic agent)
- 1 tool call (vs 15+ manual parsing)
- Automatic categorization using CodeRabbit patterns + keyword analysis

**Output format**:
```
PR #33 Issues - Prioritized

🔴 CRITICAL (2):
1. [agents/lib/kafka_helper.py:45] Missing error handling for Kafka connection failures
2. [tests/test_kafka.py:12] Test failures in test_consume_event

🟠 MAJOR (3):
1. [skills/_shared/kafka_helper.py:23] Inconsistent API pattern with other helpers
2. [scripts/health_check.sh:67] Missing exit code standardization
3. [agents/lib/kafka_rpk_client.py:89] No validation for environment variables

🟡 MINOR (5):
1. [README.md:45] Missing documentation for new EXIT_CODES.md
2. [tests/test_kafka.py:34] Missing test coverage for error scenarios
3. [kafka_helper.py:12] Consider adding type hints for better IDE support
4. [scripts/health_check.sh:23] Edge case not handled for empty responses
5. [agents/lib/kafka_rpk_client.py:56] Unused import: typing.Optional

Summary: 2 critical, 3 major, 5 minor = 10 actionable issues (nitpicks excluded)
```

**Next steps after reviewing**:
1. Address all critical issues first (blocking merge)
2. Fix major issues to prevent tech debt
3. Clean up minor issues to maintain quality
