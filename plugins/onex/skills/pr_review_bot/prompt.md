# PR Review Bot — Execution Prompt

This prompt executes the PR Review Bot skill by dispatching to the `node_pr_review_bot` ONEX node.

## When to use

Use this skill when you need to run automated multi-model adversarial review on a GitHub PR:
- Post structured review threads with findings
- Use a judge model to verify thread resolutions
- Get a summary verdict

## Execution

Run the node via `onex run-node`:

```bash
cd $OMNI_HOME/omnimarket
uv run onex run-node node_pr_review_bot --input '{"pr_number": <PR>, "repo": "owner/repo", "reviewer_models": ["qwen3-coder"], "judge_model": "deepseek-r1"}'
```

## Arguments

| Arg | Type | Required | Default | Description |
|-----|------|----------|---------|-------------|
| `pr_number` | int | Yes | — | PR number to review |
| `repo` | string | Yes | — | GitHub repo in `owner/repo` format |
| `reviewer_models` | list | No | `["qwen3-coder-30b", "qwen3-14b"]` | Models to use for review |
| `judge_model` | string | No | `deepseek-r1` | Judge model for thread verification |
| `severity_threshold` | string | No | `major` | Minimum severity to post (major, critical) |
| `dry_run` | bool | No | `false` | Run without posting to GitHub |
| `max_findings_per_pr` | int | No | 20 | Cap on threads to post |

## Example

```bash
# Full review with defaults
uv run onex run-node node_pr_review_bot --input '{"pr_number": 42, "repo": "OmniNode-ai/omnimarket"}'

# Dry run to test
uv run onex run-node node_pr_review_bot --input '{"pr_number": 42, "repo": "OmniNode-ai/omnimarket", "dry_run": true}'

# Custom models
uv run onex run-node node_pr_review_bot --input '{"pr_number": 42, "repo": "OmniNode-ai/omnimarket", "reviewer_models": ["claude-sonnet"], "judge_model": "deepseek-r1"}'
```