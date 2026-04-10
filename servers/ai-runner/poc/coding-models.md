# Coding Model POC — Model List

Candidate models for evaluating coding-focused AI on the ai-runner machine. All models were
selected to fit within the hardware constraint of 48GB VRAM (2x RTX 3090, NVLinked) using
INT4 quantization where required.

---

## Hardware Constraint Summary

| Spec | Value |
|------|-------|
| GPU | 2x NVIDIA RTX 3090 (NVLinked) |
| VRAM | 48GB total |
| Inference backend | vLLM, tensor parallel (TP=2) |
| Quantization | INT4/AWQ where needed (~0.5 bytes/param) |
| Max feasible model size | ~80B total params at INT4 |

For MoE models, **all expert weights** must fit in VRAM regardless of active parameter count.
Active params determine inference cost, not VRAM footprint.

### Context window affordability

After model weights load, remaining VRAM goes to the KV cache. KV cache size per token
is roughly `2 × layers × kv_heads × head_dim × 2 bytes` (BF16). The affordable context
limit is `remaining_vram / bytes_per_token`. Where this falls below the model's trained
maximum, `--max-model-len` must be capped in vLLM or generation will OOM.

| Model | KV headroom (actual) | Bytes/token (est.) | Affordable context |
|-------|----------------------|--------------------|--------------------|
| Phi-4 14B | ~41GB | ~96KB | 16k (trained max) |
| Qwen2.5-Coder-7B | ~44.5GB | ~64KB | 128k ✓ |
| DeepSeek-Coder-V2-Lite 16B | ~40GB | ~64KB | 128k ✓ |
| Codestral 25.08 22B | ~37GB | ~128KB | 256k ✓ |
| Gemma 4 26B-A4B | ~35GB | ~192KB | 128k ✓ |
| Qwen3-30B-A3B | ~33GB | ~192KB | 128k ✓ |
| Qwen2.5-Coder-32B | **~12GB** | ~256KB | **~32k (cap required)** |
| DeepSeek-R1-Distill-Qwen-32B | **~12GB** | ~256KB | **~32k (cap required)** |
| Gemma 4 31B | ~32.5GB | ~256KB | 128k ✓ |
| QwQ-32B | **~12GB** | ~256KB | **~32k (cap required)** |
| Qwen3-Coder-Next 80B | ~8GB | ~256KB | **~16k (cap required)** |
| Llama 3.3 70B | ~13GB | ~320KB | **~40k (cap required)** |
| DeepSeek-R1-Distill-Llama-70B | ~13GB | ~320KB | **~40k (cap required)** |

Phi-4's 16k limit is architectural (trained range), not VRAM. The original KV headroom
estimates for the 32B dense models assumed static weight-only allocation. In practice,
vLLM 0.19's `torch.compile` warmup and CUDA graph capture consume an additional ~20GB
of GPU memory during initialization, reducing actual KV headroom to ~12GB per GPU and
making the 131k default context OOM (`num_gpu_blocks=0`). The six highlighted models
require an explicit `--max-model-len` cap.

---

## Model List

| # | Model | HF ID | Params (Total / Active) | INT4 VRAM | License |
|---|-------|--------|------------------------|-----------|---------|
| 1 | Phi-4 | `microsoft/phi-4` | 14B dense | ~7GB | MIT |
| 2 | Qwen2.5-Coder-7B-Instruct | `Qwen/Qwen2.5-Coder-7B-Instruct` | 7B dense | ~3.5GB | Apache 2.0 |
| 3 | DeepSeek-Coder-V2-Lite-Instruct | `deepseek-ai/DeepSeek-Coder-V2-Lite-Instruct` | 16B / 2.4B active | ~8GB | Apache 2.0 |
| 4 | Codestral 25.08 | `mistralai/Codestral-25.08` | 22B dense | ~11GB | Mistral Research |
| 5 | Gemma 4 26B-A4B | `google/gemma-4-26B-A4B-it` | 26B / 3.8B active | ~13GB | Apache 2.0 |
| 6 | Qwen3-30B-A3B | `Qwen/Qwen3-30B-A3B` | 30B / 3B active | ~15GB | Apache 2.0 |
| 7 | Qwen2.5-Coder-32B-Instruct | `Qwen/Qwen2.5-Coder-32B-Instruct` | 32B dense | ~16GB | Apache 2.0 |
| 8 | DeepSeek-R1-Distill-Qwen-32B | `deepseek-ai/DeepSeek-R1-Distill-Qwen-32B` | 32B dense | ~16GB | MIT |
| 9 | Gemma 4 31B | `google/gemma-4-31B-it` | 31B dense | ~15.5GB | Apache 2.0 |
| 10 | QwQ-32B | `Qwen/QwQ-32B` | 32B dense | ~16GB | Apache 2.0 |
| 11 | Qwen3-Coder-Next | `Qwen/Qwen3-Coder-Next` | 80B / 3B active | ~40GB | Apache 2.0 |
| 12 | Llama 3.3 70B Instruct | `meta-llama/Llama-3.3-70B-Instruct` | 70B dense | ~35GB | Llama 3.3 Community |
| 13 | DeepSeek-R1-Distill-Llama-70B | `deepseek-ai/DeepSeek-R1-Distill-Llama-70B` | 70B dense | ~35GB | MIT |

---

## Model Notes

### Phi-4 (`microsoft/phi-4`)
14B dense model from Microsoft. Trained on high-quality synthetic data with a focus on
reasoning and coding. Benchmarks competitively with models 2-3x its size. Represents the
Microsoft model family — the only non-Qwen/DeepSeek/Meta/Google model in the list.

