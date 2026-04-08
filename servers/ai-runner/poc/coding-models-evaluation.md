# Coding Model POC — Evaluation Plan

Two-phase evaluation for the 13 models in [coding-models.md](./coding-models.md).

**Phase 1** filters all 12 models quickly using a custom test suite.
**Phase 2** runs the top finalists through SWE-bench Lite for industry-standard scores.

---

## Phase 1 — Custom Test Suite

All 13 models. Goal: eliminate weak performers and identify the top 4–5 for Phase 2.

### Tracks

#### Track 1 — Code Generation

35 problems total. Automated pass/fail: run the output and verify correctness.

| Source | Language | Count | Notes |
|--------|----------|-------|-------|
| HumanEval subset | Python | 20 | Representative sample, not full suite |
| Custom problems | NodeJS | 8 | Real-world flavored (HTTP, async, data transformation) |
| Custom problems | Go | 7 | Real-world flavored (concurrency, CLI, structs) |

Scoring: **pass / fail per problem**. Final score = % passed.

---

#### Track 2 — Bug Fixing

30 problems total. Automated where output is deterministic; semi-manual for refactoring.

| Type | Languages | Count | Notes |
|------|-----------|-------|-------|
| Broken code with logic errors | Python, NodeJS, Go | 15 | Off-by-ones, wrong conditions, type errors |
| Broken code with concurrency/async bugs | NodeJS, Go | 5 | Race conditions, missing awaits |
| Refactoring (working → cleaner) | Python, NodeJS | 10 | Correctness automated; quality scored manually |

Scoring: correctness = **pass / fail**. Refactoring quality = manual 1–5 score.

---

#### Track 3 — Fill-in-the-Middle (FIM)

Tested on all 12 models. Models that do not natively support FIM tokens (`<fim_prefix>`,
`<fim_suffix>`, `<fim_middle>`) receive the equivalent prompt formatted as a standard
completion request — this produces a fair comparison of completion quality regardless of
native FIM support.

| Language | Count | Notes |
|----------|-------|-------|
| Python | 8 | Mix of trivial and multi-line logic completions |
| NodeJS | 7 | Async functions, callbacks, middleware |
| Go | 5 | Struct methods, error handling patterns |

Scoring: does the completion compile/run and produce correct output? **Pass / fail.**

---

#### Track 4 — Agentic Reliability

Reasoning-capable models only, tested with thinking **enabled**. Goal: measure whether
thinking mode reduces agentic looping compared to instruct models on the same tasks.

10 multi-step tasks submitted via Goose (same setup used in production). Each task
requires at least 3 distinct tool calls to complete. Tasks are chosen to have a clear
done condition so loop detection is unambiguous.

| Metric | Method |
|--------|--------|
| Completion rate | Did the model finish the task without user intervention? (pass/fail) |
| Tool call efficiency | Total tool calls made vs minimum required (lower = better) |
| Loop rate | % of runs where the same tool+args was called 3+ times consecutively |
| Thinking token overhead | Thinking tokens generated per task (latency cost of reasoning) |

Scoring: **completion rate** (primary) + tool call efficiency (secondary). Loop rate
is reported but not weighted — it's a diagnostic metric.

Non-reasoning instruct models (Devstral, Qwen2.5-Coder-32B, Llama 3.3 70B) run the
same 10 tasks as a baseline for comparison.

---

### Performance Metrics

Captured for every model during Phase 1 testing.

| Metric | Method |
|--------|--------|
| Throughput (tokens/sec) | vLLM `/metrics` endpoint |
| Time to first token (TTFT) | Measured from request submission to first streamed token |
| VRAM at load | `nvidia-smi` after model loads, before first request |
| Max stable context | Test at 4K, 8K, 16K, 32K — record where generation degrades or OOMs |

---

### Reasoning Model Configuration

Models with thinking/chain-of-thought capabilities: `DeepSeek-R1-Distill-Qwen-32B`,
`DeepSeek-R1-Distill-Llama-70B`, `QwQ-32B`, `Qwen3-30B-A3B`, `Qwen3-Coder-Next`.

These models are tested in **both modes**:

**Thinking disabled** — for Tracks 1–3 (code generation, bug fixing, FIM). Direct
completions are faster and more appropriate for single-turn coding tasks. Disable via
`/no_think` prefix or system prompt:
```
User: /no_think Write a Go function that...
```
```
System: Respond directly. Do not output thinking or reasoning steps.
```

**Thinking enabled** — for Track 4 (agentic reliability) only. The internal reasoning
trace is the mechanism being evaluated; disabling it defeats the purpose of the test.
vLLM strips thinking tokens before returning output via `--reasoning-parser deepseek_r1`
(R1 distills) or `--reasoning-parser qwen3` (Qwen3 models). Goose and OpenHands never
see the raw thinking output.

