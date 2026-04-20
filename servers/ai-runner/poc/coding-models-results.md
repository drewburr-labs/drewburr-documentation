# Coding Model POC — Phase 1 Results

Eleven candidate models benchmarked on airunner01 (2× RTX 3090, TP=2, vLLM) against the
plan in [coding-models-evaluation.md](./coding-models-evaluation.md). This document
summarizes what the data says.

Two of the thirteen candidates did not run: `gemma4-26b` (bitsandbytes quant times out
in vLLM; needs an AWQ build) and `qwen3-coder-80b` (the only community AWQ quant is
broken). Both are blocked on external quant work and are not included below.

> **Heads-up before relying on this ranking for production agent use:** Phase 1
> tested isolated single-turn problems on small prompts. Phase 4 (operational
> Ralph+Goose testing) surfaced AWQ + greedy + long-context
> failure modes that block the top-ranked model (`gemma4-31b`) from being
> usable as-is. See [agentic-testing/](./agentic-testing/) before committing to
> a production model choice.

## TL;DR

- **Winner on pure correctness: `gemma4-31b`.** Tops HumanEval+ (96.5% / 92.8%),
  perfect on T1 JavaScript, clean pass on every context-stress level, no weak track.
- **Winner for interactive coding: `qwen2.5-coder-32b`.** Highest partial weighted
  score (0.671), matches gemma4-31b on tracks, and returns the first visible token in
  42 ms — feels instant at the editor.
- **Winner when reasoning actually helps: `deepseek-r1-llama-70b`.** Highest
  HumanEval+ extra among reasoning models (89.0%), but its 2.1 s TTFT, 37 tok/s
  throughput, and 40% FIM make it unsuitable for anything other than asynchronous
  batch work.
- **Thinking is a net negative on single-turn codegen.** On HumanEval+ base, the
  reasoning models average ~91.9% — solid but still beaten by gemma4-31b. On FIM
  (completion, where thinking has nothing to work with), reasoning models are
  consistently worse than the instruct models of comparable size.
- **FIM is the most discriminating track.** `codestral-22b` scored 0/20; the rest
  range 40–90%. T2 (bug-fixing) is saturated — nine of eleven models hit 99–100%,
  so it barely distinguishes candidates at this level.

## Leaderboard

Partial weighted score below uses the plan's fixed-weight components (T1 × 0.30 +
T2 × 0.25 + T3 × 0.15). Throughput (15%), refactoring quality (10%), and agentic
reliability (5%) are left at zero — throughput needs cross-model normalization,
refactoring requires manual review, and the agentic track wasn't run. Use it for
ordering, not as a final grade.

| Rank | Model                  | Reasoning | HumanEval+ base / extra |    T1     |   T2   |  T3   |   tok/s   | TTFT p50 | Partial weight |
| ---: | :--------------------- | :-------: | :---------------------: | :-------: | :----: | :---: | :-------: | -------: | -------------: |
|    1 | qwen2.5-coder-32b      |     —     |      89.6% / 84.6%      |   95.2%   | 100.0% | 90.0% |   69.3    |    42 ms |      **0.671** |
|    2 | deepseek-coder-v2-lite |     —     |      82.9% / 76.6%      |   93.3%   | 99.0%  | 95.0% |   51.6    |    66 ms |          0.670 |
|    3 | gemma4-31b             |     —     |    **96.5% / 92.8%**    |   97.1%   | 100.0% | 80.0% |   64.9    |    56 ms |          0.661 |
|    4 | qwen3-30b              |     ✓     |      86.9% / 82.6%      | **98.1%** | 95.1%  | 80.0% | **201.6** |   409 ms |          0.652 |
|    5 | phi-4                  |     —     |      86.3% / 81.0%      |   93.3%   | 100.0% | 80.0% |   50.7    |    58 ms |          0.650 |
|    6 | qwq-32b                |     ✓     |      93.3% / 87.2%      |   95.2%   | 100.0% | 65.0% |   70.2    |  1146 ms |          0.633 |
|    7 | deepseek-r1-qwen-32b   |     ✓     |      93.3% / 87.2%      |   94.9%   | 99.0%  | 60.0% |   70.3    |  1143 ms |          0.622 |
|    8 | qwen2.5-coder-7b       |     —     |      86.6% / 80.7%      |   94.3%   | 99.0%  | 60.0% |   91.9    |    32 ms |          0.620 |
|    9 | llama3.3-70b           |     —     |      85.1% / 78.8%      |   94.3%   | 100.0% | 55.0% |   36.3    |    82 ms |          0.615 |
|   10 | deepseek-r1-llama-70b  |     ✓     |      93.9% / 89.0%      |   95.1%   | 99.0%  | 40.0% |   37.4    |  2144 ms |          0.593 |
|   11 | codestral-22b          |     —     |      79.6% / 73.7%      |   93.3%   | 99.0%  | 0.0%  |   96.1    |    31 ms |          0.527 |

