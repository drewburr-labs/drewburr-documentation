# Phase 4 — Agentic Reliability Testing

Operational testing of POC-winning models against a real agentic workload.
Phase 1 (see [../coding-models-results.md](../coding-models-results.md)) ranked
candidates on isolated single-turn problems. Phase 4 measures how those models
hold up when wired into Goose driving an agentic loop
TypeScript monorepo — long context, multi-turn tool use, model self-feedback.

## Why a separate phase

The Phase 1 evaluation plan called for a Track 4 (agentic reliability) using
Goose, but the metric there was loop rate and tool-call efficiency on
synthetic 10-step tasks. What we actually need to know is **does the model
work as the brain of a real autonomous dev loop on a real codebase**, which
exercises a much larger surface area:

- Long-context decoding (~25K base prompt + accumulating tool history)
- Self-feedback (model reads its own prior output via `cat`/`view` tools)
- Sampling under the agent host's hardcoded settings (Goose forces temp=0)
- Quantization stability over the full conversation, not just one turn
- Tool-call format compatibility with the agent host

These are exactly the regimes that don't show up in HumanEval+ scores.

## Scope of testing so far

- ✅ `qwen2.5-coder-32b` — see [qwen2.5-coder-32b-results.md](./qwen2.5-coder-32b-results.md).
- ✅ `gemma4-31b` — see [gemma4-31b-results.md](./gemma4-31b-results.md).
- ⏳ `qwq-32b`, `deepseek-r1-qwen-32b` (the reasoning models) — not yet tested.
- ⏳ Other Phase 1 candidates — not prioritized; Phase 1 + agentic gap is large.

## Bottom line as of the latest gemma run

**No tested model is a clean fit for the Ralph workload.** Each surfaced a
distinct blocking issue:

| Model | Tools | Code generation | Status |
|---|---|---|---|
| qwen2.5-coder-32b | Inconsistent format (workaround via LiteLLM callback) | Clean | Tools fire but model narrates instead of acting |
| gemma4-31b | Native format works | AWQ token-duplication corrupts TS-generic-heavy code | Mitigations partial; loop on long context |

See the per-model docs for failure-mode detail and proposed next steps.

## Host safety: repeat-tool-call guard

On 2026-04-19 a Ralph+Goose run against qwen2.5-coder-32b at 96K context
reproduced the documented "narrative + self-feedback loop" failure mode —
Phase 1 emitted zero `▸ write` calls, Phase 2 fired the literal command
`cd packages/events && pnpm add zod --save` 94 times in 3.5 minutes before
being killed manually. Each `pnpm add` spawned a Node subprocess tree;
the host was nearly destabilized.

Because this failure recurs across models under greedy + long-context
regimes (gemma had the AWQ-duplication variant; qwen has the
narrative-then-loop variant), the LiteLLM callback now includes a
**repeat-tool-call guard** that short-circuits the N+1-th identical call
in a row (default N=3). When triggered, the callback replaces the
assistant message with a text stop and lets the agent host hand control
back, so Ralph can move to validation rather than continue looping.

See [../../litellm/README.md](../../litellm/README.md) for mechanism,
threshold tuning (`LITELLM_REPEAT_THRESHOLD` env var), and what the guard
does not catch. The callback source lives at
[../../litellm/fix_tool_messages.py](../../litellm/fix_tool_messages.py);
the host copy is `/etc/litellm/fix_tool_messages.py` on airunner01.

This guard is a host-safety backstop, not a solution to the underlying
failure modes — it only prevents runaway load. Fixing the loops themselves
still requires either a different model, a different agent, or prompt
changes in Ralph.