The split lets us answer: does thinking mode help with agentic loop prevention, even
if it adds latency on single-turn tasks?

---

### Phase 1 Scoring Matrix

| Track | Weight | Scoring Method |
|-------|--------|----------------|
| Code generation pass rate | 30% | Automated |
| Bug fixing accuracy | 25% | Automated + semi-manual |
| FIM pass rate | 15% | Automated |
| Throughput (tokens/sec) | 15% | Automated |
| Refactoring quality | 10% | Manual (1–5 per task, normalized) |
| Agentic reliability | 5% | Automated (reasoning models only; instruct models use baseline completion rate) |

Models are ranked by weighted total. Top 4–5 advance to Phase 2.

---

### Test Harness

A Python script submits all prompts via the LiteLLM API (`192.168.4.56:8000`), runs
returned code in a subprocess sandbox, and records pass/fail per task. One model is
loaded at a time; the harness handles model switching between runs.

```
harness.py
  ├── prompts/
  │   ├── track1_codegen/      # .json files: prompt + expected output
  │   ├── track2_bugfix/       # .json files: broken code + correct output
  │   └── track3_fim/          # .json files: prefix, suffix, expected middle behavior
  ├── runner.py                # submits prompts, captures outputs
  ├── scorer.py                # runs code, compares outputs, records pass/fail
  └── results/                 # per-model result files
```

Each prompt file format:
```json
{
  "id": "codegen_py_001",
  "track": "codegen",
  "language": "python",
  "prompt": "...",
  "test_cases": [
    { "input": "...", "expected_output": "..." }
  ]
}
```

---

## Phase 2 — SWE-bench Lite

Top 4–5 models from Phase 1. Industry-standard, directly comparable scores.

### What it tests

Given a real GitHub repository at a specific commit and an issue description, the model
must produce a patch that makes the repo's existing test suite pass. Tests the full
software engineering loop: understanding context, navigating a codebase, writing a fix.

### Setup

| Component | Details |
|-----------|---------|
| Benchmark | SWE-bench Lite (300 tasks, Python repos) |
| Agent scaffold | OpenHands (most widely used; scores are comparable to leaderboard) |
| Isolation | Docker — each task runs in a sandboxed repo environment |
| Storage budget | ~50–100GB working space for Docker images and repo environments |

SWE-bench is Python-only. Phase 1 covers NodeJS and Go; Phase 2 covers Python depth.

### Time estimate

Each task takes roughly 2–10 minutes depending on model speed and agent steps. For
300 tasks × 5 models, budget several days of continuous compute. Run overnight batches.

### Scoring

Pass rate = % of tasks where the model's patch makes all tests pass. This is the same
metric used on the public leaderboard — results are directly comparable to published scores.

### OpenHands setup

```sh
# Install OpenHands
pip install openhands-ai

# Run SWE-bench evaluation
python -m openhands.runtime.utils.swe_bench \
  --model-name litellm/<model-id> \
  --base-url http://192.168.4.56:8000 \
  --split lite \
  --output-dir ./results/phase2/<model-id>
```

---

## Expected Outputs

### Phase 1 output

A ranked table of all 12 models:

| Rank | Model | Codegen % | Bugfix % | FIM % | Tokens/sec | Weighted Score |
|------|-------|-----------|----------|-------|------------|----------------|
| 1 | ... | | | | | |
| ... | | | | | | |

### Phase 2 output

SWE-bench Lite pass rate for finalists, alongside known published scores for context:

| Model | Phase 2 Pass Rate | Published SWE-bench Verified | Delta |
|-------|------------------|------------------------------|-------|
| ... | | | |

The delta column flags where local results diverge from published scores (different
scaffold, quantization, or context length limits are common causes).

---

## Decision Criteria

After both phases, the goal is to answer:

| Question | How it's answered |
|----------|------------------|
| Best overall replacement for Llama 3.3 70B? | Highest weighted Phase 1 score + Phase 2 pass rate |
| Best coding specialist to add alongside production model? | Track 1+2 scores at fastest tokens/sec |
| Is MoE efficiency good enough? | Compare Qwen3-30B-A3B / Gemma 4 26B vs dense models of similar quality |
| Do R1 reasoning distills help for coding? | R1 distills vs base instruct at same size (32B and 70B pairs) |
| Does thinking mode reduce agentic loops? | Track 4 completion rate + loop rate: reasoning models (thinking on) vs instruct baseline |
| Is a dedicated FIM model worth it? | Codestral Track 3 score vs everything else |
