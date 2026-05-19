# Next POC — high-capability local models for agentic Ralph

Planning doc, not yet executed. Captures the candidate set, hardware
constraints, and what we want to measure before picking a Tier-2 or
Tier-3 model to actually deploy.

## Why this POC exists

Phase 4 (see [README.md](./README.md)) made it clear that **32B-class
models on 48 GB VRAM are not the brain of a viable agentic Ralph loop**.
gemma4-31b-AWQ failed via token-duplication corruption on TS generics;
qwen2.5-coder-32b-AWQ failed via narrative-instead-of-action plus
self-feedback loops; Devstral-Small-2-24B (FP8) is the current best
local fit and follows the agent contract correctly, but its
instruction-following and code quality at ~25K Ralph context are still
visibly below Claude — the binding constraint is capability, not
infrastructure (callback, repeat-guard, jq task selection, compaction
disable, 117K context, prompt re-architecting are all in place and
working).

The question this POC answers: **what's the highest-quality local
model for agentic Ralph on this specific hardware, and how much of the
Claude gap does it close?**

## Hardware envelope

- 2× NVIDIA RTX 3090 (24 GB each → 48 GB total VRAM)
  - Compute capability 8.6 — no native FP8; FP8 quants run via the
    Marlin kernel (functional, ~10–20% throughput cost)
- 128 GB system RAM
- vLLM 0.19 in podman; LiteLLM 1.x as proxy with `fix_tool_messages.py`
  callback (Mistral ordering shim + repeat-tool-call guard; the
  Qwen-format extractor is a no-op for non-Qwen models but stays loaded)
- Goose CLI as agent host with the Ralph-specific env config in
  `.ralph/ralph.sh`

Capacity numbers from the current Devstral 24B FP8 deployment:
**117,360 tokens of GPU KV cache** at `--max-num-seqs 1`,
`--gpu-memory-utilization 0.95`, leaving the model ~12 GB of GPU memory
above its weights. Larger models will eat into that budget.

## Candidate matrix

Sorted by descending expected agentic capability. tok/s and tier
labels are estimates from public benchmarks plus our Phase 1 numbers
where applicable.

| # | Model | Quant | VRAM (model) | KV budget left | Est. tok/s | Agent-tuned? | Notes |
| - | ----- | ----- | ------------ | -------------- | ---------- | ------------ | ----- |
| 1 | DeepSeek-V3.1/V3.2 (685B-37A MoE) | IQ3_XXS / IQ2 GGUF | ~290 GB total → ~40 GB GPU + ~250 GB CPU+disk | tiny | 2–4 | yes (frontier-tier agent behavior) | llama.cpp; the only candidate that might genuinely close most of the Claude gap |
| 2 | Mistral Large 2 (123B dense) | Q5_K_M GGUF | ~85 GB total → ~45 GB GPU + ~40 GB CPU | ~3 GB | 3–6 | partial (strong tool-call training) | llama.cpp; Mistral parser format we already use |
| 3 | Qwen 2.5 72B Instruct | FP8 / Q8 | ~75 GB total → ~45 GB GPU + ~30 GB CPU | ~3 GB | 5–8 | no (general instruct) | strong general baseline; not specifically agent-trained |
| 4 | GLM-4.5-Air (106B-12A MoE) | AWQ 4-bit / Q5 | ~52 GB total → ~44 GB GPU + ~8 GB CPU offload | ~4 GB | 12–18 | **yes (purpose-built for agent loops)** | reportedly the most "Claude-like" open model for tool use; needs download (~50 GB) |
| 5 | Llama 3.3 70B Instruct | AWQ 4-bit | ~36 GB GPU | ~12 GB | 25–35 | no | fits cleanly, fastest of the 70B-class on this box; Phase 1 measured 37 tok/s; instruction following solid but not agent-trained |
| 6 | Qwen 2.5 72B Instruct | AWQ 4-bit | ~38 GB GPU | ~10 GB | 25–35 | no | already cached; strongest general 70B-class option |
| 7 | Mixtral 8x22B Instruct (141B-39A MoE) | AWQ | ~70 GB total → ~44 GB GPU + ~26 GB CPU | ~4 GB | 10–15 | partial | between Mistral Large 2 and Devstral on agent fit |
| 8 | Qwen3-Coder-30B-A3B | AWQ / FP8 | ~16–30 GB GPU | huge | 60–100 | yes (coder MoE, agent surface) | already cached; basically a faster Devstral peer, not necessarily a quality jump |
| 9 | GLM-4.6 / GLM-4.6-Air (when released) | TBD | TBD | TBD | TBD | yes | watch-list; if a smaller agent-tuned variant ships, slot in here |