`tok/s` is answer-only completion throughput measured by vLLM (see caveat on reasoning
models below). TTFT is the p50 of 5 warm samples.

## Thinking vs instruct

Same tracks, grouped by whether the model emits a visible `<think>` block:

|                  | Instruct (n=7) |          Reasoning (n=4) |
| ---------------- | -------------: | -----------------------: |
| HumanEval+ base  |  **86.7% avg** |                91.9% avg |
| HumanEval+ extra |      81.2% avg |            **86.5% avg** |
| T1 codegen       |      94.4% avg |                95.8% avg |
| T2 bugfix        |      99.6% avg |                98.3% avg |
| T3 FIM           |  **65.7% avg** |                61.3% avg |
| TTFT p50         |  **52 ms avg** |              1210 ms avg |
| Answer tok/s     |       65.8 avg | 94.9 avg (skewed by MoE) |
| Wall-clock total |     21 min avg |              161 min avg |

Reasoning pulls ahead by ~5 pts on HumanEval+, which matches the intuition that chain
of thought helps on harder problems. But the spread is entirely wiped out by
`gemma4-31b` (instruct, 96.5% base), which beats every reasoning model.

Thinking is a wash or a regression on FIM. That's expected — FIM is a constrained
completion task, not a problem to solve, and extra reasoning tokens don't have anywhere
productive to go. `deepseek-r1-llama-70b` dropping to 40% on FIM is a concrete example:
the reasoning parser strips the `<think>` block, and what's left is often an empty or
truncated completion.

The real cost of reasoning is wall-clock. `deepseek-r1-llama-70b` needed 4.3 hours for
one pass of the suite; `qwen2.5-coder-7b` needed 3 minutes for comparable scores on the
tracks. For interactive editor use, that's the end of the conversation — reasoning
models are async-batch tools on this hardware.

## Per-language breakdown

### Track 1 (code generation)

| Model                  |     Py |     JS |     Go | Overall |
| :--------------------- | -----: | -----: | -----: | ------: |
| qwen3-30b              | 100.0% |  91.3% | 100.0% |   98.1% |
| gemma4-31b             | 100.0% | 100.0% |  85.0% |   97.1% |
| qwen2.5-coder-32b      | 100.0% |  91.3% |  85.0% |   95.2% |
| qwq-32b                | 100.0% |  91.3% |  85.0% |   95.2% |
| deepseek-r1-llama-70b  | 100.0% |  91.3% |  85.0% |   95.1% |
| deepseek-r1-qwen-32b   | 100.0% |  91.3% |  85.0% |   94.9% |
| llama3.3-70b           | 100.0% |  87.0% |  85.0% |   94.3% |
| qwen2.5-coder-7b       | 100.0% |  87.0% |  85.0% |   94.3% |
| codestral-22b          | 100.0% |  91.3% |  75.0% |   93.3% |
| deepseek-coder-v2-lite | 100.0% |  91.3% |  75.0% |   93.3% |
| phi-4                  | 100.0% |  91.3% |  75.0% |   93.3% |

Every model scored 100% on T1 Python — the 20 HumanEval-derived problems are too easy
to discriminate. Node.js clustered at 91.3% (gemma4-31b hit a perfect 100%). Go is the
stratifier: `codestral-22b`, `phi-4`, and `deepseek-coder-v2-lite` only got 75%;
`qwen3-30b` was the only model to get 100%.

### Track 2 (bug-fixing)

