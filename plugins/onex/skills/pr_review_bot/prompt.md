# PR Review Bot — Execution Prompt

This prompt executes the PR Review Bot skill by dispatching to the `node_pr_review_bot` ONEX node.

> **Node distinction**: `node_pr_review_bot` is the external omnimarket service node (registered in `plugin-compat.yaml`). It is distinct from the internal `node_skill_pr_review_bot_orchestrator` that lives in this repo. All `onex run-node` invocations below target the external node through the manifest-canonical runtime path.

## When to use

Use this skill when you need to run automated multi-model adversarial review on a GitHub PR:
- Post structured review threads with findings
- Use a judge model to verify thread resolutions
- Get a summary verdict

## Execution

Run the node via `onex run-node`:

```bash
uv run onex run-node node_pr_review_bot --input '{"pr_number": <PR>, "repo": "owner/repo", "reviewer_models": ["<key-from-ModelInferenceBridgeConfig>"]}'
```

## Arguments

| Arg | Type | Required | Default | Description |
|-----|------|----------|---------|-------------|
| `pr_number` | int | Yes | — | PR number to review |
| `repo` | string | Yes | — | GitHub repo in `owner/repo` format |
| `reviewer_models` | list | Yes | — | Models to use for review (must be registered in ModelInferenceBridgeConfig) |
| `judge_model` | string | No | node contract default | Judge model for thread verification; must be a key registered in `ModelInferenceBridgeConfig`. |
| `severity_threshold` | string | No | `MAJOR` | Minimum severity to post (MAJOR, CRITICAL) |
| `dry_run` | bool | No | `false` | Run without posting to GitHub |
| `max_findings_per_pr` | int | No | 20 | Cap on threads to post |

## Example

All examples use the manifest-canonical runtime dispatcher. Replace `<reviewer-key>` with a key registered in `ModelInferenceBridgeConfig.model_configs` for your deployment.

```bash
# Full review
uv run onex run-node node_pr_review_bot --input '{"pr_number": 42, "repo": "OmniNode-ai/omnimarket", "reviewer_models": ["<reviewer-key>"]}'

# Dry run to test
uv run onex run-node node_pr_review_bot --input '{"pr_number": 42, "repo": "OmniNode-ai/omnimarket", "reviewer_models": ["<reviewer-key>"], "dry_run": true}'
```