**Out of scope for this POC** (already evaluated or deprioritized):

- Reasoning models (qwq-32b, deepseek-r1-distill-*) — Phase 4 caveats
  apply; their think-phase doesn't help with the Ralph failure modes
  we hit. Revisit only if a specifically agent-tuned reasoning model
  appears.
- < 30B models — Devstral 24B FP8 is the floor; smaller drops below
  the capability threshold for multi-file refactoring in TS monorepos.
- Codestral 22B — Phase 1 found 0% FIM as configured; not worth a
  Phase-4 retry without the native FIM tokens fix.

## Newer model classes worth surveying

Cross-checked the [ollama tools catalog](https://ollama.com/search?c=tools)
against Hugging Face on 2026-04-20. Parameter counts and quants below
are pulled from the actual HF model metadata — several of the names
that looked like candidates from the Ollama listing turn out to be
frontier-scale and unreachable on this hardware.

### Fits our 48 GB VRAM box (primary candidates)

- **Nemotron-Cascade-2-30B-A3B** — 30B total / 3B active MoE
  (`nemotron_h` arch), NVIDIA, tagged "reasoning, general-purpose, SFT,
  RL". Released 2026-03-18. FP8 quant ~30 GB → fits VRAM with ~18 GB
  headroom for KV cache. Strong candidate — newest NVIDIA agent MoE in
  the fits-cleanly class. HF: `nvidia/Nemotron-Cascade-2-30B-A3B`.
- **Qwen3-Coder-30B-A3B-Instruct-FP8** — 30B / 3B active MoE,
  agent-and-coder-tuned. Already evaluated in our Phase 1 cache as
  `qwen3-30b` but on a different AWQ quant; the FP8 build from Qwen
  itself is cleaner. HF: `Qwen/Qwen3-Coder-30B-A3B-Instruct-FP8`.
  Fits comfortably; good A/B control against Devstral.
- **gemma-4-26B-A4B-it** — 26B / 4B active MoE (new Gemma-4 variant,
  distinct from the gemma4-31b dense model Phase 4 already rejected
  for AWQ corruption). Released 2026-03-11. FP8 availability unclear;
  bf16 safetensors listed. If an FP8 build ships, worth a run — the
  MoE routing may avoid the AWQ-duplication failure surface that
  killed gemma4-31b-AWQ. HF: `google/gemma-4-26B-A4B-it`.
- **Qwen3-Coder-Next-FP8** — architecture `qwen3_next` (distinct from
  `qwen3_moe`), Qwen's latest coder-specific line. Released 2026-01-30.
  Exact parameter count not in the card overview; needs verification
  before deploying. We have a broken partial copy in the vLLM cache
  from Phase 1 — a clean pull against the FP8 build may work.
  HF: `Qwen/Qwen3-Coder-Next-FP8`.

### Requires CPU offload (Tier-2 candidates)

- **Nemotron-3-Super-120B-A12B-FP8** — 120B total / 12B active MoE,
  NVIDIA. Released 2026-03-10. FP8 weights ~120 GB → needs ~72 GB CPU
  offload + ~48 GB on GPU; the 12B active forward pass keeps
  decode latency reasonable (expected ~10–20 tok/s). Explicitly tagged
  for "complex multi-agent applications." Strong candidate for the
  "meaningful quality jump over Devstral, still interactive"
  tier. Also available as BF16 and NVFP4. HF:
  `nvidia/NVIDIA-Nemotron-3-Super-120B-A12B-FP8`.

### Too big for this hardware

Verified via HF metadata; keep these off the candidate list:

- **GLM-5 / GLM-5.1** (zai-org) — both show **~754B parameters** on
  the HF cards. Even at FP8 (~800 GB), not feasible on 48 GB VRAM +
  128 GB RAM. Ollama's listing of these as "tools" models is
  accurate, but the inference endpoints people use are remote
  (fireworks-ai, zai-org). Not a candidate for self-host here.
- **MiniMax-M2.7 / M2.5 / M2.1** — **229B parameters** on the HF
  card. FP8 ~230 GB → even with full CPU offload, too large for 128 GB
  system RAM. Skip.
- **Kimi-K2.6 / K2.5** — **~1.06 T parameters**. Moonshot's frontier
  scale. Not a candidate here.
- **Qwen3-Coder-480B-A35B-Instruct-FP8** — 480B / 35B active. FP8
  ~480 GB. Too big.

### Updated from earlier revision of this doc

Earlier guesses in this file had GLM-5.x and MiniMax-M2.x in the
"maybe fits with offload" tier; HF metadata shows those guesses were
wrong by an order of magnitude. Kept the entries but moved to the
"too big" list.

The earlier `LFM2 (24B)` entry was also incorrect — the LFM2 line is
currently edge-only (350M-450M VL models, no 24B build on HF).
Dropped.

### Final verified candidate list (2026-04-20)

Parameter counts and architectures confirmed against HF model cards.
All sizes are weights-only (exclude KV cache, activations, CUDA graph
memory). All candidates below are queued for download to
`/var/lib/vllm/models/hub/` on airunner01 as part of this POC setup
via `/var/log/vllm-model-pulls/pull_candidates.sh` and
`pull_offload_additions.sh`.

Organized by offload pressure rather than by vendor, because exploring
the CPU-offload regime is an explicit goal of this POC — the VRAM
ceiling alone is no longer the binding constraint, and we want data
on how aggressively we can trade throughput for model quality.

**Fits VRAM cleanly (no offload needed):**

| Model | HF ID | Params | Quant | Weights size |
| --- | --- | ---: | --- | ---: |
| Qwen3-Coder-30B-A3B-Instruct (MoE 3B active) | `Qwen/Qwen3-Coder-30B-A3B-Instruct-FP8` | 30.5 B | FP8 | ~30 GB |
| Nemotron-Cascade-2-30B-A3B (MoE 3B active) | `nvidia/Nemotron-Cascade-2-30B-A3B` | 31.6 B | BF16 → vLLM on-load FP8 | ~32 GB effective |
| Gemma-4-26B-A4B-it (MoE 4B active) | `google/gemma-4-26B-A4B-it` | 26.5 B | BF16 → vLLM on-load FP8 | ~27 GB effective |

**CPU-offload spectrum (graded pressure):**

| Model | HF ID | Params | Quant | Weights size | Offload |
| --- | --- | ---: | --- | ---: | ---: |
| GLM-4.5-Air (MoE 12B active, agent-tuned) | `zai-org/GLM-4.5-Air-FP8` | 106 B | FP8 compressed-tensors | ~54 GB | ~6 GB (light) |
| Nemotron-3-Super-120B-A12B (MoE) | `nvidia/NVIDIA-Nemotron-3-Super-120B-A12B-NVFP4` | 120 B | NVFP4 (4-bit) | ~67 GB | ~20 GB (medium) |
| Qwen3-Coder-Next (`qwen3_next` arch) | `Qwen/Qwen3-Coder-Next-FP8` | 79.7 B | FP8 | ~80 GB | ~33 GB (medium) |
| Qwen3-Next-80B-A3B-Instruct (MoE 3B active, `qwen3_next`) | `Qwen/Qwen3-Next-80B-A3B-Instruct-FP8` | 81.3 B | FP8 | ~81 GB | ~34 GB (medium) |
| Nemotron-3-Super-120B-A12B (MoE) | `nvidia/NVIDIA-Nemotron-3-Super-120B-A12B-FP8` | 123.6 B | FP8 | ~124 GB | ~76 GB (heavy) |

### Why this offload spectrum

A key axis we want to measure in this POC — and that the Devstral
baseline alone can't tell us — is **how aggressively weight offload to
system RAM degrades agentic quality vs. throughput, and at what point
the tradeoff becomes intolerable for a Ralph-style loop.** The five
offload-required candidates above hit every bucket from "light" (a few
GB spilled) through "heavy" (~76 GB in RAM, with MoE routing bringing
active-expert pages to GPU per token).

Two natural A/B comparisons fall out of this set:

1. **Nemotron-3-Super-120B-A12B FP8 vs NVFP4** — same base model, same
   architecture, two quants. Measures whether the additional 4-bit
   compression is worth the quality loss (FP8 is "pure" / vendor
   reference; NVFP4 is 2× denser and cuts offload from 76 GB to 20 GB
   — a huge latency win if quality holds).
2. **Qwen3-Coder-Next-FP8 vs Qwen3-Next-80B-A3B-Instruct-FP8** — same
   `qwen3_next` arch, nearly identical size, one coder-tuned and one
   general-instruct. Isolates whether coder-specialization helps or
   hurts on Ralph's multi-step workload compared to a broader
   general-instruct tune.

Excluded from the spectrum:

- **Mistral-Large-Instruct-2411** (123 B dense) — no official FP8, and
  dense weights mean every parameter is consumed per forward pass,
  making heavy offload much worse than MoE heavy offload. Poor fit
  for this particular experiment even though the base model would be
  a reasonable quality ceiling.
- **Nemotron-3-Nano-30B-A3B-FP8** — would be a fourth "fits VRAM" 30B
  alongside the existing three; diminishing return in this pass.

Already cached on airunner01 for baseline comparison:

| Model | HF ID | Params | Notes |
| --- | --- | ---: | --- |
| Devstral-Small-2-24B-2512 | `mistralai/Devstral-Small-2-24B-Instruct-2512` | 24 B | Currently deployed; Tier-3 baseline |
| Qwen2.5-Coder-32B-Instruct-AWQ | `Qwen/Qwen2.5-Coder-32B-Instruct-AWQ` | 32 B | Phase-4 tested; see qwen2.5-coder-32b-results.md |
| gemma-4-31B-it-AWQ (QuantTrio) | `QuantTrio/gemma-4-31B-it-AWQ` | 31 B | Phase-4 tested; AWQ duplication failure documented |

**Total new download size**: ~350 GB. Airunner01 has 1.1 TB free on
`/var/lib/vllm/models`, comfortable for this set plus the existing
327 GB cache.

### Out-of-reach frontier tier (ruled out by HF-verified parameter counts)

- **GLM-5 / GLM-5.1** (zai-org) — 754 B. Too big even with full CPU
  offload.
- **MiniMax-M2.7 / M2.5 / M2.1** (MiniMaxAI) — 229 B. FP8 ~230 GB,
  exceeds 128 GB RAM + 48 GB VRAM combined.
- **Kimi-K2.6 / K2.5** (moonshotai) — 1,058 B. Not a candidate here.
- **Qwen3-Coder-480B-A35B** (Qwen) — 480 B. Too big.
- **Mistral-Large-3-675B-Instruct-2512** (mistralai) — 675 B. Too big.
  Note: Mistral Large 2 was 123 B; Mistral Large 3 (Dec 2025) jumped
  to 675 B, so our earlier "Mistral Large 2" line item in the Tier 1
  plan is stale — there is no longer a mid-size Mistral Large option.
- **DeepSeek-V3.2 / V3.1 family** (deepseek-ai) — all ~685 B.
  Frontier-scale; inference-only via hosted endpoints.

### Corrections from earlier revisions of this doc

- GLM-5.x and MiniMax-M2.x were guessed into the "maybe fits with
  offload" tier; HF metadata shows they're 10–20× bigger than that.
  Moved to "too big".
- LFM2 "24B" was incorrect — the current LFM2 line is edge-only
  (350M–450M VL). Dropped.
- "Mistral Large 2 at Q5_K_M via llama.cpp" was an option in the
  earlier Tier-1 rec; Mistral's current Large is 675 B so that option
  no longer exists. Older `mistralai/Mistral-Large-Instruct-2411`
  (123 B) is still on the hub if we want a legacy Mistral Large; at
  Q5_K_M ~85 GB → feasible with heavy CPU offload. Not a first-wave
  candidate; noted here for completeness.

### Re-survey cadence

Agent-tuned model space is moving faster than Phase-1's evaluation
cycle. Re-check the ollama tools catalog + trending text-generation
repos on HF roughly monthly.

## What to measure (per candidate)

Same shape as the existing per-model results docs in this directory.
Three axes, in priority order:

1. **Does Ralph converge on a real story?** Run one Ralph iteration
   against US-21.1 ("Define Event Schemas") in flavor-vibe with the
   current `.ralph/` config. Outcome buckets:
   - **Converges**: Phase 1 writes failing tests, Phase 2 writes
     implementation that satisfies validator, story marked passing.
     This is the bar — only Claude passes today.
   - **Substantive partial**: tests + implementation written, validator
     finds 1–2 missing acceptance criteria after retries (current
     Devstral behavior).
   - **Loops or abandons**: hits the repeat-guard, narrates without
     acting, or blows context (current qwen/gemma behavior).

2. **Time per Ralph turn** at typical context (~25K prompt + ~10K tool
   history). Wall-clock for Phase 1 + Phase 2 + 1 validation pass.
   Useful to know how slow we'd be willing to go.

3. **Loop / format reliability**:
   - Repeat-tool-call guard fired count (any > 0 is a flag)
   - Malformed tool-call rate (count of `-32602` errors in goose log)
   - Compaction events (should be 0 with `GOOSE_AUTO_COMPACT_THRESHOLD=0`)
   - HTTP 400 from vLLM (context-overflow) count

Capture results as `<model>-results.md` in this directory, mirroring
the structure of `gemma4-31b-results.md` / `qwen2.5-coder-32b-results.md`.

## Suggested order of operations

Cheapest informative experiment first:

1. **GLM-4.5-Air, AWQ** — ~50 GB download, fits with light CPU offload,
   purpose-built for agents. If this delivers, we're done; the perf
   stays interactive (~12–18 tok/s) and the workload aligns with what
   the model was trained for.
2. **Llama 3.3 70B AWQ** (if GLM-4.5-Air falls short) — already cached,
   fastest of the candidates, drop-in test. Tells us whether dense
   70B-class general instruction following beats agent-tuned 100B-class
   MoE on this workload.
3. **Mistral Large 2, Q5_K_M GGUF via llama.cpp** — bigger commitment
   (different inference engine, ~85 GB download, slow). Run only if
   #1 and #2 leave a clear capability gap.
4. **DeepSeek-V3.x at IQ2/IQ3** — last resort. Several hours per Ralph
   turn but is the only candidate that has a real chance at "feels
   like Claude on this codebase." Only worth setting up if we've
   decided we want to keep iterating on local-only and accept overnight
   wall clock.

## What success looks like

A model that, on a fresh Ralph run against US-21.1:

- Completes both phases without compaction, without repeat-guard
  firing, without context overflow
- Writes coherent tests in Phase 1 and an implementation in Phase 2
  that the validator marks complete within ≤ 3 retries
- Total wall-clock under 30 minutes (Tier 2) or under 4 hours (Tier 1)

We do **not** need to match Claude end-to-end — closing 60–70% of the
capability gap is the realistic win, and it would meaningfully change
what local-only Ralph is good for.

## Open questions to resolve before running

- vLLM `--cpu-offload-gb` vs llama.cpp split — both are options for
  Tier 1/2 candidates. llama.cpp is more mature for big-model GPU/CPU
  split; vLLM is what our stack already uses. Pick one or stand both
  up side-by-side.
- The Qwen-format extractor in `fix_tool_messages.py` is a no-op for
  non-Qwen models but the repeat-guard is still valuable. Verify the
  guard works correctly with the GLM hermes-style format and Mistral
  Large 2 mistral-style format.
- KV cache quantization (`--kv-cache-dtype fp8`) could give us back
  ~2× effective KV cache for any candidate, at modest quality cost.
  Worth a separate small test once a candidate model is chosen.
