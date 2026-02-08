# Ultimate Validate — Poly Worker Prompt

You are analyzing a codebase deeply and generating a comprehensive validation command file at `.claude/commands/validate.md` that validates everything in the project with complete confidence.

## Arguments

- `TARGET_REPO`: The repository root to analyze (default: current working directory)

## Steps

### 1. Discover Real User Workflows

Before analyzing tooling, understand what users actually do with this codebase.

**Read workflow documentation**:

```bash
# Check for workflow docs
head -200 README.md 2>/dev/null
head -200 CLAUDE.md 2>/dev/null
head -200 AGENTS.md 2>/dev/null
ls docs/ 2>/dev/null
```

Look for these sections:
- "Usage", "Quickstart", "Examples" sections in README.md
- Workflow patterns in CLAUDE.md/AGENTS.md
- User guides and tutorials in docs/

**Identify external integrations**:

```bash
# Check Dockerfile for installed tools/CLIs
cat Dockerfile 2>/dev/null
cat docker-compose*.yml 2>/dev/null

# Check for API client usage
grep -r "httpx\|requests\|aiohttp\|urllib" src/ --include="*.py" -l 2>/dev/null
grep -r "fetch\|axios" src/ --include="*.ts" --include="*.js" -l 2>/dev/null
```

Questions to answer:
- What CLIs does the app use? (GitHub CLI, Docker, Terraform, etc.)
- What external APIs does it call? (Telegram, Slack, GitHub, Linear, etc.)
- What services does it interact with? (PostgreSQL, Kafka, Redis, etc.)

**Extract complete user journeys**:
- Find examples like "User does X -> then Y -> then Z"
- Each workflow becomes an E2E test scenario
- Map out the full lifecycle of common operations

### 2. Deep Codebase Analysis

Explore the codebase to discover all existing validation tools and patterns.

**Linting configuration**:

```bash
# Python
ls -la ruff.toml pyproject.toml .flake8 .pylintrc setup.cfg 2>/dev/null
grep -A5 "\[tool.ruff\]" pyproject.toml 2>/dev/null

# JavaScript/TypeScript
ls -la .eslintrc* .eslintrc.json .eslintrc.js eslint.config.* 2>/dev/null

# General
ls -la .editorconfig 2>/dev/null
```

**Type checking configuration**:

```bash
# Python
ls -la mypy.ini .mypy.ini 2>/dev/null
grep -A10 "\[tool.mypy\]" pyproject.toml 2>/dev/null
grep -A10 "\[mypy\]" setup.cfg 2>/dev/null

# TypeScript
ls -la tsconfig.json tsconfig*.json 2>/dev/null
```

**Style/formatting configuration**:

```bash
# Python
grep -A5 "\[tool.black\]" pyproject.toml 2>/dev/null
grep -A5 "\[tool.isort\]" pyproject.toml 2>/dev/null

# JavaScript
ls -la .prettierrc* prettier.config.* 2>/dev/null
```

**Testing configuration**:

```bash
# Python
ls -la pytest.ini conftest.py 2>/dev/null
grep -A20 "\[tool.pytest" pyproject.toml 2>/dev/null
find . -name "conftest.py" -not -path "./.venv/*" 2>/dev/null
find . -name "test_*.py" -not -path "./.venv/*" 2>/dev/null | head -20

# JavaScript
ls -la jest.config.* vitest.config.* 2>/dev/null
```

**Package manager scripts**:

```bash
# Python
grep -A30 "\[project.scripts\]" pyproject.toml 2>/dev/null
cat Makefile 2>/dev/null

# JavaScript
cat package.json 2>/dev/null | jq '.scripts' 2>/dev/null
```

**CI/CD workflows**:

```bash
ls -la .github/workflows/*.yml 2>/dev/null
ls -la .gitlab-ci.yml 2>/dev/null
ls -la Jenkinsfile 2>/dev/null
```

**Application structure**:

```bash
# Understand what the app does
find src/ -name "*.py" -not -path "*__pycache__*" 2>/dev/null | head -30
find src/ -name "*.ts" -not -path "*node_modules*" 2>/dev/null | head -30

# Database models/migrations
find . -name "models.py" -o -name "*.model.ts" 2>/dev/null
find . -path "*/migrations/*.py" -o -path "*/migrations/*.sql" 2>/dev/null | head -10

# API endpoints
grep -r "app.route\|@router\|@app.get\|@app.post" src/ --include="*.py" -l 2>/dev/null
grep -r "router\.\|app\.get\|app\.post" src/ --include="*.ts" -l 2>/dev/null
```

### 3. Generate validate.md

Create `.claude/commands/validate.md` with only the phases that apply to the discovered codebase. Structure:

**Phase 1: Linting**

Run the actual linter commands found in the project:

