# _lib/dispatch-laws/helpers.md

**Single canonical copy of the worker Operating Rules.**

These rules are injected into every dispatched worker prompt. They exist here once so
that no file has to restate them: a second hand-maintained copy drifts, and it did --
the copy this pack replaces had lost rule 10 entirely and abridged rules 7 and 8 while
declaring itself a verbatim reproduction.

Do not restate this block anywhere else. Reference it.

## Import

Skills reference this pack via the shared lib resolution path:

```
@_lib/dispatch-laws/helpers.md
```

`worker_template_version: v2`

---

## The block

Everything inside the fence below is the injected text, verbatim. Rule text is
byte-preserved: rewording, renumbering or merging a rule is a policy change, not a
refactor, and needs operator sign-off.

```
## Operating Rules (auto-injected by dispatch_worker skill v2)

1. **No pre-existing excuse.** Pre-existing test failures block shipping regardless of
   provenance. Fix them in the same PR or file a blocker — never push red tests.

2. **PR closing keyword.** The PR body MUST contain `Closes OMN-XXXX.` (exact closing-
   keyword form, where XXXX is the primary ticket). Without it the receipt gate fails.

3. **Worktree-only development.** All code changes happen in a ticket worktree under
   `$ONEX_WORKTREES_ROOT/<ticket>/<repo>/`. NEVER stage or commit inside the
   canonical repo clone. The worktree guard hook enforces this.

4. **Full test suite before push.** Run `env -u PYTHONPATH uv run pytest tests/ -v` with
   NO `-k` filter as the final pre-push check. The `env -u PYTHONPATH` prefix is required:
   omniclaude hooks export PYTHONPATH into the parent environment, and that value shadows
   the worktree's local `src/` layout, causing import failures. Always prefix `uv run`
   and direct `python` invocations inside worktrees with `env -u PYTHONPATH`.

5. **Never bypass pre-commit hooks.** Never use `--no-verify`, `--no-gpg-sign`, or any
   bypass flag. Pre-commit hooks enforce code quality and architectural constraints.
   Fix the issue instead of bypassing the gate.

6. **Anchor-first ordering (<TICKET>).** Phase 0 is mandatory and must complete before
   any long implementation leg: (a) verify or file the Linear ticket; (b) push a WIP
   branch to origin (even if the branch is empty). Write a resume manifest to
   `$ONEX_STATE_DIR/manifests/<ticket_id>/manifest.yaml` immediately after the WIP push
   using `resume_manifest_writer.write_resume_manifest()` with
   `phase=EnumResumeManifestPhase.PHASE_0_ANCHOR` and `wip_pushed_at` populated.
   Update the manifest at every subsequent phase boundary (implement, local_review,
   create_pr, done). On any auth or usage-limit error, call
   `resume_manifest_writer.write_survivor_note(manifest, detail="<what was diagnosed>")`
   before terminating so the defect retains identity even without a filed PR.

7. **Verifiable-handle reporting (worker-misreport ratchet).** Your final
   message MUST end with a fenced ```json-report``` block, and any claim of completion
   MUST carry its verifiable handle — claims without handles are BLOCKED at SubagentStop
   by the receipt-honesty verifier (EFFECT-based claims validator), re-probed against live
   GitHub BEFORE the orchestrator accepts your receipt:
   - A **merged** claim requires `kind: pr_ship` with `pr: {number, state: MERGED, merge_sha, repo}`.
     The verifier re-probes `gh pr view --json mergeCommit`; a missing or mismatched
     `merge_sha` is a block. Never assert "merged" in prose without this block.
   - A **deploy** claim requires `kind: deploy` with `deploy: {target, container_digest}`
     (digest must contain `sha256:`). Never assert "deployed/redeployed" in prose without it.
   - Asserting merged/deployed in free-form prose while the structured report lacks the
     matching handle is itself a block (prose-claim guard). Report only what you can prove;
     if a PR is still open or a deploy is pending, say so honestly.

   Example terminal block:
   ````
   ```json-report
   {"kind": "pr_ship", "ticket": "<TICKET-ID>",
    "pr": {"number": 1234, "state": "MERGED",
           "merge_sha": "<full-or-short-merge-commit-sha>", "repo": "OmniNode-ai/<repo>"}}
   ```
   ````

8. **OCC receipt pairing — TOOL-GENERATE, never hand-author (<TICKET>, retro D-4).**
   Hand-authored OCC receipts wedged OCC PR #2530 four ways and blocked three code
   PRs overnight. If your change touches runtime paths (src nodes/handlers/contracts),
   you MUST pair it with an `onex_change_control` (OCC) contract + DoD receipt. Do NOT
   hand-write the receipt YAML. Generate it with the tool so the full schema —
   INCLUDING `contract_sha256` (mandatory since <TICKET>; its omission is exactly
   what wedged #2530) — is emitted and validated against `ModelDodReceipt`:

   ```bash
   # From the omniclaude repo root; --base defaults to dev mechanically.
   uv run scripts/scaffold_occ_receipt.py <TICKET-ID> \
     --pr-number <OCC-PR#> --commit-sha <code-PR-head-SHA> \
     --occ-root <path-to-onex_change_control-checkout> \
     --pr-body-file <code-PR-body.md> --ci-watch-confirmed \
     --out drift/dod_receipts/<TICKET-ID>/dod-occ-pr-self/command.yaml
   ```

   The tool self-reports the four OCC #2530 wedges and refuses to emit a receipt
   while any are present. Each prohibition below is paired with its failure mode
   and the alternative action — do the alternative, do not work around the gate:

   - **No bracketed skip token.** Failure mode: a bracketed `skip-receipt-gate`
     or `skip-deploy-gate` bypass token of the form `[ skip-<gate>: ... ]`
     (written without the inner spaces) — even with a self-written justification —
     hard-FAILS the PR at the reject-deploy-gate-skip pre-commit hook AND the GHA
     required check — self-judgement is not evidence (<TICKET>). Alternative:
     **STOP and report back — any bracketed skip-token hard-fails your PR.** Remove
     the token and fix the real gate input (missing dod_evidence / Evidence-Source
     line / contract). The only escape hatch is a real user-issued
     `# skip-token-allowed: <receipt-id>` handle.
   - **Target `dev`, not `main`.** Failure mode: an OCC/code PR with base=main whose
     head is not the dev→main promotion branch is hard-FAILED by main-target-guard
     (dev-only promotion). Alternative: branch off `origin/dev` and target `dev`
     (the tool's `--base` defaults to dev); for a genuine promotion pass
     `--promotion`.
   - **Never arm blind.** Failure mode: arming auto-merge before a confirmed green
     `gh pr checks` watch merges red or strands the PR unobserved (Operating Rule 3).
     Alternative: run `gh pr checks <num> --watch` to terminal green, paste that
     output as evidence, then arm via the `enqueue_to_merge_queue()` /
     `arm_auto_merge()` helpers in `@_lib/pr-safety/helpers.md` (which select the
     correct queue method); re-run the scaffold tool with `--ci-watch-confirmed`.
   - **Cite Evidence-Source + Evidence-Ticket.** Failure mode: a code PR body
     missing the unbulleted `Evidence-Source: OCC#<n>` (or `<sha>`) OR
     `Evidence-Ticket: <TICKET-ID>` line FAILS the Receipt-Gate even with green
     checks. Alternative: patch the code PR body to include both lines via the
     `patch_pr_body()` helper in `@_lib/pr-safety/helpers.md` — the REST PATCH +
     read-back path, never the interactive PR-edit command (Projects-classic
     silent-no-op trap, <TICKET>).

9. **UI proof requires Playwright, not `curl` (D-6, <TICKET>).** For any DoD item that
   touches UI behavior, the required proof is a Playwright interaction with the operator's
   running surface: the live URL, a screenshot, and the network log of the actual request
   the UI emitted. A `curl` of the canonical endpoint is NOT acceptable evidence for a UI
   claim — it proves the backend answered, not that the operator's surface renders the data
   or emits the request. Bridges the gap until the A-2 Receipt-Gate evidence-class check
   (<TICKET>) is live.

10. **Docker builds run on the runtime host's stability lane, never in-sandbox (<TICKET>).** Worker
    sandboxes have no docker daemon — `docker build`, `docker compose build`, `docker
    compose up --build`, or any local image rebuild dead-ends inside a dispatched
    worker. If your task requires building, rebuilding, or runtime-verifying a
    container image: author the Dockerfile/compose/source change and open the PR,
    then hand off build + runtime verification to the gated `node_redeploy_orchestrator`
    path (the `/redeploy` skill) targeting the runtime host's **stability-test** lane —
    never attempt the build locally inside your sandbox, and never SSH + raw
    `docker build`/`docker compose up` yourself (that recreates the same
    no-raw-prod-bypass anti-pattern <TICKET> blocks for prod, just aimed at a
    different lane). Verify the built image via the stability-test lane's live
    EFFECT (`rpk`/`psql` against `INFRA_HOST`), never a local container. This gated
    path depends on the deploy-agent revival (<TICKET>/<TICKET>); if the
    deploy-agent is unavailable, report the PR as authored-only and flag the
    build/runtime-verify step as blocked — do not fall back to in-sandbox docker.
    Full procedure: `docs/runbooks/docker-build-worker-routing.md`.

---
```
