# gemma4-31b — Agentic Reliability Results

Phase 4 (operational) testing of `QuantTrio/gemma-4-31B-it-AWQ` driving Goose +
Ralph against a TypeScript monorepo. See
[README.md](./README.md) for what Phase 4 is and why it's separate from
Phase 1's track-based evaluation.

## Summary — gemma4-31b is not currently usable for this workload

Phase 1 ranked it #1 on correctness (HumanEval+ 96.5% / 92.8%) and we deployed
it as the Ralph backend on that basis. Two consecutive full Ralph runs against
production code demonstrated a hard failure mode that prevents the loop from
converging: AWQ-quantization token-duplication corruption on TypeScript
generics, amplified by Goose's greedy sampling and by the agent feeding its own
broken output back into context.

The failure is reproducible on demand. Mitigations (sampling penalties) suppress
it on isolated short prompts but the long-context Ralph regime is still under
verification. Even in the best case, mitigations don't address the underlying
mechanism — they just shift the threshold.

## What we observed

Two clean Ralph runs, both starting from the same state, both with
US-21.1 ("Define Event Schemas") as the assigned story. In each, the agent's
**first** edit to `packages/events/src/validation.ts` produced corrupted
TypeScript:

```typescript
// First write, both runs:
export type EventEnvelope = z.infer<<typeoftypeof EventEnvelopeSchema>;
export function validateEvent<<TT>(...)
```

`<typeof X>` got duplicated to `<<typeoftypeof X>`; the generic `<T>` collapsed
to `<<TT>`. The agent then noticed the file didn't compile, called `cat`/`view`
to inspect it, and ran `edit` to fix it. Each subsequent edit pulled the
broken text back into the model's input, so next-token prediction biased toward
extending the corruption:

```
edit attempt 1:  <<typeoftypeof
edit attempt 2:  <<<typetypeoftypeof
edit attempt 3:  <<<<tytypetypeoftypeof
edit attempt N+: <<<<<tyttypetypeoftypeof  (etc.)
```

By the time the run was killed, ~9 minutes and 100+ tool cycles had been spent
on this single file with no convergence. Tool-calling itself was working
correctly — 172 tool invocations in one run vs ~6 in our prior qwen2.5-coder
test — gemma is *trying* to do the right work; it just can't write the file.

## Why it happens

Three factors compound:

1. **AWQ logit imprecision.** The quant compresses FP16 weights to ~4 bits,
   adding numerical noise to logits. On token continuations where two
   candidates have nearly-equal probability under FP16, the AWQ noise can
   flip the winner. After `z.infer<` the two top candidates are `typeof`
   (correct here) and `<` (correct in nested-generic patterns). FP16 picks
   `typeof` cleanly; AWQ picks `<` enough of the time for greedy decoding to
   commit. The model still "wants" to emit `typeof`, so it follows up with
   `typeof` on the next step — yielding `<<typeof`. Repeats once more →
   `<<typeoftypeof`.

2. **Greedy decoding (temperature 0).** Goose hardcodes `temperature: 0` for
   determinism. With temperature > 0, occasional sampling around the noisy
   logits would correct the path. Greedy commits to whatever the noisy
   argmax says, every token, every time.

3. **Self-feedback into context.** Once the broken file exists, every agent
   step passes the file content back to the model via tool results. Next-token
   prediction over `<<<typetypeoftypeof` continues the pattern; the model
   learns the wrong syntax from its own prior output within the same
   conversation. Each edit attempt produces *worse* corruption than the
   previous one.

The pattern is specific to TS generics because `z.infer<typeof X>` is a
**rare** pattern in Gemma's training data (Zod is newer than much of the
training corpus), so the logit margin is naturally smaller there. Most code
patterns are robust because the margin is wider.

FP16 weights would not have this problem — the gap is wide enough that
quantization noise can't flip the winner. But FP16 Gemma 4 31B is ~62 GB and
doesn't fit on 2× RTX 3090 (48 GB total). AWQ is what makes it fit.

## Mitigations attempted

| Setting | Result |
|---|---|
| Stock config | First write corrupts; agent enters edit loop. |
| `repetition_penalty: 1.05` | Short isolated tests clean. Full Ralph context still corrupts on first write. |
| `repetition_penalty: 1.15` | Same — short tests clean, Ralph still corrupts (worse: `<<<<tytypetypeof`). |
| `repetition_penalty: 1.2` + `frequency_penalty: 0.3` | Targeted reproduction of 5 sequential `z.infer<typeof X>` declarations is now clean. Long-context Ralph result still pending verification. |

Why this isn't a real fix: penalties suppress the *symptom* by reducing the
logit of recently/frequently emitted tokens, not the *cause* (AWQ noise on a
specific token competition). They work when the duplicated token is exactly
the recent one (`typeof` after `typeof`) but get less reliable when the
corruption pattern shifts (`<<<<` then `tytypetypeof` is a different pattern).
We're tuning a knob that's adjacent to the problem, not on it.

## What did NOT work / blocked next steps