```bash
# Python example
ruff check src/ tests/
# or
pylint src/

# JavaScript example
npm run lint
# or
npx eslint src/
```

**Phase 2: Type Checking**

Run the actual type checker commands found:

```bash
# Python
mypy src/omniclaude/
# or
pyright src/

# TypeScript
tsc --noEmit
```

**Phase 3: Style/Formatting Check**

Run the actual formatter check commands found:

```bash
# Python
ruff format --check src/ tests/
# or
black --check src/ tests/

# JavaScript
npx prettier --check "src/**/*.ts"
```

**Phase 4: Unit Testing**

Run the actual test commands found:

```bash
# Python
pytest tests/ -v
# or
pytest tests/ -m unit -v

# JavaScript
npm test
# or
npx jest
```

**Phase 5: End-to-End Testing**

This is the most critical phase. Test complete user workflows, not just internal APIs.

**Three levels of E2E testing**:

1. **Internal APIs**:
   - Test adapter endpoints work
   - Database queries succeed
   - Commands execute properly

2. **External Integrations**:
   - CLI operations (GitHub CLI, Linear MCP, etc.)
   - Platform API calls
   - Service health checks

3. **Complete User Journeys**:
   - Follow workflows from docs start-to-finish
   - Test the way a user would actually use the application
   - Example: "Create issue -> Bot processes -> PR created -> Issue updated"

**Good vs bad E2E tests**:
- Bad: Tests that `/clone` command stores data in database
- Good: Clone repo -> Load commands -> Execute command -> Verify git commit created
- Great: Create GitHub issue -> Bot receives webhook -> Analyzes issue -> Creates PR -> Comments on issue with PR link

**Approach**:
- Use Docker for isolated, reproducible testing where applicable
- Create test data/repos/issues as needed
- Verify outcomes in external systems (GitHub, database, file system)
- Clean up after tests

### 4. Write the Validation Command File

Write the generated validation command to `.claude/commands/validate.md`:

```bash
mkdir -p .claude/commands
```

The file should be executable by Claude Code as a slash command (`/validate`).

Structure of the generated file:

```markdown
---
description: Comprehensive validation of the codebase
---

# Validate

Run all validation phases for this codebase.

## Phase 1: Linting
[discovered linting commands]

## Phase 2: Type Checking
[discovered type checking commands]

## Phase 3: Style Checking
[discovered formatting commands]

## Phase 4: Unit Tests
[discovered test commands]

## Phase 5: Integration Tests
[discovered integration test commands]

## Phase 6: End-to-End Tests
[generated E2E test scenarios from user workflows]

## Summary
Report pass/fail for each phase with exit codes.
```

### 5. Verify the Generated Command

After writing the file, verify it:

```bash
# Check file exists and has content
wc -l .claude/commands/validate.md

# Verify the file is valid markdown
head -20 .claude/commands/validate.md
```

## Expected Output

The primary output is the `.claude/commands/validate.md` file written to the repository.

Additionally, provide a summary report:

```
=== Ultimate Validate Command Generated ===

File: .claude/commands/validate.md

Phases included:
  1. Linting        - ruff check src/ tests/
  2. Type Checking  - mypy src/omniclaude/
  3. Style Checking - ruff format --check src/ tests/
  4. Unit Tests     - pytest tests/ -v
  5. E2E Tests      - [N scenarios from workflow docs]

Discovered:
  - Linting: ruff (ruff.toml found)
  - Types: mypy ([tool.mypy] in pyproject.toml)
  - Style: ruff format (ruff.toml found)
  - Tests: pytest (conftest.py, 42 test files)
  - CI: GitHub Actions (3 workflows)
  - Integrations: Linear MCP, GitHub CLI, Kafka, PostgreSQL

Coverage:
  - Internal APIs: covered
  - External integrations: covered
  - User journeys: [N] scenarios from README.md

Run with: /validate
```

## Guiding Principles

1. **Only include phases that exist in the codebase** - Do not add type checking if there is no type checker configured
2. **Use the actual commands from the project** - Do not invent generic commands; use what is already configured
3. **E2E tests must mirror actual user workflows** - Read the docs, extract the journeys, test them
4. **Be comprehensive** - Every user workflow, every external integration, every API endpoint
5. **Be practical** - The validation should be runnable and produce clear pass/fail results
6. **Leave no stone unturned** - If `/validate` passes, the user should have 100% confidence their application works

## Error Handling

| Error | Behavior |
|-------|----------|
| No README.md found | Proceed with codebase analysis only |
| No linting config found | Skip Phase 1, note in summary |
| No type checker found | Skip Phase 2, note in summary |
| No test files found | Skip Phase 4, warn prominently |
| `.claude/commands/` does not exist | Create it with `mkdir -p` |
| Existing validate.md | Overwrite with new generated version |