| Model                  |     Py |     JS |     Go | Refactor | Overall |
| :--------------------- | -----: | -----: | -----: | -------: | ------: |
| gemma4-31b             | 100.0% | 100.0% | 100.0% |   100.0% |  100.0% |
| llama3.3-70b           | 100.0% | 100.0% | 100.0% |   100.0% |  100.0% |
| phi-4                  | 100.0% | 100.0% | 100.0% |   100.0% |  100.0% |
| qwen2.5-coder-32b      | 100.0% | 100.0% | 100.0% |   100.0% |  100.0% |
| qwq-32b                | 100.0% | 100.0% | 100.0% |   100.0% |  100.0% |
| codestral-22b          |  97.8% | 100.0% | 100.0% |   100.0% |   99.0% |
| deepseek-r1-llama-70b  |  97.8% | 100.0% | 100.0% |   100.0% |   99.0% |
| deepseek-r1-qwen-32b   |  97.6% | 100.0% | 100.0% |   100.0% |   99.0% |
| deepseek-coder-v2-lite | 100.0% | 100.0% |  94.4% |   100.0% |   99.0% |
| qwen2.5-coder-7b       | 100.0% | 100.0% |  94.4% |   100.0% |   99.0% |
| qwen3-30b              |  97.8% |  81.8% |  88.9% |   100.0% |   95.1% |

Essentially saturated. Nine models hit 99–100%; `qwen3-30b` was the outlier at 95.1%
overall, with a conspicuous 81.8% on the JS bug-fixing subset. Refactoring correctness
was 100% for all models (quality is still pending manual review).

### Track 3 (fill-in-the-middle)

The most useful discriminator:

| Model                  |    Py |    JS |   Go | Overall |
| :--------------------- | ----: | ----: | ---: | ------: |
| deepseek-coder-v2-lite |  100% | 85.7% | 100% |   95.0% |
| qwen2.5-coder-32b      |  100% | 85.7% |  80% |   90.0% |
| gemma4-31b             | 87.5% | 71.4% |  80% |   80.0% |
| phi-4                  | 87.5% | 71.4% |  80% |   80.0% |
| qwen3-30b              | 87.5% | 57.1% | 100% |   80.0% |
| qwq-32b                | 50.0% | 57.1% | 100% |   65.0% |
| qwen2.5-coder-7b       | 62.5% | 57.1% |  60% |   60.0% |
| deepseek-r1-qwen-32b   | 37.5% | 85.7% |  60% |   60.0% |
| llama3.3-70b           | 12.5% | 71.4% | 100% |   55.0% |
| deepseek-r1-llama-70b  | 37.5% | 28.6% |  60% |   40.0% |
| codestral-22b          |    0% |    0% |   0% |    0.0% |

Two observations here matter for a practical editor/agent deployment:

1. **`codestral-22b` is broken at FIM** as configured. The model has documented FIM
   token support but the benchmark used chat-prompt FIM (no native tokens set in the
   model config). Every completion was wrapped or padded to fail the test. This may
   be fixable by wiring up codestral's native `[PREFIX]/[SUFFIX]/[MIDDLE]` tokens — a
   reason to keep codestral off the Phase 2 list until that's verified.
2. **Reasoning models are systematically worse at FIM than instruct models of the same
   family.** deepseek-r1-qwen-32b (60%) vs qwen2.5-coder-32b (90%); deepseek-r1-llama-70b
   (40%) vs llama3.3-70b (55%). Rolling a reasoning model into editor-FIM duty is going
   to degrade autocomplete quality.

## Performance vs correctness

| Model                  | HumanEval+ base | tok/s (answer) | TTFT p50 |
| :--------------------- | --------------: | -------------: | -------: |
| qwen3-30b              |           86.9% |      **201.6** |   409 ms |
| qwen2.5-coder-7b       |           86.6% |           91.9 |    32 ms |
| codestral-22b          |           79.6% |           96.1 |    31 ms |
| gemma4-31b             |       **96.5%** |           64.9 |    56 ms |
| qwen2.5-coder-32b      |           89.6% |           69.3 |    42 ms |
| deepseek-r1-qwen-32b   |           93.3% |           70.3 |  1143 ms |
| qwq-32b                |           93.3% |           70.2 |  1146 ms |
| phi-4                  |           86.3% |           50.7 |    58 ms |
| deepseek-coder-v2-lite |           82.9% |           51.6 |    66 ms |
| llama3.3-70b           |           85.1% |           36.3 |    82 ms |
| deepseek-r1-llama-70b  |           93.9% |           37.4 |  2144 ms |