- **Forcing a non-zero temperature.** Goose hardcodes `temperature: 0` and
  doesn't expose it via env var or CLI. We tried overriding via LiteLLM's
  `async_pre_call_hook`, but that hook does not fire in the current LiteLLM
  proxy build (only post-call and streaming-iterator hooks fire). Effectively
  unreachable without code changes to Goose or insertion of a small
  middleware proxy between Goose and LiteLLM.
- **Disabling `--enable-prefix-caching`.** Considered but expected to be a
  no-op — prefix caching just reuses identical KV computations and doesn't
  change deterministic outputs.

## What the POC missed (and what would have caught this)

Phase 1 evaluated:
- single-turn codegen on small isolated problems (~150 tokens prompt)
- temperature 0.001 on HumanEval+ (effectively greedy)
- no agent self-feedback
- prompt sizes well under 5K tokens

Phase 1 did not evaluate:
- multi-turn agent loops with accumulated context
- sampling under the agent host's actual settings (`temperature: 0` greedy)
- the model viewing its own prior output and being asked to amend it
- prompts in the 25K–80K token range

The corruption mode requires all of those conditions. None of the Phase 1
problems exercised the regime, so gemma4-31b looked clean while having a
serious latent issue for the actual workload.

A targeted regression probe would catch this in <5 minutes:

> Generate 30 sequential `export type X = z.infer<typeof X_Schema>;`
> declarations at temperature 0 with 30K of preceding TypeScript context.
> Pass = no `<<` or `typetypeof` substrings in output.

Worth adding to the eval suite as a guard against the same class of issue with
other AWQ-quantized models.

## Next steps

Roughly in order of effort to expected payoff:

### 1. Wedge a non-zero temperature into the request path

Most likely actual fix — directly addresses the greedy-decoding amplifier.
Three feasible approaches:

- **Patch Ralph or Goose's openai provider** to send `temperature: 0.1`. The
  Goose Rust source has a hardcoded value to change; the Ralph wrapper script
  could pre-process the requests if Goose surfaced a hook.
- **Insert a tiny FastAPI/Express middleware** between Goose and LiteLLM that
  rewrites `temperature` in the JSON body before forwarding. ~30 lines of
  code, no upstream changes.
- **Newer LiteLLM with working `async_pre_call_hook`.** Worth checking
  whether the latest release has fixed the hook chain — would let us reuse
  the existing callback file.

### 2. Verify whether the current penalties hold at full Ralph context length

The targeted 5-line reproduction is clean at `repetition_penalty: 1.2 +
frequency_penalty: 0.3`. Need to run a clean Ralph iteration end-to-end (with
the corrupted files reverted from the working tree first) to know if it holds
at 25K+ context. If yes, this becomes the operational baseline. If no, we
escalate to (3).

### 3. Drop `--max-model-len` from 128K to 32K

Less context-length amplification of AWQ noise. Ralph's base prompt is ~25K,
which leaves only ~7K for accumulated tool-call history. Tighter, but likely
manageable for short Ralph iterations.

### 4. Try a different gemma quant

The `QuantTrio` AWQ build is a community quant. If a more recent / better-
calibrated AWQ or a GPTQ build exists for gemma-4-31B-it, swap and re-test.
Phase 1 didn't compare quants — only one was tested per model.

### 5. Re-test the reasoning models for agentic use

`qwq-32b` and `deepseek-r1-qwen-32b` both scored 93.3% / 87.2% on HumanEval+
in Phase 1, just below gemma. We haven't run either against Ralph yet.
Reasoning models tend to have cleaner tool-calling habits and the explicit
think phase may serve as a self-correcting buffer that mitigates the kind of
"committed to the wrong token" failure we see on greedy gemma.

Caveat: their Phase 1 wall-clock was 2-3× longer than gemma's, and the
reasoning think-phase strips tokens that the corruption mechanism may still
generate during. Worth a probe but no guarantee.

### 6. Re-evaluate the Phase 1 ranking weights

The current "winner on correctness" framing in
[../coding-models-results.md](../coding-models-results.md) doesn't penalize
models for AWQ/sampling brittleness. A future Phase 1 revision could add an
operational-readiness component that includes:

- Behavior under greedy + 30K+ context
- Tool-call format compatibility with Goose
- Stability across 50+ self-feedback cycles

This wouldn't have promoted a different model to #1 in our case, but it
would have flagged gemma's risk before deployment instead of after.

## Operational reminders

- **Always revert untracked changes in the target directory between Ralph
  runs** unless the prior run completed cleanly. Corrupted files in the
  working tree re-trigger the loop on iteration 1 of the next run.
- **Watch the log for `<<` or `typetypeof` substrings early.** If they appear
  in the first developer-phase write, kill the run before it burns an hour
  in an edit loop.
- **Configs that affect the model's behavior live in `/etc/litellm/config.yaml`
  and `/etc/vllm/env` on airunner01.** Backups of prior versions live next to
  them as `.bak.<timestamp>`. Restore is a single `cp` + `systemctl restart`.
