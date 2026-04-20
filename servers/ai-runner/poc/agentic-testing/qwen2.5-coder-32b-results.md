# qwen2.5-coder-32b — Agentic Reliability Results

Phase 4 (operational) testing of `Qwen/Qwen2.5-Coder-32B-Instruct-AWQ` driving
Goose + Ralph against a TypeScript monorepo. See
[README.md](./README.md) for what Phase 4 is.

## Summary — qwen2.5-coder-32b is also not currently usable for this workload

Phase 1 ranked it #1 by partial weighted score (0.671) and recommended it as the
"interactive coding" pick. Operational deployment surfaced two distinct
blockers, neither of which is the same problem we hit with gemma:

1. **Tool-call format mismatch with vLLM's hermes parser.** The model emits
   bare JSON or `<tools>{...}</tools>` blocks instead of the expected
   `<tool_call>{...}</tool_call>` tags. Required a server-side LiteLLM
   callback that buffers streaming chunks and rewrites them into proper
   OpenAI `tool_calls`.
2. **Narrative-instead-of-action behavior on long agentic prompts.** Even
   with the callback in place, the model spent its single Phase 1 dev step
   writing a 117-line markdown document describing the test files it
   "would create" — without ever calling the `write` tool. End-of-phase: zero
   files created, zero `▸ write` tool invocations.