**Pareto frontier** for the "instant-response" regime (TTFT < 100 ms) is
`gemma4-31b → qwen2.5-coder-32b → qwen2.5-coder-7b → codestral-22b`. `gemma4-31b` is
the highest-quality model that still feels snappy, and `qwen2.5-coder-32b` is a
close-second with better Phase 1 scores elsewhere.

`qwen3-30b` is the one reasoning model that doesn't pay the usual throughput penalty —
it's a mixture-of-experts model with 3B active parameters per token, so it runs at 200
tok/s while still reasoning. Its TTFT (409 ms) is much lower than the dense reasoning
models, but its HumanEval+ score (86.9%) lands in non-reasoning territory, so the
thinking isn't obviously paying off on this workload.

The two dense 70B models (`llama3.3-70b`, `deepseek-r1-llama-70b`) are both throughput-
bound at ~37 tok/s on TP=2 × 3090. That's slow enough that they're only worth deploying
when the quality delta matters more than latency — so for batch evaluation, not for an
IDE.

## Context stress test

The "stress" probe asks each model to echo `READY` at prompt lengths of 4K/8K/16K/32K.
Results:

- **Clean pass through 32K:** `gemma4-31b`, `qwen2.5-coder-32b`, `qwen2.5-coder-7b`.
- **Pass through 16K, error at 32K:** `codestral-22b` (configured max 16384),
  `phi-4` (configured 16384).
- **Incoherent at 16K:** `deepseek-coder-v2-lite` (configured 16384, model degrades).
- **Only tested to 8K:** `llama3.3-70b` (configured 8192).
- **"Incoherent" at every level:** all four reasoning models. This is almost
  certainly a test artifact, not a real coherence issue — the reasoning-parser
  strips the `<think>` block, and what remains is an empty or near-empty `content`
  field that doesn't match the literal `READY` check. The same models scored
  93–94% on Track 1 codegen at much longer prompts, so they're clearly functional;
  the context-stress probe just isn't designed for them. Re-running this track
  with `enable_thinking=false` (or adjusting the probe to also read
  `message.reasoning`) is the right fix before drawing conclusions about
  reasoning-model long-context behavior.

## Consistency / anomalies worth flagging

- **`qwen3-30b` has an inconsistent Track 2.** 100% Python bug-fix, but 81.8% JS
  (9/11) — the only model to miss on T2 JS. Worth re-running with a different seed
  to see if this is noise; if it's stable, it's a signal the MoE routing is picking
  the wrong expert for JS-specific idioms.
- **`deepseek-r1-llama-70b` drops hard on FIM-Python (37.5%) and FIM-JS (28.6%).**
  That's a ~60-point gap vs the non-reasoning llama3.3-70b on FIM-Python. Strong
  evidence that the reasoning distillation hurt the model for structured completion
  tasks.
- **`deepseek-r1-qwen-32b` Python FIM is 37.5%**, far below its qwen2.5-coder-32b
  cousin at 100%. Same pattern — reasoning distill degrades FIM quality.
- **`codestral-22b` Track 3 is 0.0%.** Almost certainly a benchmark-harness mismatch
  (native FIM tokens not wired up), not a model capability issue. Don't conclude
  codestral is "bad at FIM" from this number — re-run with proper FIM tokens.
- **Reasoning-model `reasoning_tokens_observed: 0`.** vLLM strips the `<think>` block
  before reporting usage, so the throughput numbers above count only the _visible_
  completion tokens. Actual GPU work per request was much higher; the reported
  throughput understates real load for reasoning models. This is called out in the
  result JSON's throughput `note` field.

## Hardware footprint

VRAM usage at model load, across both GPUs (TP=2, 0.95 utilization target):

| Model                  | VRAM used | VRAM free |
| :--------------------- | --------: | --------: |
| qwen3-30b (MoE 30B)    |   47.6 GB |    0.9 GB |
| qwen2.5-coder-7b       |   47.4 GB |    1.1 GB |
| codestral-22b          |   47.3 GB |    1.3 GB |
| gemma4-31b             |   47.0 GB |    1.6 GB |
| deepseek-coder-v2-lite |   47.6 GB |    0.9 GB |
| qwen2.5-coder-32b      |   46.4 GB |    2.2 GB |
| qwq-32b                |   46.4 GB |    2.2 GB |
| deepseek-r1-qwen-32b   |   46.4 GB |    2.2 GB |
| phi-4                  |   46.5 GB |    2.1 GB |
| llama3.3-70b           |   45.5 GB |    3.0 GB |
| deepseek-r1-llama-70b  |   45.5 GB |    3.0 GB |