### Qwen2.5-Coder-7B-Instruct (`Qwen/Qwen2.5-Coder-7B-Instruct`)
Lightweight coding specialist. Useful as a lower bound for quality comparisons and for
tasks where latency matters more than quality. 88.4% HumanEval at 7B is unusually strong.

### DeepSeek-Coder-V2-Lite-Instruct (`deepseek-ai/DeepSeek-Coder-V2-Lite-Instruct`)
16B total / 2.4B active MoE. Tests whether a very small active parameter count is
"good enough" for coding tasks. The most inference-efficient model on the list.

### Codestral 25.08 (`mistralai/Codestral-25.08`)
Purpose-built for IDE integration. Leads all models on fill-in-the-middle (FIM) benchmarks
at 95.3% FIM pass@1 — the core primitive behind tab completion. 256K context window.
Note: Mistral Research License restricts commercial self-hosting; free for internal use.

### Gemma 4 26B-A4B (`google/gemma-4-26B-A4B-it`)
MoE variant of Gemma 4. 26B total / 3.8B active. Requires INT4 (BF16 ~52GB exceeds
budget). Comparison point for Qwen3-30B-A3B: similar architecture, different lab.
77.1% LiveCodeBench v6.

### Qwen3-30B-A3B (`Qwen/Qwen3-30B-A3B`)
MoE with thinking mode. 30B total / 3B active — near-free inference cost. Tests whether
Qwen3's architectural improvements over Qwen2.5 translate to better coding quality at
similar active parameter counts.

### Qwen2.5-Coder-32B-Instruct (`Qwen/Qwen2.5-Coder-32B-Instruct`)
The community gold standard for single-node coding. Consistently top-ranked on HumanEval,
MBPP, LiveCodeBench, and BigCodeBench for its size tier. Serves as the primary quality
baseline for this POC. ~92% HumanEval.

### DeepSeek-R1-Distill-Qwen-32B (`deepseek-ai/DeepSeek-R1-Distill-Qwen-32B`)
Reasoning-first 32B model distilled from DeepSeek-R1. Directly comparable to
Qwen2.5-Coder-32B (same size, similar base) but optimized for chain-of-thought reasoning
rather than direct coding. Tests whether reasoning-focused training helps on coding tasks.

### Gemma 4 31B (`google/gemma-4-31B-it`)
Dense flagship of the Gemma 4 family. Released April 2026, day-0 vLLM support. 94.1%
HumanEval, 80.0% LiveCodeBench v6, ~2150 Codeforces ELO. Requires INT4/AWQ (BF16 ~62GB
exceeds budget). Use `QuantTrio/gemma-4-31B-it-AWQ` for vLLM.

### Qwen3-Coder-Next (`Qwen/Qwen3-Coder-Next`)
80B total / 3B active MoE. The smaller variant of the Qwen3-Coder-480B family.
256K context window trained, but **affordable context is ~16k** given only ~8GB KV headroom
after weights. Cap `--max-model-len 16384` in vLLM to avoid OOM. The efficiency ratio
(80B total / 3B active) makes this the most interesting MoE model on the list if quality
holds — but the context ceiling is a real limitation for long agentic tasks.

### Llama 3.3 70B Instruct (`meta-llama/Llama-3.3-70B-Instruct`)
Current production model on ai-runner. Included as the real-world quality and latency
baseline. INT4 only (~35GB); BF16 would OOM. **Affordable context ~40k** despite 128k
training — only ~13GB KV headroom remains after weights. Cap `--max-model-len 40960`.

### QwQ-32B (`Qwen/QwQ-32B`)
Qwen's native reasoning model (not a distill). 32B dense, thinking always enabled —
there is no `/no_think` mode. Compared to DeepSeek-R1-Distill-Qwen-32B (same size,
same base architecture), QwQ was trained for reasoning from scratch rather than
distilled from a larger model. Key comparison: does native reasoning training produce
different agentic behavior than distillation? Fits in VRAM alongside other 32B models.
~72% SWE-bench Verified on public leaderboard.

### DeepSeek-R1-Distill-Llama-70B (`deepseek-ai/DeepSeek-R1-Distill-Llama-70B`)
Reasoning-focused 70B distill of DeepSeek-R1 on a Llama base. Highest-quality reasoning
model on the list. Paired with DeepSeek-R1-Distill-Qwen-32B to compare the reasoning
distill approach at different scales. INT4 only (~35GB). **Affordable context ~40k**
for the same reason as Llama 3.3 70B — same base architecture, same KV headroom.

---

## Selection Rationale

Models were chosen to cover several axes of comparison:

| Axis | Models |
|------|--------|
| Scale (small → large) | Qwen2.5-Coder-7B → DeepSeek-Coder-V2-Lite → Phi-4 → Codestral → ... → 70B models |
| MoE efficiency | DeepSeek-Coder-V2-Lite, Gemma 4 26B-A4B, Qwen3-30B-A3B, Qwen3-Coder-Next |
| Coding specialist vs general | Qwen2.5-Coder / Codestral / DeepSeek-Coder (specialist) vs Phi-4 / Gemma 4 / Llama (general) |
| Reasoning-first vs direct | DeepSeek-R1-Distill-* / QwQ-32B vs base instruct models |
| Reasoning approach | QwQ-32B (native) vs DeepSeek-R1-Distill-Qwen-32B (distilled) — same size/base |
| Model family diversity | Microsoft, Mistral, Google, Qwen/Alibaba, DeepSeek, Meta |