We have **less data on qwen2.5 than on gemma** because we abandoned it after
one full Ralph run rather than iterate on tuning. Some of the failures from
that one run might now be salvageable with the post-hoc parser improvements
we made (see [Open questions](#open-questions)). We don't know.

## What we observed

### Tool-call format mismatch

`Qwen/Qwen2.5-Coder-32B-Instruct-AWQ` does not reliably emit `<tool_call>` XML
tags in its tool-calling output, despite vLLM being launched with
`--tool-call-parser hermes --enable-auto-tool-choice`. We tested four
configurations:

| Config | Model output |
|---|---|
| Native chat template + hermes parser | `<tools>\n{"name":"X","arguments":{...}}\n</tools>` (wrong tag) |
| `tool_chat_template_hermes.jinja` + hermes parser | bare JSON object, no tag wrapping |
| Custom Qwen2.5-specific chat template with strong format instructions | bare JSON, no tag wrapping |
| Strong system prompt explicitly requiring `<tool_call>` tags | `<|im_start|>{...}` (chat-template token leak + bare JSON) |

In all four, the hermes parser sees no `<tool_call>` tags and returns
`tool_calls: []`. The model knows the *content* of the tool call but not the
*wrapping*.

This is a documented quirk of the AWQ build — the FP16 weights apparently
follow the format better, but the AWQ has soft enough logits that it consistently
picks the more-frequent `<tools>` continuation at temperature 0.

### Mitigation: LiteLLM streaming callback

We added `async_post_call_streaming_iterator_hook` (and a non-streaming version)
to `/etc/litellm/fix_tool_messages.py`. It buffers all chunks for a streaming
response, runs an extractor over the assembled content, and re-emits a
synthetic stream with proper `tool_calls` deltas. The extractor handles:

- `<tool_call>{...}</tool_call>` (canonical hermes)
- `<tools>{...}</tools>` (Qwen2.5's preferred wrapping)
- Markdown code fences (```` ```json ```` / ```` ```python ````)
- Brace-balanced top-level JSON objects in plain text
- Both strict JSON and Python-literal-style dicts (single-quoted keys/values)
  via `ast.literal_eval` fallback

After the callback was in place, simple two-step Goose tests (write file →
shell ls) completed correctly end-to-end.

### Narrative-instead-of-action

The single full Ralph run we did against qwen2.5 (US-21.1, "Define Event
Schemas") produced:

- **Phase 1 (tests):** 0 tool invocations. The model emitted a 117-line
  markdown document narrating what tests it "will create," with file contents
  inlined in ```` ```typescript ```` code blocks. Zero `▸ write` markers in
  the log. Zero files appeared on disk.
- **Phase 2 (implementation):** 4 actual `▸ shell` invocations (`pnpm --filter
  @redacted/auth tsc/lint/test:unit/test:integration`), all of which
  presumably failed — the package-filter format `@redacted/auth` doesn't
  match how the monorepo names its packages. The model then emitted what
  looked like retries with the corrected package name, but as Python-dict
  JSON inside markdown code fences:

  ```
  ### Step 1: TypeScript Compilation
  ```json
  {"name": "shell", "arguments": {'command': 'pnpm --filter services/auth tsc --noEmit'}}
  ```
  ```

  Note the single-quoted `'command'` inside an otherwise double-quoted JSON —
  not parseable as JSON. The original (pre-hardening) callback rejected these
  with `json.loads`, so they never converted into real tool calls.

- **Net result:** ~6 real tool calls across both phases, zero useful work
  done, validation phase started against an empty implementation.

For comparison, gemma's first Ralph run on the same story produced 172 tool
invocations and actual files (just with corrupted TypeScript inside).

### Other observations

- Context: configured at 96K with YaRN rope-scaling (factor 3.0 over the
  native 32K). vLLM reported max possible at this config = 101,472 tokens with
  `--max-num-seqs 2`; we rounded down to 96K for safety.
- We did NOT observe gemma's token-duplication corruption pattern on
  qwen2.5. Whether that's because qwen2.5 doesn't have the same AWQ
  brittleness, or because the agent never got far enough to trigger it
  (only 4 successful tool calls), is unknown.

## Why it happens

### Tool format mismatch (high confidence)

Qwen2.5-Coder-32B's chat template tells the model to emit `<tool_call>` tags,
but the AWQ build's logits are soft enough that at temperature 0 it
consistently picks the more-frequent `<tools>` wrapping (the same tag the
template uses for the *list of available tools*). The model has high
probability mass on both `<tools>` (from the template's tool-list section)
and `<tool_call>` (from the format-instruction section), and AWQ's noise
pushes the wrong one over the line. Same root cause family as gemma's
duplication issue, different surface.

### Narrative behavior (lower confidence)

This one we have less direct evidence for. Plausible explanations:

- **Long context overwhelms the instruction-following signal.** The Ralph
  prompt is ~25K tokens (PRD + DEV_INSTRUCTIONS + progress); buried in that
  is a single instruction to "use tools, don't describe." At 25K context the
  weight on that instruction is small relative to the weight on the visible
  task description, and the model defaults to "describe what I would do" mode.
- **Coder-specialist training bias.** qwen2.5-coder may have been
  RLHF-tuned to *explain* its reasoning more than instruct-class models,
  making it lean toward narrative output even when given tools.
- **Chat-template artifacts.** We saw `<|im_start|>` tokens leak into
  visible content with one of our chat-template attempts. The same template
  rendering oddities could be confusing the model about whether it's in
  "describe" or "act" mode.

We didn't isolate which of these is dominant. With the parser hardening done
after the run, a re-test would tell us whether the narrative was actually
the model "trying to call tools but in the wrong format" all along (now
recoverable) or genuinely a refusal-to-act behavior (not recoverable
without prompting changes).

## What we didn't get to

Listed because they may matter for whether qwen2.5 is worth revisiting:

- **Re-run Ralph after hardening the parser.** The parser now handles
  Python-dict-in-markdown-fence and brace-balanced bare JSON. Phase 2's
  failed retries from the previous run might now succeed. We never tested
  this — we switched to gemma instead.
- **Sampling penalty tuning.** We didn't try `repetition_penalty` or
  `frequency_penalty` on qwen2.5. They might suppress the `<tools>` vs
  `<tool_call>` flip the same way they suppressed gemma's duplication.
  Untested.
- **Token-duplication regression probe.** The `z.infer<typeof X>`
  test we'd recommend for gemma — we never ran it on qwen2.5. Might find a
  similar issue, might not.
- **Multiple runs.** One Ralph run per model is not enough to characterize
  agentic reliability. We have one for each.

## Next steps

If qwen2.5 is worth revisiting:

1. **Re-run Ralph against qwen2.5 with the current LiteLLM callback** (the
   one with hardened JSON / Python-dict / markdown-fence handling).
   Cheap — one Ralph iteration, ~10–15 minutes. Tells us whether the
   "narrative" behavior was actually parseable tool calls in disguise.
2. **If still narrating, strengthen the system prompt** in `DEV_INSTRUCTIONS.md`
   with explicit, near-the-top instructions: "If you describe a file you would
   create instead of calling `write`, you have failed the task."
3. **Run the `z.infer<typeof X>` regression probe** at temperature 0 with
   30K of preceding TypeScript context. Pass = no `<<` or `typetypeof`
   substrings. Cheap — one curl. Establishes whether qwen2.5 has
   gemma's class of AWQ issue.
4. **If steps 1–3 produce a working setup**, run 3–5 Ralph iterations on
   different stories to characterize stability.

If qwen2.5 is not worth revisiting (more likely answer right now):

- Move on to testing one of the reasoning models (qwq-32b,
  deepseek-r1-qwen-32b). Their explicit think phase may serve as a buffer
  against both the format-mismatch and narrative-vs-action failure modes.

## Operational reminders

- The current LiteLLM callback at `/etc/litellm/fix_tool_messages.py` was
  built for qwen2.5's tool-call format issues. It still loads and runs
  under gemma deployment, but is effectively a no-op there because gemma
  emits proper tool_calls natively. Safe to leave in place.
- If switching back to qwen2.5, the LiteLLM model entry needs updating to
  point at the qwen HF id and the vLLM container needs restarting with
  qwen-specific flags (`--tool-call-parser hermes`, the YaRN
  `--hf-overrides` for 96K context). Backup configs at
  `/etc/litellm/config.yaml.bak.*` include the prior qwen setup.

## Update — 2026-04-19: second Ralph run with hardened callback + 96K context

Returned to qwen2.5 after running gemma for a while. Setup this time:

- vLLM serving `Qwen/Qwen2.5-Coder-32B-Instruct-AWQ` with
  `--tool-call-parser hermes`, `--enable-auto-tool-choice`,
  `--max-num-seqs 2`, `--enable-prefix-caching`, and YaRN rope-scaling
  to 96K (`factor=3.0` over native 32K, `max_position_embeddings=98304`).
- vLLM reports GPU KV cache size 101,520 tokens → max concurrency 1.06×
  at the full 96K context (i.e. exactly one full-window request at a time,
  fine for single-agent Ralph).
- LiteLLM callback has the hardened JSON / Python-literal / markdown-fence
  tool-call extractor (addresses the Qwen tool-format mismatch listed
  above), and — after the first run today — a new repeat-tool-call guard
  (details: [../../litellm/README.md](../../litellm/README.md)).

Ran two Ralph iterations against the same user story, back-to-back with the same PRD state.

### Run 1 (pre-guard): catastrophic self-feedback loop

- Phase 1 (tests): 150+ lines of markdown narrating what tests it "would"
  create. **Zero** `▸ write` tool calls. Zero files on disk.
- Phase 2 (implementation): ~20 reasonable tool calls (tsc, lint, test,
  package discovery) then locked into firing the literal command
  `cd packages/events && pnpm add zod --save` 94 times in 3.5 minutes.
  Each call spawned a pnpm/node subprocess tree; the host was nearly
  destabilized before the user killed Ralph manually.
- Failure-mode summary: 115 total shell calls, 94 duplicates (82%),
  zero writes. Same class as gemma's AWQ-duplication issue — greedy
  temperature=0 + the model re-reading its own last tool call and tool
  result — but the surface is different (identical tool call repetition
  rather than corrupted code generation).

### Run 2 (with host-safety guard in place): clean exit, no meaningful story progress

- Guard deployed: N+1-th identical consecutive tool call is dropped and
  replaced with `finish_reason: stop`. Default threshold 3 ⇒ 4th repeat
  blocked. See [../../litellm/README.md](../../litellm/README.md) for
  mechanism.
- Guard **did not fire** this run — the model didn't reproduce the exact
  loop. It produced real work: 12 `▸ write` calls, 44 `▸ shell` calls,
  a handful of `cat` / `edit` / `todo_write`. Created
  `packages/events/{package.json, tsconfig.json, src/*.ts}` with schema
  files for auth/users/recipes/grocery/subscriptions/notifications/
  learning/achievements/subjects/index plus two test files.
- Phase 1 still narrated extensively before acting. The "write 1 file,
  describe 10 more" pattern persists.
- Validation rejected the story 5 times in a row (max retries reached),
  on legitimate acceptance-criteria gaps: "Event schemas are versioned
  — no mention of versioning in the progress update", "Event schemas
  are tested — no mention of testing". Each retry produced more code
  but didn't close the gaps.
- Ralph exited cleanly at iteration 1/1 with `STORY INCOMPLETE`, committed
  a `wip(US-21.1)` marker, cleaned up Testcontainers. 9 minutes total
  wall-clock, no runaway subprocesses, no host strain.

### What run 2 tells us

The LiteLLM callback + repeat-guard together make the host safe to leave
Ralph running unattended, and qwen2.5 can actually do tool calls at
long context without exploding. But:

- **Instruction-following quality is the binding constraint, not
  infrastructure.** Given strict DEV_INSTRUCTIONS, the same PRD, and the
  same per-phase prompt, a Claude-backed Ralph iteration will typically
  close acceptance criteria like "versioned" and "tested" without
  needing the validation loop to re-invoke 5 times. qwen2.5 does the
  rough work but misses criteria nuance.
- **Phase 1 narration is not a parser problem.** Even with the hardened
  parser in place (so "tool calls in the wrong wrapping" would be
  caught), the model produces markdown descriptions of tests more than
  it calls `write`. This is model behavior under ~25K of Ralph prompt,
  not an artifact we can extract our way out of.
- **The repeat-guard is a backstop, not a fix.** It protects against the
  run-1-style meltdown but does not make the model more capable. Its
  presence means we can now run experiments without fearing the host.

### Conclusion on qwen2.5 for this workload

Stop iterating on qwen2.5 for Ralph. The operational fixes (tool-format
extractor, repeat guard, 96K YaRN) mean qwen2.5 is *operable*, but the
code quality and instruction-following gap versus Claude is the binding
constraint, and that gap is outside what infrastructure or sampling
tweaks can close on AWQ at greedy decoding.

Next model to try in agentic-testing track: Devstral-Small-2-24B-Instruct
(Mistral's agent-tuned coder, 24B FP8, already cached on airunner01).
See [devstral-small-2-24b-results.md](./devstral-small-2-24b-results.md)
once that evaluation runs.