All fit in the 48 GB total VRAM pool comfortably. The 70B AWQ builds use the most
weight memory (~36 GB) but reserve less for KV cache, which is why
`deepseek-r1-llama-70b` hit a context-length ceiling during this POC (patched to 16384
at the cost of ~5.3 GB KV, still within headroom — see `benchmark.py:~204`).

## Recommendations for Phase 2

Pre-deciding which models to send through SWE-bench Lite. Two clear picks plus one
conditional:

1. **`gemma4-31b`** — highest HumanEval+, clean 32K context, solid tracks. The
   reference point we want to beat in any future evaluation.
2. **`qwen2.5-coder-32b`** — highest partial Phase 1 score, best FIM among the
   high-quality instruct models, 42 ms TTFT. The "use this for the IDE" candidate.
3. **`deepseek-r1-llama-70b`** — conditional. If the Phase 4 agentic-reliability
   track (unscored here) shows a real advantage from thinking, this wins the
   reasoning bracket. Otherwise it's too slow to justify over the instruct 70B.

Not advancing:

- **`codestral-22b`** — fix the FIM native-token config before re-evaluating. As
  tested, it can't do the FIM workload at all.
- **`llama3.3-70b`** — solid but strictly dominated by `gemma4-31b` and
  `qwen2.5-coder-32b` on every quality metric, while being roughly 2× slower.
- **`qwen2.5-coder-7b`** — fine for a local/offline mode, but qwen2.5-coder-32b is
  close on latency and better everywhere else.
- **`phi-4`, `deepseek-coder-v2-lite`** — middle-of-pack results without any axis
  where they clearly win.

## Working example — TypeScript monorepo, agent-driven full-stack

Concrete target:

SaaS platform built as a pnpm monorepo — 100% TypeScript, 7 Express micro-services + 3
Next.js apps + 3 shared packages (~9.7 K TS files, 198 test files). Stack: Next.js 14,
Express, Prisma, PostgreSQL, Elasticsearch, NATS pub-sub. Strict types, Zod validation
throughout, TDD culture with Vitest + TestContainers.

An agent working on this codebase mostly does:

1. **Cross-service feature work.** Prisma migration + ES
   mapping + types package + service method + route + event schema + tests.
2. **Read-then-edit loops** (far more than from-scratch codegen). Good FIM matters
   because the agent is constantly amending existing files.
3. **Test authoring** alongside every change. Vitest unit + integration + pact tests.
4. **Framework-dense work** (Prisma queries, NATS subjects, Next.js routing) where
   knowing the library matters more than raw coding ability.
5. **Long multi-file context** — touching types → service → route → test in one turn.
   Multi-turn sessions accumulate quickly beyond 16 K.

What matters in the data:

1. Strong **T1 JS** (new code) **and T3 JS** (edit/FIM) — both are daily activity.
2. **Clean 32 K context** — long sessions over many files need it.
3. **High HumanEval+ base/extra** — proxy for generalization beyond toy codegen. The
   project is framework-dense, so broader training matters.
4. **Sub-100 ms TTFT** — a multi-step agent turn at 1 s TTFT stacks into a half-minute
   wait per user prompt.

Filtered data slice:

| Model                |    T1 JS |     T2 JS |     T3 JS | 32 K stress |  TTFT p50 | HumanEval+ base / extra |
| :------------------- | -------: | --------: | --------: | :---------: | --------: | ----------------------: |
| gemma4-31b           | **100%** |      100% |     71.4% |   ✅ pass   |     56 ms |       **96.5% / 92.8%** |
| qwen2.5-coder-32b    |    91.3% |      100% | **85.7%** |   ✅ pass   | **42 ms** |           89.6% / 84.6% |
| deepseek-r1-qwen-32b |    91.3% |      100% |     85.7% |    error    |   1143 ms |           93.3% / 87.2% |
| qwen3-30b            |    91.3% | **81.8%** |     57.1% |    error    |    409 ms |           86.9% / 82.6% |
| llama3.3-70b         |    87.0% |      100% |     71.4% |  only 8 K   |     82 ms |           85.1% / 78.8% |

