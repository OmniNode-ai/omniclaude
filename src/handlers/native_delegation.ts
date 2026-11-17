// SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
// SPDX-License-Identifier: MIT

// Display adapter only. The existing shell/runner owns eligibility, switches,
// sensitivity, provider routing, quality checks, receipts and bounded fallback.
// Keep this host adapter in the JavaScript-compatible subset of TypeScript:
// the customer wheel packages these bytes as its vendor-loaded .js module.
export function register(on) {
  let turn;
  const submissions = [];
  on("prompt.submit", async ($, event, next) => {
    const pending = {
      text: event.text,
      eligible: !event.isMeta && !event.command && !event.attachments?.length &&
        ["composer", "bridge", "sdk"].includes(event.origin?.kind),
    };
    submissions.push(pending);
    // Bound queued state. An evicted or rewritten prompt simply stays Claude's.
    if (submissions.length > 128) submissions.shift();
    const forget = () => {
      const index = submissions.indexOf(pending);
      if (index >= 0) submissions.splice(index, 1);
    };
    try {
      const result = await next(event);
      if (result.drop || result.text !== event.text) forget();
      return result;
    } catch (error) {
      forget();
      throw error;
    }
  });
  on("turn.start", async ($, event, next) => {
    if (event.agentId === undefined) {
      const index = submissions.findIndex(item => item.text === event.text);
      const pending = index >= 0 ? submissions.splice(index, 1)[0] : undefined;
      turn = { id: event.turnId, text: event.text, eligible: pending?.eligible === true };
    }
    return next(event);
  });
  on("turn.complete", async ($, event, next) => {
    if (turn?.id === event.turnId) turn = undefined;
    return next(event);
  });
  on("turn.step", async function* ($, event, next) {
    if (event.agentId !== undefined || event.index !== 0 ||
        turn?.id !== event.turnId || !turn.text || !turn.eligible) {
      return yield* next(event);
    }

    let output;
    try {
      const messages = await $.session.messages({ as: "api" });
      const last = Array.isArray(messages) ? messages.at(-1) : undefined;
      // Image/attachment content belongs to Claude, which received the actual
      // attachment. Never reduce it to text for the delegated model.
      if (last?.role === "user" && Array.isArray(last.content) &&
          last.content.length > 0 &&
          last.content.every(block => block.type === "text")) {
        const info = await $.session.info();
        const runtime = JSON.parse(await $.fs.read(`${$.plugin.root}/hooks/delegation-runtime.json`));
        if (typeof runtime.python !== "string" || !runtime.python.startsWith("/")) {
          throw new Error("Invalid delegation interpreter binding");
        }
        const payload = {
          hook_event_name: "UserPromptSubmit",
          prompt: turn.text,
          session_id: await $.session.id(),
          transcript_path: info.transcriptPath,
        };
        const process = await $.process.run(
          ["/bin/bash", `${$.plugin.root}/hooks/scripts/pre_tool_use_delegation.sh`],
          {
            stdin: JSON.stringify(payload),
            env: { ...await $.process.hookEnv(), PLUGIN_PYTHON_BIN: runtime.python },
            // The shell and node retain their existing inner limits. This is
            // only the host process ceiling, including shell startup/shutdown.
            timeoutMs: 300000,
          },
        );
        if (process.exitCode === 0 && !process.isStdoutTruncated && process.stdout.trim()) {
          output = JSON.parse(process.stdout);
        }
      }
    } catch {
      // A failed adapter never consumes the original turn. Keep next() outside
      // this catch: a Claude/provider failure must not trigger a second call.
      try {
        await $.ui.log("ONEX native delegation adapter failed; continuing with Claude.", { to: "debug" });
      } catch {
        // Failure to record diagnostics must not consume the original prompt.
      }
    }

    const answer = output?.decision === "block" && typeof output.reason === "string"
      ? output.reason : "";
    if (answer.trim()) {
      yield { kind: "text", index: 0, text: answer };
      yield { kind: "stop", stopReason: "end_turn", usage: null };
      return {
        turnId: event.turnId,
        index: event.index,
        answer,
        toolUses: [],
        stopReason: "end_turn",
        usage: null,
      };
    }

    const context = output?.hookSpecificOutput?.additionalContext;
    if (typeof context === "string" && context.trim()) {
      try {
        await $.session.append({
          message: { type: "user", content: [{ type: "text", text: context }] },
        });
      } catch {
        // Context delivery failure still leaves this prompt with Claude.
      }
    }
    return yield* next(event);
  });
}