**Primary pick: `gemma4-31b`.** This codebase rewards _breadth_ over coder-specialist
depth. The agent spends a lot of time wiring Prisma schemas, writing Elasticsearch
queries, handling NATS event plumbing, and navigating Next.js route handlers — general
framework fluency, which gemma gets from broader pretraining. It wins on correctness
(HumanEval+ 96.5% / 92.8% — the best in the POC), perfect on both T1 JS (new code) and
T2 JS (bug-fixing), and passes 32 K context cleanly. The one weak spot is T3 JS FIM
(71.4%) — if the agent does a _lot_ of in-place code editing, you'll feel that.

**Strong alternate: `qwen2.5-coder-32b`.** Swap in when the workload tips toward edit-
heavy days: long refactor passes, test-body filling, small tweaks across many files.
Matches gemma on T1/T2 JS, beats it on T3 JS FIM by ~14 points (85.7% vs 71.4%), and
is faster at 42 ms TTFT. Gives up ~8 points on HumanEval+ extra, so cross-file feature
work with tricky edge cases lands slightly worse.

A reasonable operational pattern: **gemma4-31b as the default**, `qwen2.5-coder-32b`
available for "editor-mode" agent tasks where FIM quality dominates (bulk renames,
targeted patches, test backfills).

**Reasoning option: `deepseek-r1-qwen-32b`.** Only meaningful if the instruct agent
starts looping, mishandling cross-service data flow, or getting the tier-based access
control checks wrong. Strong HumanEval+ (93.3 / 87.2), ties coder-32b on JS, and
thinking helps when the agent needs to plan across tool calls. Accept 1.1 s TTFT and
~10× wall clock per turn, and note that it **errors at 32 K context stress** — not
ideal for long multi-file sessions in a monorepo this size.

**Avoid for this use-case:**

- `qwen3-30b` — 81.8% on T2 JS bug-fixing. That's the single-language regression in
  our data; an agent doing TypeScript all day will hit it repeatedly. The 200 tok/s
  MoE speed doesn't buy back the reliability loss.
- `deepseek-r1-llama-70b` — 40% FIM and 2.1 s TTFT kill edit-heavy agent turns in a
  codebase with this much existing code to modify.
- `codestral-22b` — FIM is 0% as configured, and the project is edit-heavy.
- `llama3.3-70b` — stress test only went to 8 K (its configured `max_model_len`).
  Not enough for a long agent session over a 9.7 K-file monorepo.

**Caveat:** our JS tests were plain JavaScript, not strict TypeScript with Prisma
generics or Zod inference. Real-world complex-type reasoning could shift scores a
bit, especially for models without strong TS-specific training. Worth a small
follow-up probe on a couple of prompts before committing to one
model for production agent use.

## Known limitations of this POC

- **Agentic track (Track 4) was not run.** It requires Goose integration and was
  descoped to fit the single-pass benchmarking window. The partial weighted score
  above is missing the 5% agentic component and the 15% throughput component —
  final ranking may shift once both are added.
- **Refactoring quality is correctness-only.** The 10% manual-quality score from
  the evaluation plan is pending review of the refactored outputs.
- **Reasoning models ran with `enable_thinking=true`** for every track. The
  evaluation plan originally called for thinking-off on Tracks 1–3. The current
  results are therefore "reasoning at its best" for those tracks, and the
  instruct-vs-reasoning comparison above uses the same setup. A companion run
  with `/no_think` or `enable_thinking=false` would let us measure the specific
  latency/quality tradeoff of the thinking mode itself.
- **Context stress needs a reasoning-aware version.** See the caveat above —
  "incoherent at all levels" for the reasoning models is a probe limitation, not
  a model limitation.
- **Noise.** Most scores come from a single pass with `temperature=0` (greedy) on
  tracks and `temperature=0.001` for reasoning models on evalplus. Bench-track
  pass-rate differences under ~3 points should be treated as noise; the bigger
  gaps (T3 variation, 70B FIM regression, codestral FIM failure) are outside
  noise and worth acting on.
