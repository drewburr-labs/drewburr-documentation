#!/usr/bin/env python3
"""
benchmark.py — Phase 1 coding model evaluation harness for ai-runner

Implements the automated tracks from coding-models-evaluation.md:
    Track 1: Code generation     (Python / NodeJS / Go, 20 problems)
    Track 2: Bug fixing          (Python / NodeJS / Go, 15 problems)
    Track 3: Fill-in-the-middle  (Python / NodeJS / Go, 12 problems)
    Perf:    TTFT, throughput, VRAM at load, context stress

Usage (from your local machine, pointing at ai-runner):
    python3 benchmark.py <model_key> --api-url http://192.168.4.56:8001
    python3 benchmark.py qwen2.5-coder-32b --api-url http://192.168.4.56:8001 --evalplus
    python3 benchmark.py llama3.3-70b --api-url http://192.168.4.56:8001 --tracks perf,track1

    Manage vLLM on ai-runner separately; this script is a pure benchmarking client.
    Use --no-start / --no-stop (both default True when --api-url is non-local)
    to skip container lifecycle if vLLM is already running.

Model keys:
    phi-4  qwen2.5-coder-7b  deepseek-coder-v2-lite  codestral-22b
    gemma4-26b  qwen3-30b  qwen2.5-coder-32b  deepseek-r1-qwen-32b
    gemma4-31b  qwq-32b  qwen3-coder-80b  llama3.3-70b  deepseek-r1-llama-70b

Output:
    results/<model_key>.json
"""

import argparse
import concurrent.futures
import http.client
import json
import os
import re
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone

# ── Constants ──────────────────────────────────────────────────────────────────

VLLM_IMAGE      = "docker.io/vllm/vllm-openai:latest"
DEFAULT_API_URL = "http://192.168.4.56:8001"  # vLLM direct port on ai-runner
CONTAINER       = "vllm-bench"
MODEL_CACHE     = "/var/lib/vllm/models"
RESULTS_DIR     = os.path.join(os.path.dirname(os.path.abspath(__file__)), "results")
STARTUP_WAIT         = 300   # seconds to wait when model is already cached (remote / --no-start)
DOWNLOAD_WAIT        = 7200  # seconds to wait when starting locally (download + load; ~2h ceiling)
CODE_TIMEOUT         = 15    # seconds to execute generated code in subprocess
LLM_TIMEOUT          = 90    # socket idle timeout for inference requests
PER_PROBLEM_TIMEOUT  = 180   # wall-clock cap per benchmark problem
CONTEXT_TEST_TIMEOUT = 240   # wall-clock cap per context stress level
EVALPLUS_N           = 5     # samples per problem for pass@1 estimation
EVALPLUS_TEMP        = 0.2   # temperature for evalplus sampling

PROD_SERVICES = ["vllm-1", "litellm"]  # stopped before bench, optionally restarted

# ── Model configs ──────────────────────────────────────────────────────────────
# hf_id:            HuggingFace repo passed to vLLM --model
# quantization:     vLLM --quantization value, or None for BF16/FP16
# max_model_len:    vLLM --max-model-len cap, or None (use model default)
# reasoning_parser: vLLM --reasoning-parser value for models with thinking tokens
# is_reasoning:     True = model has chain-of-thought / thinking mode (metadata only)
# fim_tokens:       Native FIM token set, or None (falls back to chat prompt)

MODEL_CONFIGS: dict[str, dict] = {
    "phi-4": {
        "hf_id": "microsoft/phi-4",
        "quantization": None,
        "max_model_len": None,
        "reasoning_parser": None,
        "is_reasoning": False,
        "fim_tokens": None,
    },
    "qwen2.5-coder-7b": {
        "hf_id": "Qwen/Qwen2.5-Coder-7B-Instruct",
        "quantization": None,
        "max_model_len": None,
        "reasoning_parser": None,
        "is_reasoning": False,
        "fim_tokens": {
            "prefix": "<|fim_prefix|>",
            "suffix": "<|fim_suffix|>",
            "middle": "<|fim_middle|>",
        },
    },
    "deepseek-coder-v2-lite": {
        "hf_id": "deepseek-ai/DeepSeek-Coder-V2-Lite-Instruct",
        "quantization": None,
        "max_model_len": None,
        "reasoning_parser": None,
        "is_reasoning": False,
        "fim_tokens": {
            "prefix": "<｜fim▁begin｜>",   # before prefix code
            "suffix": "<｜fim▁hole｜>",    # between prefix and suffix code (fill position)
            "middle": "<｜fim▁end｜>",     # after suffix code (end of context)
        },
    },
    "codestral-22b": {
        # Codestral-25.08 (mistralai/Codestral-25.08) is enterprise-gated with no public AWQ.
        # Using Codestral-22B-v0.1 AWQ as the nearest public equivalent.
        "hf_id": "solidrust/Codestral-22B-v0.1-hf-AWQ",
        "quantization": "awq_marlin",
        "max_model_len": None,
        "reasoning_parser": None,
        "is_reasoning": False,
        # solidrust AWQ omits the chat template; supply Mistral v1 template explicitly.
        # Stripped of raise_exception guards — benchmark only needs correct formatting.
        "chat_template": (
            "{{ bos_token }}"
            "{% for message in messages %}"
            "{% if message['role'] == 'user' %}{{ '[INST] ' + message['content'] + ' [/INST]' }}"
            "{% elif message['role'] == 'assistant' %}{{ message['content'] + eos_token + ' ' }}"
            "{% endif %}"
            "{% endfor %}"
        ),
        # Mistral FIM format used by Codestral (same across v0.1 and 25.x)
        "fim_tokens": {
            "prefix": "[PREFIX]",
            "suffix": "[SUFFIX]",
            "middle": "[MIDDLE]",
        },
    },
    "gemma4-26b": {
        # bitsandbytes blocked for MoE: Gemma4ForConditionalGeneration missing get_expert_mapping().
        # v0.19.0 doesn't help — it ships an older Transformers that doesn't recognise gemma4 arch.
        # gemma4 image required for Transformers compat; AWQ required to avoid MoE+bnb block.
        # cyankiwi model config.json declares compressed-tensors (llm-compressor format, not awq)
        # despite the repo name — set quantization=None so vLLM reads it from config.json directly.
        # 8-bit weights ≈ 26 GB; fits in 2× RTX 3090 with ~22 GB left for KV cache.
        "hf_id": "cyankiwi/gemma-4-26B-A4B-it-AWQ-8bit",
        "quantization": None,
        "max_model_len": 32768,
        "reasoning_parser": None,
        "is_reasoning": False,
        "fim_tokens": None,
        "image": "docker.io/vllm/vllm-openai:gemma4",
    },
    "qwen3-30b": {
        "hf_id": "QuixiAI/Qwen3-30B-A3B-AWQ",  # community AWQ (ModelScope swift); no official Qwen AWQ exists yet
        "quantization": "awq_marlin",
        "max_model_len": 32768,  # 14 GB KV headroom; 131k default yields only 64 blocks (1024 tok pool)
        "reasoning_parser": "qwen3",
        "is_reasoning": True,
        "fim_tokens": None,
    },
    "qwen2.5-coder-32b": {
        "hf_id": "Qwen/Qwen2.5-Coder-32B-Instruct-AWQ",  # official Qwen AWQ
        "quantization": "awq_marlin",
        "max_model_len": 32768,  # torch.compile overhead leaves ~12GB KV headroom; 131K default OOMs
        "reasoning_parser": None,
        "is_reasoning": False,
        "fim_tokens": {
            "prefix": "<|fim_prefix|>",
            "suffix": "<|fim_suffix|>",
            "middle": "<|fim_middle|>",
        },
    },
    "deepseek-r1-qwen-32b": {
        "hf_id": "casperhansen/deepseek-r1-distill-qwen-32b-awq",  # community AWQ, 13k dl/mo, MIT
        "quantization": "awq_marlin",
        "max_model_len": 32768,  # same KV headroom constraint as qwen2.5-coder-32b
        "reasoning_parser": "deepseek_r1",
        "is_reasoning": True,
        "fim_tokens": None,
    },
    "gemma4-31b": {
        "hf_id": "QuantTrio/gemma-4-31B-it-AWQ",  # community AWQ quant
        "quantization": "awq_marlin",
        "max_model_len": 32768,  # same torch.compile KV headroom constraint as 32B models
        "reasoning_parser": None,
        "is_reasoning": False,
        "fim_tokens": None,
        "image": "docker.io/vllm/vllm-openai:gemma4",  # gemma4 image required for Transformers compat
    },
    "qwq-32b": {
        "hf_id": "Qwen/QwQ-32B-AWQ",  # official Qwen AWQ
        "quantization": "awq_marlin",
        "max_model_len": 32768,  # same KV headroom constraint as qwen2.5-coder-32b
        "reasoning_parser": "qwen3",  # QwQ uses Qwen3-compatible thinking tokens
        "is_reasoning": True,
        "fim_tokens": None,
    },
    "qwen3-coder-80b": {
        "hf_id": "bullpoint/Qwen3-Coder-Next-AWQ-4bit",  # community AWQ, 135k dl/mo, Apache 2.0
        "quantization": "awq_marlin",
        "max_model_len": 16384,  # only ~8 GB KV headroom after weights
        "reasoning_parser": "qwen3",
        "is_reasoning": True,
        "fim_tokens": None,
    },
    "llama3.3-70b": {
        "hf_id": "casperhansen/llama-3.3-70b-instruct-awq",
        "quantization": "awq_marlin",
        "max_model_len": 8192,  # torch.compile leaves only ~2.65 GB KV headroom; 40960 OOMs
        "reasoning_parser": None,
        "is_reasoning": False,
        "fim_tokens": None,
    },
    "deepseek-r1-llama-70b": {
        "hf_id": "casperhansen/deepseek-r1-distill-llama-70b-awq",  # community AWQ, 10k dl/mo, MIT
        "quantization": "awq_marlin",
        "max_model_len": 8192,  # same ~2.65 GB KV headroom as llama3.3-70b
        "reasoning_parser": "deepseek_r1",
        "is_reasoning": True,
        "fim_tokens": None,
    },
}

# ── Test problems ──────────────────────────────────────────────────────────────
# Each problem:
#   id, prompt, language, test_cases: [{call, expected}]
# expected is a valid Python literal — compared with == against the call result.

TRACK1_PYTHON = [
    {
        "id": "py_sum_to_n",
        "prompt": "Write a Python function `sum_to_n(n: int) -> int` that returns the sum of all integers from 1 to n inclusive. Handle n=0.",
        "test_cases": [
            {"call": "sum_to_n(5)", "expected": "15"},
            {"call": "sum_to_n(0)", "expected": "0"},
            {"call": "sum_to_n(100)", "expected": "5050"},
        ],
    },
    {
        "id": "py_count_vowels",
        "prompt": "Write a Python function `count_vowels(s: str) -> int` that counts vowels (a e i o u, case-insensitive).",
        "test_cases": [
            {"call": "count_vowels('hello')", "expected": "2"},
            {"call": "count_vowels('rhythm')", "expected": "0"},
            {"call": "count_vowels('AEIOUaeiou')", "expected": "10"},
        ],
    },
    {
        "id": "py_is_palindrome",
        "prompt": "Write a Python function `is_palindrome(s: str) -> bool` that returns True if s is a palindrome, ignoring case and non-alphanumeric characters.",
        "test_cases": [
            {"call": "is_palindrome('racecar')", "expected": "True"},
            {"call": "is_palindrome('hello')", "expected": "False"},
            {
                "call": "is_palindrome('A man a plan a canal Panama')",
                "expected": "True",
            },
        ],
    },
    {
        "id": "py_flatten_once",
        "prompt": "Write a Python function `flatten_once(lst: list) -> list` that flattens exactly one level of nesting. [[1,2],[3,[4,5]]] -> [1,2,3,[4,5]].",
        "test_cases": [
            {"call": "flatten_once([[1,2],[3,4]])", "expected": "[1, 2, 3, 4]"},
            {"call": "flatten_once([[1,[2]],[3]])", "expected": "[1, [2], 3]"},
            {"call": "flatten_once([])", "expected": "[]"},
        ],
    },
    {
        "id": "py_running_sum",
        "prompt": "Write a Python function `running_sum(nums: list) -> list` that returns the cumulative (running) sum. [1,2,3] -> [1,3,6].",
        "test_cases": [
            {"call": "running_sum([1,2,3,4])", "expected": "[1, 3, 6, 10]"},
            {"call": "running_sum([5])", "expected": "[5]"},
            {"call": "running_sum([])", "expected": "[]"},
        ],
    },
    {
        "id": "py_unique",
        "prompt": "Write a Python function `unique(lst: list) -> list` that removes duplicates while preserving the order of first appearances.",
        "test_cases": [
            {"call": "unique([3,1,2,1,3])", "expected": "[3, 1, 2]"},
            {"call": "unique([])", "expected": "[]"},
            {"call": "unique([1,1,1])", "expected": "[1]"},
        ],
    },
    {
        "id": "py_fizzbuzz",
        "prompt": "Write a Python function `fizzbuzz(n: int) -> str` returning 'FizzBuzz' if divisible by 3 and 5, 'Fizz' if by 3, 'Buzz' if by 5, else str(n).",
        "test_cases": [
            {"call": "fizzbuzz(15)", "expected": "'FizzBuzz'"},
            {"call": "fizzbuzz(9)", "expected": "'Fizz'"},
            {"call": "fizzbuzz(10)", "expected": "'Buzz'"},
            {"call": "fizzbuzz(7)", "expected": "'7'"},
        ],
    },
    {
        "id": "py_rotate",
        "prompt": "Write a Python function `rotate(lst: list, k: int) -> list` that rotates the list right by k positions. rotate([1,2,3,4,5], 2) -> [4,5,1,2,3].",
        "test_cases": [
            {"call": "rotate([1,2,3,4,5], 2)", "expected": "[4, 5, 1, 2, 3]"},
            {"call": "rotate([1,2,3], 0)", "expected": "[1, 2, 3]"},
            {"call": "rotate([1,2,3], 3)", "expected": "[1, 2, 3]"},
        ],
    },
    {
        "id": "py_group_by_length",
        "prompt": "Write a Python function `group_by_length(words: list) -> dict` that groups words by their length. Keys are lengths, values are lists of words in original order.",
        "test_cases": [
            {
                "call": "group_by_length(['cat','dog','ox'])",
                "expected": "{3: ['cat', 'dog'], 2: ['ox']}",
            },
            {"call": "group_by_length([])", "expected": "{}"},
            {
                "call": "group_by_length(['a','b','cc'])",
                "expected": "{1: ['a', 'b'], 2: ['cc']}",
            },
        ],
    },
    {
        "id": "py_is_balanced",
        "prompt": "Write a Python function `is_balanced(s: str) -> bool` that checks whether parentheses, brackets, and braces are balanced. Only count (), [], {}.",
        "test_cases": [
            {"call": "is_balanced('([{}])')", "expected": "True"},
            {"call": "is_balanced('([)]')", "expected": "False"},
            {"call": "is_balanced('')", "expected": "True"},
            {"call": "is_balanced('(((')", "expected": "False"},
        ],
    },
    {
        "id": "py_two_sum",
        "prompt": "Write a Python function `two_sum(nums: list, target: int) -> list` that returns the indices [i, j] of the two numbers that add up to target. Assume exactly one solution exists and i < j.",
        "test_cases": [
            {"call": "two_sum([2,7,11,15], 9)", "expected": "[0, 1]"},
            {"call": "two_sum([3,2,4], 6)", "expected": "[1, 2]"},
            {"call": "two_sum([3,3], 6)", "expected": "[0, 1]"},
        ],
    },
    {
        "id": "py_merge_dicts",
        "prompt": "Write a Python function `merge_dicts(a: dict, b: dict) -> dict` that returns a new dict with all keys from both. If a key appears in both, the value from b wins. Do not modify either input.",
        "test_cases": [
            {"call": "merge_dicts({'a':1,'b':2}, {'b':3,'c':4})", "expected": "{'a': 1, 'b': 3, 'c': 4}"},
            {"call": "merge_dicts({}, {'x':1})", "expected": "{'x': 1}"},
            {"call": "merge_dicts({'a':1}, {})", "expected": "{'a': 1}"},
        ],
    },
    {
        "id": "py_chunk",
        "prompt": "Write a Python function `chunk(lst: list, n: int) -> list` that splits lst into consecutive chunks of size n. The last chunk may be smaller.",
        "test_cases": [
            {"call": "chunk([1,2,3,4,5], 2)", "expected": "[[1, 2], [3, 4], [5]]"},
            {"call": "chunk([1,2,3], 3)", "expected": "[[1, 2, 3]]"},
            {"call": "chunk([], 2)", "expected": "[]"},
        ],
    },
    {
        "id": "py_most_common",
        "prompt": "Write a Python function `most_common(lst: list)` that returns the most frequently occurring element. If there is a tie, return any one of the tied elements.",
        "test_cases": [
            {"call": "most_common([1,2,2,3,3,3])", "expected": "3"},
            {"call": "most_common(['a','b','a'])", "expected": "'a'"},
            {"call": "most_common([42])", "expected": "42"},
        ],
    },
    {
        "id": "py_deep_flatten",
        "prompt": "Write a Python function `deep_flatten(lst: list) -> list` that recursively flattens a nested list to a single flat list.",
        "test_cases": [
            {"call": "deep_flatten([1,[2,[3,[4]]],5])", "expected": "[1, 2, 3, 4, 5]"},
            {"call": "deep_flatten([1,2,3])", "expected": "[1, 2, 3]"},
            {"call": "deep_flatten([])", "expected": "[]"},
        ],
    },
    {
        "id": "py_zip_to_dict",
        "prompt": "Write a Python function `zip_to_dict(keys: list, values: list) -> dict` that pairs each key with its corresponding value. Stop at the shorter list if lengths differ.",
        "test_cases": [
            {"call": "zip_to_dict(['a','b','c'], [1,2,3])", "expected": "{'a': 1, 'b': 2, 'c': 3}"},
            {"call": "zip_to_dict(['a','b'], [1,2,3])", "expected": "{'a': 1, 'b': 2}"},
            {"call": "zip_to_dict([], [])", "expected": "{}"},
        ],
    },
    {
        "id": "py_clamp",
        "prompt": "Write a Python function `clamp(value, lo, hi)` that returns value clamped to the range [lo, hi].",
        "test_cases": [
            {"call": "clamp(5, 1, 10)", "expected": "5"},
            {"call": "clamp(-3, 0, 100)", "expected": "0"},
            {"call": "clamp(200, 0, 100)", "expected": "100"},
        ],
    },
    {
        "id": "py_caesar",
        "prompt": "Write a Python function `caesar(text: str, shift: int) -> str` that applies a Caesar cipher to all alphabetic characters, wrapping correctly at z/Z. Non-alpha characters pass through unchanged.",
        "test_cases": [
            {"call": "caesar('Hello, World!', 3)", "expected": "'Khoor, Zruog!'"},
            {"call": "caesar('xyz', 3)", "expected": "'abc'"},
            {"call": "caesar('ABC', 1)", "expected": "'BCD'"},
        ],
    },
    {
        "id": "py_word_count",
        "prompt": "Write a Python function `word_count(text: str) -> dict` that returns a dict mapping each lowercased word (split on whitespace) to its count.",
        "test_cases": [
            {"call": "word_count('the cat sat on the mat')", "expected": "{'the': 2, 'cat': 1, 'sat': 1, 'on': 1, 'mat': 1}"},
            {"call": "word_count('')", "expected": "{}"},
            {"call": "word_count('one one ONE')", "expected": "{'one': 3}"},
        ],
    },
    {
        "id": "py_transpose",
        "prompt": "Write a Python function `transpose(matrix: list) -> list` that returns the transpose of a 2D list. Assume all rows have equal length.",
        "test_cases": [
            {"call": "transpose([[1,2,3],[4,5,6]])", "expected": "[[1, 4], [2, 5], [3, 6]]"},
            {"call": "transpose([[1,2],[3,4],[5,6]])", "expected": "[[1, 3, 5], [2, 4, 6]]"},
            {"call": "transpose([[1]])", "expected": "[[1]]"},
        ],
    },
]

TRACK1_NODEJS = [
    {
        "id": "js_chunk",
        "prompt": "Write a JavaScript function `chunkArray(arr, size)` that splits an array into chunks of the given size. The last chunk may be smaller.",
        "test_js": r"""
const tests = [
  [[[1,2,3,4,5], 2],  [[1,2],[3,4],[5]]],
  [[[], 3],           []],
  [[[1,2,3], 3],      [[1,2,3]]],
];
let ok = 0;
for (const [args, exp] of tests) {
  const got = chunkArray(...args);
  if (JSON.stringify(got) === JSON.stringify(exp)) { console.log('PASS'); ok++; }
  else console.log(`FAIL: got ${JSON.stringify(got)} expected ${JSON.stringify(exp)}`);
}
""",
        "n_tests": 3,
    },
    {
        "id": "js_groupby",
        "prompt": "Write a JavaScript function `groupByKey(arr, key)` that groups an array of objects by the value of a given key. Returns an object where each key maps to an array of matching objects.",
        "test_js": r"""
const items = [{t:'a',v:1},{t:'b',v:2},{t:'a',v:3}];
const got = groupByKey(items, 't');
const pass = JSON.stringify(got['a']) === JSON.stringify([{t:'a',v:1},{t:'a',v:3}])
          && JSON.stringify(got['b']) === JSON.stringify([{t:'b',v:2}]);
console.log(pass ? 'PASS' : 'FAIL: ' + JSON.stringify(got));
const got2 = groupByKey([], 'x');
console.log(JSON.stringify(got2) === '{}' ? 'PASS' : 'FAIL empty');
""",
        "n_tests": 2,
    },
    {
        "id": "js_flatten",
        "prompt": "Write a JavaScript function `deepFlatten(arr)` that recursively flattens a nested array to a single level.",
        "test_js": r"""
const tests = [
  [[1,[2,[3,[4]]],5],  [1,2,3,4,5]],
  [[],                 []],
  [[[1,2],[3]],        [1,2,3]],
];
let ok = 0;
for (const [input, exp] of tests) {
  const got = deepFlatten(input);
  if (JSON.stringify(got) === JSON.stringify(exp)) { console.log('PASS'); ok++; }
  else console.log(`FAIL: got ${JSON.stringify(got)} expected ${JSON.stringify(exp)}`);
}
""",
        "n_tests": 3,
    },
    {
        "id": "js_compact",
        "prompt": "Write a JavaScript function `compact(arr)` that removes all falsy values (false, null, 0, '', undefined, NaN) from an array.",
        "test_js": r"""
const tests = [
  [[0,1,false,2,'',3],  [1,2,3]],
  [[null,undefined,NaN],[],],
  [[1,'a',true],        [1,'a',true]],
];
let ok = 0;
for (const [input, exp] of tests) {
  const got = compact(input);
  if (JSON.stringify(got) === JSON.stringify(exp)) { console.log('PASS'); ok++; }
  else console.log(`FAIL: got ${JSON.stringify(got)} exp ${JSON.stringify(exp)}`);
}
""",
        "n_tests": 3,
    },
    {
        "id": "js_parse_qs",
        "prompt": "Write a JavaScript function `parseQueryString(qs)` that parses a query string (without the leading ?) into a plain object. Example: 'a=1&b=hello' -> {a:'1', b:'hello'}. Keys with no value map to ''.",
        "test_js": r"""
const t1 = parseQueryString('a=1&b=hello');
console.log(t1.a === '1' && t1.b === 'hello' ? 'PASS' : 'FAIL t1: ' + JSON.stringify(t1));
const t2 = parseQueryString('');
console.log(JSON.stringify(t2) === '{}' ? 'PASS' : 'FAIL t2: ' + JSON.stringify(t2));
const t3 = parseQueryString('x=foo%20bar');
console.log(t3.x === 'foo bar' ? 'PASS' : 'FAIL t3: ' + JSON.stringify(t3));
""",
        "n_tests": 3,
    },
    {
        "id": "js_deep_clone",
        "prompt": "Write a JavaScript function `deepClone(obj)` that returns a deep clone of a plain JSON-serialisable object or array. Modifying the clone must not affect the original.",
        "test_js": r"""
const orig = {a: 1, b: {c: 2, d: [3, 4]}};
const clone = deepClone(orig);
clone.b.c = 99;
clone.b.d.push(5);
console.log(orig.b.c === 2 ? 'PASS' : 'FAIL: orig.b.c mutated to ' + orig.b.c);
console.log(orig.b.d.length === 2 ? 'PASS' : 'FAIL: orig.b.d mutated to ' + JSON.stringify(orig.b.d));
const arr = deepClone([1,[2,3],4]);
arr[1].push(99);
console.log(JSON.stringify([1,[2,3],4]) === '[1,[2,3],4]' ? 'PASS' : 'FAIL: source array mutated');
""",
        "n_tests": 3,
    },
    {
        "id": "js_sum_nested",
        "prompt": "Write a JavaScript function `sumValues(obj)` that sums all numeric values in a plain object (one level deep). Non-numeric values are ignored.",
        "test_js": r"""
console.log(sumValues({a:1, b:2, c:3}) === 6 ? 'PASS' : 'FAIL basic: ' + sumValues({a:1,b:2,c:3}));
console.log(sumValues({x:10, y:'hello', z:5}) === 15 ? 'PASS' : 'FAIL mixed: ' + sumValues({x:10,y:'hello',z:5}));
console.log(sumValues({}) === 0 ? 'PASS' : 'FAIL empty: ' + sumValues({}));
""",
        "n_tests": 3,
    },
    {
        "id": "js_truncate",
        "prompt": "Write a JavaScript function `truncate(str, maxLen)` that returns the string truncated to maxLen characters with '...' appended if it exceeds maxLen. Return the string unchanged if it fits.",
        "test_js": r"""
console.log(truncate('Hello, World!', 5) === 'Hello...' ? 'PASS' : 'FAIL long: ' + truncate('Hello, World!', 5));
console.log(truncate('Hi', 10) === 'Hi' ? 'PASS' : 'FAIL short: ' + truncate('Hi', 10));
console.log(truncate('exact', 5) === 'exact' ? 'PASS' : 'FAIL exact: ' + truncate('exact', 5));
""",
        "n_tests": 3,
    },
]

TRACK1_GO = [
    {
        "id": "go_reverse_string",
        "prompt": "Write a Go function `ReverseString(s string) string` that reverses a UTF-8 string by rune.",
        "func_name": "ReverseString",
        "imports": [],
        "test_main": r"""
    tests := []struct{ in, want string }{
        {"hello", "olleh"},
        {"", ""},
        {"ab", "ba"},
        {"café", "éfac"},
    }
    for _, tt := range tests {
        got := ReverseString(tt.in)
        if got == tt.want {
            fmt.Println("PASS")
        } else {
            fmt.Printf("FAIL: got %q want %q\n", got, tt.want)
        }
    }
""",
        "n_tests": 4,
    },
    {
        "id": "go_word_frequency",
        "prompt": "Write a Go function `WordFrequency(s string) map[string]int` that returns a count of each word (split on whitespace, case-insensitive).",
        "func_name": "WordFrequency",
        "imports": ["strings"],
        "test_main": r"""
    freq := WordFrequency("the cat sat on the mat the cat")
    if freq["the"] == 3 && freq["cat"] == 2 && freq["sat"] == 1 {
        fmt.Println("PASS")
    } else {
        fmt.Printf("FAIL: %v\n", freq)
    }
    empty := WordFrequency("")
    if len(empty) == 0 {
        fmt.Println("PASS")
    } else {
        fmt.Printf("FAIL empty: %v\n", empty)
    }
""",
        "n_tests": 2,
    },
    {
        "id": "go_is_palindrome",
        "prompt": "Write a Go function `IsPalindrome(s string) bool` that returns true if s is a palindrome ignoring case and non-alphanumeric characters.",
        "func_name": "IsPalindrome",
        "imports": ["strings", "unicode"],
        "test_main": r"""
    if IsPalindrome("racecar") { fmt.Println("PASS") } else { fmt.Println("FAIL racecar") }
    if !IsPalindrome("hello")  { fmt.Println("PASS") } else { fmt.Println("FAIL hello") }
    if IsPalindrome("A man a plan a canal Panama") { fmt.Println("PASS") } else { fmt.Println("FAIL panama") }
""",
        "n_tests": 3,
    },
    {
        "id": "go_max_slice",
        "prompt": "Write a Go function `MaxSlice(nums []int) (int, bool)` that returns the maximum value and true. Returns (0, false) for an empty slice.",
        "func_name": "MaxSlice",
        "imports": [],
        "test_main": r"""
    if v, ok := MaxSlice([]int{3,1,4,1,5,9,2,6}); ok && v == 9 {
        fmt.Println("PASS")
    } else {
        fmt.Printf("FAIL: got %d %v\n", v, ok)
    }
    if _, ok := MaxSlice([]int{}); !ok {
        fmt.Println("PASS")
    } else {
        fmt.Println("FAIL empty")
    }
    if v, ok := MaxSlice([]int{-3,-1,-4}); ok && v == -1 {
        fmt.Println("PASS")
    } else {
        fmt.Printf("FAIL negatives: got %d %v\n", v, ok)
    }
""",
        "n_tests": 3,
    },
    {
        "id": "go_filter_even",
        "prompt": "Write a Go function `FilterEven(nums []int) []int` that returns a new slice containing only the even numbers, preserving order.",
        "func_name": "FilterEven",
        "imports": ["reflect"],
        "test_main": r"""
    if reflect.DeepEqual(FilterEven([]int{1,2,3,4,5,6}), []int{2,4,6}) {
        fmt.Println("PASS")
    } else {
        fmt.Printf("FAIL: %v\n", FilterEven([]int{1,2,3,4,5,6}))
    }
    if reflect.DeepEqual(FilterEven([]int{1,3,5}), []int{}) || len(FilterEven([]int{1,3,5})) == 0 {
        fmt.Println("PASS")
    } else {
        fmt.Printf("FAIL odds: %v\n", FilterEven([]int{1,3,5}))
    }
""",
        "n_tests": 2,
    },
    {
        "id": "go_contains",
        "prompt": "Write a Go function `Contains(slice []string, item string) bool` that returns true if the slice contains the given string.",
        "func_name": "Contains",
        "imports": [],
        "test_main": r"""
    if Contains([]string{"a","b","c"}, "b") { fmt.Println("PASS") } else { fmt.Println("FAIL found") }
    if !Contains([]string{"a","b","c"}, "z") { fmt.Println("PASS") } else { fmt.Println("FAIL not found") }
    if !Contains([]string{}, "a") { fmt.Println("PASS") } else { fmt.Println("FAIL empty") }
""",
        "n_tests": 3,
    },
    {
        "id": "go_sum_ints",
        "prompt": "Write a Go function `SumInts(nums []int) int` that returns the sum of all integers in the slice. Return 0 for an empty slice.",
        "func_name": "SumInts",
        "imports": [],
        "test_main": r"""
    if SumInts([]int{1,2,3,4,5}) == 15 { fmt.Println("PASS") } else { fmt.Printf("FAIL: %d\n", SumInts([]int{1,2,3,4,5})) }
    if SumInts([]int{}) == 0 { fmt.Println("PASS") } else { fmt.Printf("FAIL empty: %d\n", SumInts([]int{})) }
    if SumInts([]int{-1,1}) == 0 { fmt.Println("PASS") } else { fmt.Printf("FAIL zero sum: %d\n", SumInts([]int{-1,1})) }
""",
        "n_tests": 3,
    },
]

# ── Track 2: Bug fixing ────────────────────────────────────────────────────────
# broken_code: the code handed to the model
# prompt: instruction to the model
# test_cases: same format as Track 1 (for Python/NodeJS bugs)
# For Go bugs: test_main + func_name same as Track 1

TRACK2_PYTHON = [
    {
        "id": "bug_py_off_by_one",
        "prompt": "The following Python function is supposed to return the sum of 1 to n inclusive, but it has a bug. Fix it.\n\n```python\ndef sum_to_n(n):\n    total = 0\n    for i in range(n):  # bug here\n        total += i\n    return total\n```",
        "test_cases": [
            {"call": "sum_to_n(5)", "expected": "15"},
            {"call": "sum_to_n(1)", "expected": "1"},
            {"call": "sum_to_n(0)", "expected": "0"},
        ],
    },
    {
        "id": "bug_py_mutable_default",
        "prompt": "The following Python function appends items to a list but behaves unexpectedly across calls. Fix the bug.\n\n```python\ndef append_item(item, lst=[]):\n    lst.append(item)\n    return lst\n```",
        "test_cases": [
            {"call": "append_item(1, [])", "expected": "[1]"},
            {"call": "append_item(2, [])", "expected": "[2]"},
            {"call": "append_item(1, [0])", "expected": "[0, 1]"},
        ],
    },
    {
        "id": "bug_py_wrong_return",
        "prompt": "The following Python function should return True if a list contains any negative numbers, but it never returns True. Fix it.\n\n```python\ndef has_negative(nums):\n    for n in nums:\n        if n < 0:\n            found = True\n    return False\n```",
        "test_cases": [
            {"call": "has_negative([-1, 2, 3])", "expected": "True"},
            {"call": "has_negative([1, 2, 3])", "expected": "False"},
            {"call": "has_negative([])", "expected": "False"},
        ],
    },
    {
        "id": "bug_py_operator",
        "prompt": "The following function should return all numbers greater than or equal to the threshold, but it excludes the threshold value. Fix it.\n\n```python\ndef at_least(nums, threshold):\n    return [n for n in nums if n > threshold]\n```",
        "test_cases": [
            {"call": "at_least([1,2,3,4,5], 3)", "expected": "[3, 4, 5]"},
            {"call": "at_least([1,2,3], 5)", "expected": "[]"},
        ],
    },
    {
        "id": "bug_py_string_concat",
        "prompt": "The following function should return a greeting string like 'Hello, Alice (age 30)' but raises a TypeError. Fix it.\n\n```python\ndef greet(name, age):\n    return 'Hello, ' + name + ' (age ' + age + ')'\n```",
        "test_cases": [
            {"call": "greet('Alice', 30)", "expected": "'Hello, Alice (age 30)'"},
            {"call": "greet('Bob', 25)", "expected": "'Hello, Bob (age 25)'"},
        ],
    },
    {
        "id": "bug_py_integer_div",
        "prompt": "The following function should return the average as a float, but always rounds down to an integer. Fix it.\n\n```python\ndef average(nums):\n    return sum(nums) // len(nums)\n```",
        "test_cases": [
            {"call": "average([1, 2, 4])", "expected": "2.3333333333333335"},
            {"call": "average([1, 1])", "expected": "1.0"},
            {"call": "average([10])", "expected": "10.0"},
        ],
    },
    {
        "id": "bug_py_sort_returns_none",
        "prompt": "The following function should return a sorted copy of the list, but always returns None. Fix it.\n\n```python\ndef sorted_list(lst):\n    return lst.sort()\n```",
        "test_cases": [
            {"call": "sorted_list([3,1,2])", "expected": "[1, 2, 3]"},
            {"call": "sorted_list([])", "expected": "[]"},
            {"call": "sorted_list([5,5,1])", "expected": "[1, 5, 5]"},
        ],
    },
    {
        "id": "bug_py_count_keyerror",
        "prompt": "The following function should count occurrences of each item but raises KeyError on the first unseen item. Fix it.\n\n```python\ndef count_items(items):\n    counts = {}\n    for item in items:\n        counts[item] += 1\n    return counts\n```",
        "test_cases": [
            {"call": "count_items(['a','b','a','c','b','a'])", "expected": "{'a': 3, 'b': 2, 'c': 1}"},
            {"call": "count_items([])", "expected": "{}"},
            {"call": "count_items([1])", "expected": "{1: 1}"},
        ],
    },
    {
        "id": "bug_py_missing_return",
        "prompt": "The following function should return the absolute value of n, but returns None for non-negative inputs. Fix it.\n\n```python\ndef my_abs(n):\n    if n < 0:\n        return -n\n```",
        "test_cases": [
            {"call": "my_abs(-5)", "expected": "5"},
            {"call": "my_abs(3)", "expected": "3"},
            {"call": "my_abs(0)", "expected": "0"},
        ],
    },
    {
        "id": "bug_py_mutate_while_iterate",
        "prompt": "The following function should remove all negative numbers but skips some due to mutation during iteration. Fix it.\n\n```python\ndef remove_negatives(nums):\n    for n in nums:\n        if n < 0:\n            nums.remove(n)\n    return nums\n```",
        "test_cases": [
            {"call": "remove_negatives([-1, -2, 3, 4])", "expected": "[3, 4]"},
            {"call": "remove_negatives([1, 2, 3])", "expected": "[1, 2, 3]"},
            {"call": "remove_negatives([-1, -1, -1])", "expected": "[]"},
        ],
    },
    {
        "id": "bug_py_join_int",
        "prompt": "The following function should join a list of numbers as a comma-separated string, but raises TypeError. Fix it.\n\n```python\ndef join_nums(nums):\n    return ','.join(nums)\n```",
        "test_cases": [
            {"call": "join_nums([1, 2, 3])", "expected": "'1,2,3'"},
            {"call": "join_nums([])", "expected": "''"},
            {"call": "join_nums([42])", "expected": "'42'"},
        ],
    },
    {
        "id": "bug_py_wrong_condition",
        "prompt": "The following function should return True if n is strictly between lo and hi (exclusive), but the condition is incorrect. Fix it.\n\n```python\ndef between(n, lo, hi):\n    return lo < hi < n\n```",
        "test_cases": [
            {"call": "between(5, 1, 10)", "expected": "True"},
            {"call": "between(1, 1, 10)", "expected": "False"},
            {"call": "between(10, 1, 10)", "expected": "False"},
            {"call": "between(0, 1, 10)", "expected": "False"},
        ],
    },
    {
        "id": "bug_py_dict_get",
        "prompt": "The following function should return a default value when a key is missing, but raises KeyError. Fix it.\n\n```python\ndef safe_get(d, key, default):\n    return d[key]\n```",
        "test_cases": [
            {"call": "safe_get({'a': 1}, 'a', 0)", "expected": "1"},
            {"call": "safe_get({'a': 1}, 'b', 0)", "expected": "0"},
            {"call": "safe_get({}, 'x', 'none')", "expected": "'none'"},
        ],
    },
    {
        "id": "bug_py_strip_compare",
        "prompt": "The following function should compare two strings ignoring surrounding whitespace, but gives wrong results when either string has leading/trailing spaces. Fix it.\n\n```python\ndef equal_stripped(a, b):\n    return a == b\n```",
        "test_cases": [
            {"call": "equal_stripped('hello', 'hello')", "expected": "True"},
            {"call": "equal_stripped('  hello  ', 'hello')", "expected": "True"},
            {"call": "equal_stripped('hello', 'world')", "expected": "False"},
        ],
    },
    {
        "id": "bug_py_wrong_return_branch",
        "prompt": "The following function should return 'fizz' for multiples of 3, 'buzz' for multiples of 5, 'fizzbuzz' for both, and the number otherwise — but the order of checks is wrong. Fix it.\n\n```python\ndef fizzbuzz(n):\n    if n % 3 == 0:\n        return 'fizz'\n    elif n % 5 == 0:\n        return 'buzz'\n    elif n % 15 == 0:\n        return 'fizzbuzz'\n    return str(n)\n```",
        "test_cases": [
            {"call": "fizzbuzz(15)", "expected": "'fizzbuzz'"},
            {"call": "fizzbuzz(9)", "expected": "'fizz'"},
            {"call": "fizzbuzz(10)", "expected": "'buzz'"},
            {"call": "fizzbuzz(7)", "expected": "'7'"},
        ],
    },
]

TRACK2_NODEJS = [
    {
        "id": "bug_js_missing_await",
        "prompt": "The following async JavaScript function is supposed to return the length of a resolved promise value, but it returns wrong results. Fix it.\n\n```javascript\nasync function getLength(promise) {\n    const value = promise;  // bug: missing await\n    return value.length;\n}\n```",
        "test_js": r"""
async function runTests() {
    const r1 = await getLength(Promise.resolve('hello'));
    console.log(r1 === 5 ? 'PASS' : 'FAIL: got ' + r1);
    const r2 = await getLength(Promise.resolve([1,2,3]));
    console.log(r2 === 3 ? 'PASS' : 'FAIL: got ' + r2);
}
runTests();
""",
        "n_tests": 2,
    },
    {
        "id": "bug_js_mutates_input",
        "prompt": "The following function should return a sorted copy of the input array without modifying the original. Fix the bug.\n\n```javascript\nfunction sortedCopy(arr) {\n    return arr.sort();\n}\n```",
        "test_js": r"""
const orig = [3,1,4,1,5,9,2,6];
const copy = orig.slice();
const result = sortedCopy(orig);
const origUnchanged = JSON.stringify(orig) === JSON.stringify([3,1,4,1,5,9,2,6]);
const resultSorted = JSON.stringify(result) === JSON.stringify([1,1,2,3,4,5,6,9]);
console.log(origUnchanged ? 'PASS' : 'FAIL: original was mutated to ' + JSON.stringify(orig));
console.log(resultSorted  ? 'PASS' : 'FAIL: result is ' + JSON.stringify(result));
""",
        "n_tests": 2,
    },
    {
        "id": "bug_js_loose_equality",
        "prompt": "The following function should return true only when both arguments are strictly the same value and type. It currently returns wrong results for some inputs. Fix it.\n\n```javascript\nfunction strictEqual(a, b) {\n    return a == b;\n}\n```",
        "test_js": r"""
console.log(strictEqual(1, 1)   === true  ? 'PASS' : 'FAIL 1==1');
console.log(strictEqual(1, '1') === false ? 'PASS' : 'FAIL 1==\"1\"');
console.log(strictEqual(0, '')  === false ? 'PASS' : 'FAIL 0==\"\"');
""",
        "n_tests": 3,
    },
    {
        "id": "bug_js_promise_no_return",
        "prompt": "The following async function should resolve to double the input value, but always resolves to undefined. Fix it.\n\n```javascript\nasync function doubleAsync(promise) {\n    promise.then(v => v * 2);\n}\n```",
        "test_js": r"""
async function runTests() {
    const r1 = await doubleAsync(Promise.resolve(5));
    console.log(r1 === 10 ? 'PASS' : 'FAIL: got ' + r1);
    const r2 = await doubleAsync(Promise.resolve(0));
    console.log(r2 === 0 ? 'PASS' : 'FAIL: got ' + r2);
}
runTests();
""",
        "n_tests": 2,
    },
    {
        "id": "bug_js_await_loop",
        "prompt": "The following async function should collect all resolved promise values into an array, but the array is always full of unresolved Promises. Fix it.\n\n```javascript\nasync function collectAll(promises) {\n    const results = [];\n    for (const p of promises) {\n        results.push(p);\n    }\n    return results;\n}\n```",
        "test_js": r"""
async function runTests() {
    const vals = await collectAll([Promise.resolve(1), Promise.resolve(2), Promise.resolve(3)]);
    console.log(JSON.stringify(vals) === '[1,2,3]' ? 'PASS' : 'FAIL: ' + JSON.stringify(vals));
    const empty = await collectAll([]);
    console.log(JSON.stringify(empty) === '[]' ? 'PASS' : 'FAIL empty: ' + JSON.stringify(empty));
}
runTests();
""",
        "n_tests": 2,
    },
]

TRACK2_GO = [
    {
        "id": "bug_go_off_by_one",
        "prompt": "The following Go function should return the last element of a slice, but it panics on single-element slices. Fix it.\n\n```go\nfunc LastElement(s []int) int {\n    return s[len(s)]\n}\n```",
        "func_name": "LastElement",
        "imports": [],
        "test_main": r"""
    if LastElement([]int{1,2,3}) == 3 { fmt.Println("PASS") } else { fmt.Println("FAIL [1,2,3]") }
    if LastElement([]int{42})    == 42 { fmt.Println("PASS") } else { fmt.Println("FAIL [42]") }
    if LastElement([]int{5,10})  == 10 { fmt.Println("PASS") } else { fmt.Println("FAIL [5,10]") }
""",
        "n_tests": 3,
    },
    {
        "id": "bug_go_int_division",
        "prompt": "The following Go function should compute the average of a slice as a float64, but it always returns a whole number. Fix it.\n\n```go\nfunc Average(nums []int) float64 {\n    sum := 0\n    for _, n := range nums {\n        sum += n\n    }\n    return float64(sum / len(nums))\n}\n```",
        "func_name": "Average",
        "imports": ["math"],
        "test_main": r"""
    if math.Abs(Average([]int{1,2,3,4,5}) - 3.0) < 0.001 { fmt.Println("PASS") } else { fmt.Printf("FAIL avg [1..5]: %f\n", Average([]int{1,2,3,4,5})) }
    if math.Abs(Average([]int{1,2}) - 1.5) < 0.001 { fmt.Println("PASS") } else { fmt.Printf("FAIL avg [1,2]: %f\n", Average([]int{1,2})) }
""",
        "n_tests": 2,
    },
    {
        "id": "bug_go_nil_check",
        "prompt": "The following Go function is supposed to return the length of a map, or 0 if nil. It panics on nil input. Fix it.\n\n```go\nfunc MapLen(m map[string]int) int {\n    return len(m)\n}\n```",
        "func_name": "MapLen",
        "imports": [],
        "test_main": r"""
    if MapLen(nil) == 0 { fmt.Println("PASS") } else { fmt.Printf("FAIL nil: %d\n", MapLen(nil)) }
    if MapLen(map[string]int{"a":1,"b":2}) == 2 { fmt.Println("PASS") } else { fmt.Println("FAIL non-nil") }
""",
        "n_tests": 2,
        # Note: len(nil map) is actually 0 in Go and doesn't panic, but the intent
        # of this problem tests that the model understands nil safety. The "bug"
        # prompt causes many models to add an explicit nil guard, which is the lesson.
    },
    {
        "id": "bug_go_append_no_reassign",
        "prompt": "The following Go function should append item to the slice only if it's not already present, but the append result is never captured. Fix it.\n\n```go\nfunc AppendUnique(s []string, item string) []string {\n    for _, v := range s {\n        if v == item {\n            return s\n        }\n    }\n    append(s, item)\n    return s\n}\n```",
        "func_name": "AppendUnique",
        "imports": ["reflect"],
        "test_main": r"""
    got := AppendUnique([]string{"a","b"}, "c")
    if reflect.DeepEqual(got, []string{"a","b","c"}) { fmt.Println("PASS") } else { fmt.Printf("FAIL append: %v\n", got) }
    got2 := AppendUnique([]string{"a","b"}, "a")
    if reflect.DeepEqual(got2, []string{"a","b"}) { fmt.Println("PASS") } else { fmt.Printf("FAIL dup: %v\n", got2) }
    got3 := AppendUnique([]string{}, "x")
    if reflect.DeepEqual(got3, []string{"x"}) { fmt.Println("PASS") } else { fmt.Printf("FAIL empty: %v\n", got3) }
""",
        "n_tests": 3,
    },
    {
        "id": "bug_go_nil_map_assign",
        "prompt": "The following Go function should build a map from a slice of keys but panics with 'assignment to entry in nil map'. Fix it.\n\n```go\nfunc IndexSlice(keys []string) map[string]int {\n    var m map[string]int\n    for i, k := range keys {\n        m[k] = i\n    }\n    return m\n}\n```",
        "func_name": "IndexSlice",
        "imports": [],
        "test_main": r"""
    m := IndexSlice([]string{"a","b","c"})
    if m["a"] == 0 && m["b"] == 1 && m["c"] == 2 { fmt.Println("PASS") } else { fmt.Printf("FAIL: %v\n", m) }
    m2 := IndexSlice([]string{})
    if len(m2) == 0 { fmt.Println("PASS") } else { fmt.Printf("FAIL empty: %v\n", m2) }
""",
        "n_tests": 2,
    },
    {
        "id": "bug_go_trim_last_panic",
        "prompt": "The following Go function should return all elements except the last, but panics on an empty slice. Fix it.\n\n```go\nfunc DropLast(s []int) []int {\n    return s[:len(s)-1]\n}\n```",
        "func_name": "DropLast",
        "imports": ["reflect"],
        "test_main": r"""
    if reflect.DeepEqual(DropLast([]int{1,2,3}), []int{1,2}) { fmt.Println("PASS") } else { fmt.Printf("FAIL: %v\n", DropLast([]int{1,2,3})) }
    if reflect.DeepEqual(DropLast([]int{42}), []int{}) || len(DropLast([]int{42})) == 0 { fmt.Println("PASS") } else { fmt.Printf("FAIL single: %v\n", DropLast([]int{42})) }
    if reflect.DeepEqual(DropLast([]int{}), []int{}) || len(DropLast([]int{})) == 0 { fmt.Println("PASS") } else { fmt.Printf("FAIL empty: %v\n", DropLast([]int{})) }
""",
        "n_tests": 3,
    },
    {
        "id": "bug_go_zero_slice",
        "prompt": "The following Go function should return a slice of n zeros, but returns an empty slice. Fix it.\n\n```go\nfunc ZeroSlice(n int) []int {\n    return make([]int, 0, n)\n}\n```",
        "func_name": "ZeroSlice",
        "imports": ["reflect"],
        "test_main": r"""
    if reflect.DeepEqual(ZeroSlice(3), []int{0,0,0}) { fmt.Println("PASS") } else { fmt.Printf("FAIL: %v\n", ZeroSlice(3)) }
    if reflect.DeepEqual(ZeroSlice(0), []int{}) || len(ZeroSlice(0)) == 0 { fmt.Println("PASS") } else { fmt.Printf("FAIL zero: %v\n", ZeroSlice(0)) }
    if reflect.DeepEqual(ZeroSlice(1), []int{0}) { fmt.Println("PASS") } else { fmt.Printf("FAIL one: %v\n", ZeroSlice(1)) }
""",
        "n_tests": 3,
    },
]

# ── Track 2: Refactoring ──────────────────────────────────────────────────────
# Working but messy code → ask model to clean it up.
# Correctness is automated (same test_cases / test_js format as above).
# Code quality is scored manually during review.

TRACK2_REFACTOR_PYTHON = [
    {
        "id": "refactor_py_list_comp",
        "prompt": "Refactor the following Python function to be more idiomatic (hint: list comprehension). Keep the same behavior.\n\n```python\ndef double_evens(nums):\n    result = []\n    for n in nums:\n        if n % 2 == 0:\n            result.append(n * 2)\n    return result\n```",
        "test_cases": [
            {"call": "double_evens([1,2,3,4,5,6])", "expected": "[4, 8, 12]"},
            {"call": "double_evens([])", "expected": "[]"},
            {"call": "double_evens([1,3,5])", "expected": "[]"},
        ],
    },
    {
        "id": "refactor_py_early_return",
        "prompt": "Refactor the following function to reduce nesting using early returns. Keep the same behavior.\n\n```python\ndef describe(n):\n    if n is not None:\n        if isinstance(n, int):\n            if n > 0:\n                return 'positive'\n            else:\n                return 'non-positive'\n        else:\n            return 'not an int'\n    else:\n        return 'none'\n```",
        "test_cases": [
            {"call": "describe(5)", "expected": "'positive'"},
            {"call": "describe(-1)", "expected": "'non-positive'"},
            {"call": "describe('x')", "expected": "'not an int'"},
            {"call": "describe(None)", "expected": "'none'"},
        ],
    },
    {
        "id": "refactor_py_manual_max",
        "prompt": "Refactor the following function to use Python built-ins instead of a manual loop. Keep the same behavior.\n\n```python\ndef longest_word(words):\n    best = ''\n    for w in words:\n        if len(w) > len(best):\n            best = w\n    return best\n```",
        "test_cases": [
            {"call": "longest_word(['cat','elephant','dog'])", "expected": "'elephant'"},
            {"call": "longest_word(['a'])", "expected": "'a'"},
            {"call": "longest_word(['ab','cd'])", "expected": "'ab'"},
        ],
    },
    {
        "id": "refactor_py_fstring",
        "prompt": "Refactor the following function to use an f-string instead of concatenation. Keep the same behavior.\n\n```python\ndef format_range(lo, hi):\n    return '[' + str(lo) + ', ' + str(hi) + ']'\n```",
        "test_cases": [
            {"call": "format_range(1, 10)", "expected": "'[1, 10]'"},
            {"call": "format_range(0, 0)", "expected": "'[0, 0]'"},
            {"call": "format_range(-5, 5)", "expected": "'[-5, 5]'"},
        ],
    },
    {
        "id": "refactor_py_dict_comprehension",
        "prompt": "Refactor the following function to use a dict comprehension. Keep the same behavior.\n\n```python\ndef square_map(nums):\n    result = {}\n    for n in nums:\n        result[n] = n * n\n    return result\n```",
        "test_cases": [
            {"call": "square_map([1,2,3,4])", "expected": "{1: 1, 2: 4, 3: 9, 4: 16}"},
            {"call": "square_map([])", "expected": "{}"},
            {"call": "square_map([5])", "expected": "{5: 25}"},
        ],
    },
]

TRACK2_REFACTOR_NODEJS = [
    {
        "id": "refactor_js_map",
        "prompt": "Refactor the following JavaScript function to use Array.map instead of a for loop. Keep the same behavior.\n\n```javascript\nfunction doubleAll(arr) {\n    const result = [];\n    for (let i = 0; i < arr.length; i++) {\n        result.push(arr[i] * 2);\n    }\n    return result;\n}\n```",
        "test_js": r"""
console.log(JSON.stringify(doubleAll([1,2,3])) === '[2,4,6]' ? 'PASS' : 'FAIL: ' + JSON.stringify(doubleAll([1,2,3])));
console.log(JSON.stringify(doubleAll([])) === '[]' ? 'PASS' : 'FAIL empty');
""",
        "n_tests": 2,
    },
    {
        "id": "refactor_js_reduce",
        "prompt": "Refactor the following JavaScript function to use Array.reduce instead of a for loop. Keep the same behavior.\n\n```javascript\nfunction sumArray(arr) {\n    let total = 0;\n    for (const n of arr) {\n        total += n;\n    }\n    return total;\n}\n```",
        "test_js": r"""
console.log(sumArray([1,2,3,4,5]) === 15 ? 'PASS' : 'FAIL: ' + sumArray([1,2,3,4,5]));
console.log(sumArray([]) === 0 ? 'PASS' : 'FAIL empty');
console.log(sumArray([-1,1]) === 0 ? 'PASS' : 'FAIL zero');
""",
        "n_tests": 3,
    },
    {
        "id": "refactor_js_filter",
        "prompt": "Refactor the following JavaScript function to use Array.filter. Keep the same behavior.\n\n```javascript\nfunction onlyPositive(arr) {\n    const result = [];\n    for (const n of arr) {\n        if (n > 0) result.push(n);\n    }\n    return result;\n}\n```",
        "test_js": r"""
console.log(JSON.stringify(onlyPositive([1,-2,3,-4,5])) === '[1,3,5]' ? 'PASS' : 'FAIL: ' + JSON.stringify(onlyPositive([1,-2,3,-4,5])));
console.log(JSON.stringify(onlyPositive([-1,-2])) === '[]' ? 'PASS' : 'FAIL all neg');
""",
        "n_tests": 2,
    },
    {
        "id": "refactor_js_object_destructure",
        "prompt": "Refactor the following JavaScript function to use destructuring. Keep the same behavior.\n\n```javascript\nfunction formatUser(user) {\n    const name = user.name;\n    const age = user.age;\n    const city = user.city;\n    return name + ' (' + age + ') from ' + city;\n}\n```",
        "test_js": r"""
console.log(formatUser({name:'Alice',age:30,city:'NYC'}) === 'Alice (30) from NYC' ? 'PASS' : 'FAIL: ' + formatUser({name:'Alice',age:30,city:'NYC'}));
console.log(formatUser({name:'Bob',age:25,city:'LA'}) === 'Bob (25) from LA' ? 'PASS' : 'FAIL: ' + formatUser({name:'Bob',age:25,city:'LA'}));
""",
        "n_tests": 2,
    },
    {
        "id": "refactor_js_optional_chain",
        "prompt": "Refactor the following JavaScript function to use optional chaining (?.) instead of nested checks. Keep the same behavior.\n\n```javascript\nfunction getCity(user) {\n    if (user && user.address && user.address.city) {\n        return user.address.city;\n    }\n    return null;\n}\n```",
        "test_js": r"""
console.log(getCity({address:{city:'Paris'}}) === 'Paris' ? 'PASS' : 'FAIL found');
console.log(getCity({address:{}}) === null ? 'PASS' : 'FAIL no city');
console.log(getCity(null) === null ? 'PASS' : 'FAIL null user');
""",
        "n_tests": 3,
    },
]

# ── Track 3: Fill-in-the-middle ────────────────────────────────────────────────
# prefix: code before the gap
# suffix: code after the gap (may be empty string)
# expected_output: what the assembled code should print when run
# run_code: the full runnable code with FILL_HERE replaced — used to verify
# For non-FIM models: prompt is constructed from prefix/suffix

TRACK3_PYTHON = [
    {
        "id": "fim_py_binary_search",
        "prefix": "def binary_search(arr, target):\n    lo, hi = 0, len(arr) - 1\n    while lo <= hi:\n        mid = (lo + hi) // 2\n        if arr[mid] == target:\n            return mid\n",
        "suffix": "\n    return -1\n",
        "expected_output": "3\n-1",
        "run_template": """\
def binary_search(arr, target):
    lo, hi = 0, len(arr) - 1
    while lo <= hi:
        mid = (lo + hi) // 2
        if arr[mid] == target:
            return mid
        {FILL}
    return -1
print(binary_search([1,3,5,7,9], 7))
print(binary_search([1,3,5,7,9], 4))
""",
    },
    {
        "id": "fim_py_fib_memo",
        "prefix": "_cache = {}\ndef fib(n):\n    if n <= 1:\n        return n\n    if n in _cache:\n        return _cache[n]\n",
        "suffix": "\n    return _cache[n]\n",
        "expected_output": "55\n6765",
        "run_template": """\
_cache = {}
def fib(n):
    if n <= 1:
        return n
    if n in _cache:
        return _cache[n]
    {FILL}
    return _cache[n]
print(fib(10))
print(fib(20))
""",
    },
    {
        "id": "fim_py_dict_invert",
        "prefix": "def invert_dict(d):\n    result = {}\n    for key, value in d.items():\n",
        "suffix": "\n    return result\n",
        "expected_output": "{'a': 1, 'b': 2}",
        "run_template": """\
def invert_dict(d):
    result = {}
    for key, value in d.items():
        {FILL}
    return result
print(invert_dict({1: 'a', 2: 'b'}))
""",
    },
    {
        "id": "fim_py_running_max",
        "prefix": "def running_max(nums):\n    if not nums:\n        return []\n    result = [nums[0]]\n    for n in nums[1:]:\n",
        "suffix": "\n    return result\n",
        "expected_output": "[1, 3, 3, 5, 5]",
        "run_template": """\
def running_max(nums):
    if not nums:
        return []
    result = [nums[0]]
    for n in nums[1:]:
        {FILL}
    return result
print(running_max([1,3,2,5,4]))
""",
    },
    {
        "id": "fim_py_flatten_deep",
        "prefix": "def flatten(lst):\n    result = []\n    for item in lst:\n        if isinstance(item, list):\n",
        "suffix": "\n        else:\n            result.append(item)\n    return result\n",
        "expected_output": "[1, 2, 3, 4, 5]",
        "run_template": """\
def flatten(lst):
    result = []
    for item in lst:
        if isinstance(item, list):
            {FILL}
        else:
            result.append(item)
    return result
print(flatten([1,[2,[3,[4]]],5]))
""",
    },
    {
        "id": "fim_py_count_chars",
        "prefix": "def char_count(s):\n    counts = {}\n    for c in s:\n",
        "suffix": "\n    return counts\n",
        "expected_output": "{'h': 1, 'e': 1, 'l': 3, 'o': 2, ' ': 1, 'w': 1, 'r': 1, 'd': 1}",
        "run_template": """\
def char_count(s):
    counts = {}
    for c in s:
        {FILL}
    return counts
print(char_count('hello world'))
""",
    },
    {
        "id": "fim_py_is_sorted",
        "prefix": "def is_sorted(lst):\n    for i in range(len(lst) - 1):\n",
        "suffix": "\n    return True\n",
        "expected_output": "True\nFalse\nTrue",
        "run_template": """\
def is_sorted(lst):
    for i in range(len(lst) - 1):
        {FILL}
    return True
print(is_sorted([1,2,3,4,5]))
print(is_sorted([1,3,2,4]))
print(is_sorted([]))
""",
    },
    {
        "id": "fim_py_merge_sorted",
        "prefix": "def merge_sorted(a, b):\n    result, i, j = [], 0, 0\n    while i < len(a) and j < len(b):\n",
        "suffix": "\n    return result + a[i:] + b[j:]\n",
        "expected_output": "[1, 2, 3, 4, 5, 6]",
        "run_template": """\
def merge_sorted(a, b):
    result, i, j = [], 0, 0
    while i < len(a) and j < len(b):
        {FILL}
    return result + a[i:] + b[j:]
print(merge_sorted([1,3,5], [2,4,6]))
""",
    },
]

TRACK3_NODEJS = [
    {
        "id": "fim_js_filter_map",
        "prefix": "function doubleEvens(arr) {\n    return arr\n        .filter(n => ",
        "suffix": ")\n        .map(n => n * 2);\n}",
        "expected_output": "[4,8,12]",
        "run_template": """\
function doubleEvens(arr) {
    return arr
        .filter(n => {FILL})
        .map(n => n * 2);
}
console.log(JSON.stringify(doubleEvens([1,2,3,4,5,6])));
""",
    },
    {
        "id": "fim_js_reduce_sum",
        "prefix": "function sumBy(arr, key) {\n    return arr.reduce((acc, item) => ",
        "suffix": ", 0);\n}",
        "expected_output": "9",
        "run_template": """\
function sumBy(arr, key) {
    return arr.reduce((acc, item) => {FILL}, 0);
}
console.log(sumBy([{v:1},{v:3},{v:5}], 'v'));
""",
    },
    {
        "id": "fim_js_error_first",
        "prefix": "function safeDivide(a, b) {\n    if (b === 0) {\n",
        "suffix": "\n    }\n    return [null, a / b];\n}",
        "expected_output": '["division by zero",null]\n[null,2.5]',
        "run_template": """\
function safeDivide(a, b) {
    if (b === 0) {
        {FILL}
    }
    return [null, a / b];
}
console.log(JSON.stringify(safeDivide(5, 0)));
console.log(JSON.stringify(safeDivide(5, 2)));
""",
    },
    {
        "id": "fim_js_object_pick",
        "prefix": "function pick(obj, keys) {\n    return keys.reduce((acc, k) => {\n",
        "suffix": "\n        return acc;\n    }, {});\n}",
        "expected_output": '{"a":1,"c":3}',
        "run_template": """\
function pick(obj, keys) {
    return keys.reduce((acc, k) => {
        {FILL}
        return acc;
    }, {});
}
console.log(JSON.stringify(pick({a:1,b:2,c:3}, ['a','c'])));
""",
    },
    {
        "id": "fim_js_clamp",
        "prefix": "function clamp(val, lo, hi) {\n    if (val < lo) return lo;\n",
        "suffix": "\n    return val;\n}",
        "expected_output": "1\n10\n5",
        "run_template": """\
function clamp(val, lo, hi) {
    if (val < lo) return lo;
    {FILL}
    return val;
}
console.log(clamp(-5, 1, 10));
console.log(clamp(20, 1, 10));
console.log(clamp(5, 1, 10));
""",
    },
    {
        "id": "fim_js_zip",
        "prefix": "function zip(a, b) {\n    const len = Math.min(a.length, b.length);\n    const result = [];\n    for (let i = 0; i < len; i++) {\n",
        "suffix": "\n    }\n    return result;\n}",
        "expected_output": "[[1,\"a\"],[2,\"b\"],[3,\"c\"]]",
        "run_template": """\
function zip(a, b) {
    const len = Math.min(a.length, b.length);
    const result = [];
    for (let i = 0; i < len; i++) {
        {FILL}
    }
    return result;
}
console.log(JSON.stringify(zip([1,2,3], ['a','b','c'])));
""",
    },
    {
        "id": "fim_js_flatten_one",
        "prefix": "function flattenOne(arr) {\n    return arr.reduce((acc, val) => ",
        "suffix": ", []);\n}",
        "expected_output": "[1,2,3,4,5,6]",
        "run_template": """\
function flattenOne(arr) {
    return arr.reduce((acc, val) => {FILL}, []);
}
console.log(JSON.stringify(flattenOne([[1,2],[3,4],[5,6]])));
""",
    },
]

TRACK3_GO = [
    {
        "id": "fim_go_error_wrap",
        "prefix": "func safeSqrt(x float64) (float64, error) {\n\tif x < 0 {\n",
        "suffix": "\n\t}\n\treturn math.Sqrt(x), nil\n}",
        "expected_output": "PASS\nPASS",
        "run_template": """\
package main

import (
    "fmt"
    "math"
    "errors"
)

func safeSqrt(x float64) (float64, error) {
    if x < 0 {
        {FILL}
    }
    return math.Sqrt(x), nil
}

func main() {
    _, err := safeSqrt(-1)
    if err != nil { fmt.Println("PASS") } else { fmt.Println("FAIL: expected error for -1") }
    v, err2 := safeSqrt(4)
    if err2 == nil && math.Abs(v-2.0) < 0.001 { fmt.Println("PASS") } else { fmt.Printf("FAIL: %v %v\\n", v, err2) }
}
""",
        # imports used in template only; model may use errors.New or fmt.Errorf
        "imports": ["fmt", "math", "errors"],
    },
    {
        "id": "fim_go_slice_dedupe",
        "prefix": "func Unique(s []string) []string {\n\tseen := make(map[string]bool)\n\tresult := []string{}\n\tfor _, v := range s {\n\t\tif !seen[v] {\n",
        "suffix": "\n\t\t}\n\t}\n\treturn result\n}",
        "expected_output": "PASS\nPASS",
        "run_template": """\
package main

import (
    "fmt"
    "reflect"
)

func Unique(s []string) []string {
    seen := make(map[string]bool)
    result := []string{}
    for _, v := range s {
        if !seen[v] {
            {FILL}
        }
    }
    return result
}

func main() {
    got := Unique([]string{"a","b","a","c","b"})
    if reflect.DeepEqual(got, []string{"a","b","c"}) { fmt.Println("PASS") } else { fmt.Printf("FAIL: %v\\n", got) }
    got2 := Unique([]string{})
    if len(got2) == 0 { fmt.Println("PASS") } else { fmt.Printf("FAIL empty: %v\\n", got2) }
}
""",
        "imports": ["fmt", "reflect"],
    },
    {
        "id": "fim_go_max_min",
        "prefix": "func Clamp(val, lo, hi int) int {\n\tif val < lo {\n\t\treturn lo\n\t}\n",
        "suffix": "\n\treturn val\n}",
        "expected_output": "PASS\nPASS\nPASS",
        "run_template": """\
package main

import "fmt"

func Clamp(val, lo, hi int) int {
    if val < lo {
        return lo
    }
    {FILL}
    return val
}

func main() {
    if Clamp(5, 1, 10) == 5  { fmt.Println("PASS") } else { fmt.Printf("FAIL mid: %d\\n", Clamp(5,1,10)) }
    if Clamp(0, 1, 10) == 1  { fmt.Println("PASS") } else { fmt.Printf("FAIL lo: %d\\n", Clamp(0,1,10)) }
    if Clamp(15, 1, 10) == 10 { fmt.Println("PASS") } else { fmt.Printf("FAIL hi: %d\\n", Clamp(15,1,10)) }
}
""",
        "imports": ["fmt"],
    },
    {
        "id": "fim_go_sum_slice",
        "prefix": "func SumSlice(nums []int) int {\n\ttotal := 0\n\tfor _, n := range nums {\n",
        "suffix": "\n\t}\n\treturn total\n}",
        "expected_output": "PASS\nPASS",
        "run_template": """\
package main

import "fmt"

func SumSlice(nums []int) int {
    total := 0
    for _, n := range nums {
        {FILL}
    }
    return total
}

func main() {
    if SumSlice([]int{1,2,3,4,5}) == 15 { fmt.Println("PASS") } else { fmt.Printf("FAIL: %d\\n", SumSlice([]int{1,2,3,4,5})) }
    if SumSlice([]int{}) == 0 { fmt.Println("PASS") } else { fmt.Printf("FAIL empty: %d\\n", SumSlice([]int{})) }
}
""",
        "imports": ["fmt"],
    },
    {
        "id": "fim_go_contains_str",
        "prefix": "func ContainsStr(slice []string, target string) bool {\n\tfor _, s := range slice {\n",
        "suffix": "\n\t}\n\treturn false\n}",
        "expected_output": "PASS\nPASS\nPASS",
        "run_template": """\
package main

import "fmt"

func ContainsStr(slice []string, target string) bool {
    for _, s := range slice {
        {FILL}
    }
    return false
}

func main() {
    if ContainsStr([]string{"a","b","c"}, "b") { fmt.Println("PASS") } else { fmt.Println("FAIL found") }
    if !ContainsStr([]string{"a","b","c"}, "z") { fmt.Println("PASS") } else { fmt.Println("FAIL not found") }
    if !ContainsStr([]string{}, "x") { fmt.Println("PASS") } else { fmt.Println("FAIL empty") }
}
""",
        "imports": ["fmt"],
    },
]

# ── Helpers: code extraction ───────────────────────────────────────────────────


def extract_code(response: str, language: str) -> str:
    """Extract the first/last code block from an LLM response."""
    lang_aliases = {
        "javascript": ["javascript", "js", "node"],
        "python": ["python", "py"],
    }
    alts = lang_aliases.get(language, [language])
    pattern = r"```(?:" + "|".join(re.escape(a) for a in alts) + r")?\n(.*?)```"
    blocks = re.findall(pattern, response, re.DOTALL | re.IGNORECASE)
    if blocks:
        return blocks[-1].strip()
    # fallback: strip surrounding ``` if no language tag
    stripped = re.sub(r"^```\w*\n?", "", response.strip())
    stripped = re.sub(r"\n?```$", "", stripped)
    return stripped.strip()


def extract_go_function(response: str, func_name: str) -> str:
    """Extract a named Go function from the response."""
    code = extract_code(response, "go")
    # Find 'func FuncName(' and grab everything to the matching closing brace
    pattern = re.compile(rf"(func\s+{re.escape(func_name)}\s*\(.*)", re.DOTALL)
    m = pattern.search(code)
    if not m:
        return code  # return as-is, let the compile step fail
    fn_text = m.group(0)
    # Count braces to find function end
    depth, start = 0, fn_text.find("{")
    if start == -1:
        return fn_text
    for i, ch in enumerate(fn_text[start:], start):
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return fn_text[: i + 1]
    return fn_text


# ── Helpers: code execution ────────────────────────────────────────────────────


def _run(cmd: list[str], input_text: str | None = None) -> tuple[int, str, str]:
    try:
        r = subprocess.run(
            cmd, input=input_text, capture_output=True, text=True, timeout=CODE_TIMEOUT
        )
        return r.returncode, r.stdout, r.stderr
    except subprocess.TimeoutExpired:
        return -1, "", "TIMEOUT"
    except FileNotFoundError:
        return -2, "", f"RUNTIME_NOT_FOUND: {cmd[0]}"


def run_python_tests(code: str, test_cases: list[dict]) -> tuple[int, int, list[str]]:
    """Execute Python code against test cases. Returns (passed, total, lines)."""
    harness_lines = []
    for tc in test_cases:
        harness_lines += [
            "try:",
            f"    _got = {tc['call']}",
            f"    _exp = {tc['expected']}",
            "    print('PASS' if _got == _exp else f'FAIL: got {_got!r} exp {_exp!r}')",
            "except Exception as _e:",
            "    print(f'ERROR: {_e}')",
        ]
    full = code + "\n\n" + "\n".join(harness_lines)
    with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
        f.write(full)
        fname = f.name
    try:
        rc, out, err = _run(["python3", fname])
        lines = (out + err).strip().splitlines()
        passed = sum(1 for l in lines if l.strip() == "PASS")
        return passed, len(test_cases), lines
    finally:
        os.unlink(fname)


def run_node_tests(code: str, test_js: str, n_tests: int) -> tuple[int, int, list[str]]:
    full = code + "\n\n" + test_js
    with tempfile.NamedTemporaryFile(mode="w", suffix=".js", delete=False) as f:
        f.write(full)
        fname = f.name
    try:
        rc, out, err = _run(["node", fname])
        lines = (out + err).strip().splitlines()
        passed = sum(1 for l in lines if l.strip() == "PASS")
        return passed, n_tests, lines
    finally:
        os.unlink(fname)


def run_go_tests(
    fn_code: str, imports: list[str], test_main: str, n_tests: int
) -> tuple[int, int, list[str]]:
    """Wrap extracted Go function in package main + test main()."""
    import_block = ""
    if imports:
        import_block = (
            "import (\n" + "\n".join(f'\t"{imp}"' for imp in imports) + "\n)\n"
        )
    # Also add fmt unconditionally (used by test_main)
    all_imports = list(dict.fromkeys(["fmt"] + imports))
    import_block = (
        "import (\n" + "\n".join(f'\t"{imp}"' for imp in all_imports) + "\n)\n"
    )
    full = f"package main\n\n{import_block}\n{fn_code}\n\nfunc main() {{{test_main}}}\n"
    with tempfile.NamedTemporaryFile(mode="w", suffix=".go", delete=False) as f:
        f.write(full)
        fname = f.name
    try:
        rc, out, err = _run(["go", "run", fname])
        if rc == -2:
            return 0, n_tests, ["GO_NOT_FOUND"]
        lines = (out + err).strip().splitlines()
        passed = sum(1 for l in lines if l.strip() == "PASS")
        return passed, n_tests, lines
    finally:
        os.unlink(fname)


def run_go_program(
    full_program: str, expected_output: str
) -> tuple[int, int, list[str]]:
    """Run a complete Go program and compare stdout to expected_output."""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".go", delete=False) as f:
        f.write(full_program)
        fname = f.name
    try:
        rc, out, err = _run(["go", "run", fname])
        if rc == -2:
            return 0, 1, ["GO_NOT_FOUND"]
        actual = out.strip()
        passed = 1 if actual == expected_output.strip() else 0
        detail = (
            "PASS"
            if passed
            else f"FAIL: got {actual!r} exp {expected_output.strip()!r}"
        )
        if err.strip():
            detail += f" | stderr: {err.strip()}"
        return passed, 1, [detail]
    finally:
        os.unlink(fname)


def run_python_fim(assembled: str, expected: str) -> tuple[int, int, list[str]]:
    with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
        f.write(assembled)
        fname = f.name
    try:
        rc, out, err = _run(["python3", fname])
        actual = out.strip()
        passed = 1 if actual == expected.strip() else 0
        detail = "PASS" if passed else f"FAIL: got {actual!r} exp {expected.strip()!r}"
        return passed, 1, [detail]
    finally:
        os.unlink(fname)


def run_node_fim(assembled: str, expected: str) -> tuple[int, int, list[str]]:
    with tempfile.NamedTemporaryFile(mode="w", suffix=".js", delete=False) as f:
        f.write(assembled)
        fname = f.name
    try:
        rc, out, err = _run(["node", fname])
        actual = out.strip()
        passed = 1 if actual == expected.strip() else 0
        detail = "PASS" if passed else f"FAIL: got {actual!r} exp {expected.strip()!r}"
        return passed, 1, [detail]
    finally:
        os.unlink(fname)


# ── vLLM API ───────────────────────────────────────────────────────────────────

_current_model_id: str = ""
_api_url: str = DEFAULT_API_URL
_ssh_host: str = ""   # when set, lifecycle commands and nvidia-smi run over SSH
_thinking_budget: int = 0  # extra tokens prepended to max_tokens for reasoning models;
                            # set by configure_globals() when is_reasoning=True


def _api_conn(timeout: int = LLM_TIMEOUT) -> http.client.HTTPConnection:
    from urllib.parse import urlparse
    p = urlparse(_api_url)
    return http.client.HTTPConnection(p.hostname or "127.0.0.1", p.port or 80, timeout=timeout)


def _post(path: str, payload: dict, timeout: int = LLM_TIMEOUT) -> dict:
    data = json.dumps(payload).encode()
    conn = _api_conn(timeout)
    conn.request("POST", f"/v1/{path}", data, {"Content-Type": "application/json"})
    resp = conn.getresponse()
    body = resp.read()
    if resp.status != 200:
        raise RuntimeError(f"API {resp.status}: {body[:200]}")
    return json.loads(body)


def _get(path: str, timeout: int = 10) -> dict | str:
    conn = _api_conn(timeout)
    conn.request("GET", f"/v1/{path}")
    resp = conn.getresponse()
    body = resp.read()
    if resp.status != 200:
        return {}
    try:
        return json.loads(body)
    except Exception:
        return body.decode()


def chat_with_usage(messages: list[dict], max_tokens: int = 1024, temperature: float = 0.0,
                    timeout: int = PER_PROBLEM_TIMEOUT) -> tuple[str, dict]:
    """Like chat(), but also returns the usage dict from the API response."""
    def _call() -> tuple[str, dict]:
        result = _post("chat/completions", {
            "model": _current_model_id,
            "messages": messages,
            "max_tokens": max_tokens + _thinking_budget,
            "temperature": temperature,
        })
        # vLLM's reasoning-parser sets content=null when a reasoning model exhausts
        # max_tokens mid-<think>. Treat as empty so callers (extract_code, etc.) don't crash.
        content = result["choices"][0]["message"]["content"] or ""
        usage = result.get("usage", {})
        return content, usage

    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as ex:
        future = ex.submit(_call)
        try:
            return future.result(timeout=timeout)
        except concurrent.futures.TimeoutError:
            raise TimeoutError(f"chat_with_usage() timed out after {timeout}s")


def chat(messages: list[dict], max_tokens: int = 1024, temperature: float = 0.0,
         timeout: int = PER_PROBLEM_TIMEOUT) -> str:
    """Single non-streaming chat completion with a wall-clock timeout."""
    def _call() -> str:
        result = _post("chat/completions", {
            "model": _current_model_id,
            "messages": messages,
            "max_tokens": max_tokens + _thinking_budget,
            "temperature": temperature,
        })
        # See chat_with_usage() — null content when reasoning runs out of budget.
        return result["choices"][0]["message"]["content"] or ""

    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as ex:
        future = ex.submit(_call)
        try:
            return future.result(timeout=timeout)
        except concurrent.futures.TimeoutError:
            raise TimeoutError(f"chat() timed out after {timeout}s")


def complete(prompt: str, max_tokens: int = 256, temperature: float = 0.0,
             timeout: int = PER_PROBLEM_TIMEOUT) -> str:
    """Raw completions endpoint (used for native FIM) with a wall-clock timeout."""
    def _call() -> str:
        result = _post("completions", {
            "model": _current_model_id,
            "prompt": prompt,
            "max_tokens": max_tokens,
            "temperature": temperature,
        })
        return result["choices"][0]["text"]

    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as ex:
        future = ex.submit(_call)
        try:
            return future.result(timeout=timeout)
        except concurrent.futures.TimeoutError:
            raise TimeoutError(f"complete() timed out after {timeout}s")


def measure_ttft(prompt: str, max_tokens: int = 80) -> float:
    """Streaming request; return seconds to first non-empty content token."""
    payload = json.dumps(
        {
            "model": _current_model_id,
            "messages": [{"role": "user", "content": prompt}],
            "max_tokens": max_tokens,
            "stream": True,
            "temperature": 0.0,
        }
    ).encode()
    conn = _api_conn(LLM_TIMEOUT)
    conn.request(
        "POST", "/v1/chat/completions", payload, {"Content-Type": "application/json"}
    )
    t0 = time.perf_counter()
    resp = conn.getresponse()
    for raw_line in resp:
        line = raw_line.decode().strip()
        if not line.startswith("data:"):
            continue
        body = line[5:].strip()
        if body == "[DONE]":
            break
        try:
            chunk = json.loads(body)
            content = chunk["choices"][0].get("delta", {}).get("content", "")
            if content:
                return time.perf_counter() - t0
        except Exception:
            continue
    return time.perf_counter() - t0


def get_vllm_metrics() -> dict:
    """Scrape key metrics from vLLM /metrics Prometheus endpoint."""
    conn = _api_conn(timeout=5)
    conn.request("GET", "/metrics")
    resp = conn.getresponse()
    text = resp.read().decode()
    out = {}
    for line in text.splitlines():
        if line.startswith("#"):
            continue
        for key in [
            "vllm:avg_generation_throughput_toks_per_s",
            "vllm:gpu_cache_usage_perc",
            "vllm:num_requests_running",
        ]:
            if line.startswith(key + " ") or line.startswith(key + "{"):
                try:
                    out[key] = float(line.split()[-1])
                except Exception:
                    pass
    return out


# ── GPU stats ──────────────────────────────────────────────────────────────────


def get_gpu_stats() -> dict:
    """
    Collect GPU stats via nvidia-smi.
    Runs over SSH when _ssh_host is set, locally otherwise.
    Falls back to vLLM /metrics if nvidia-smi is unavailable.
    """
    nvidia_smi_cmd = [
        "nvidia-smi",
        "--query-gpu=index,name,memory.used,memory.free,memory.total,temperature.gpu",
        "--format=csv,noheader,nounits",
    ]
    try:
        if _ssh_host:
            result = _remote(nvidia_smi_cmd)
            out = result.stdout
            if result.returncode != 0:
                raise RuntimeError(result.stderr)
        else:
            out = subprocess.check_output(nvidia_smi_cmd, timeout=10, text=True)

        gpus = []
        for line in out.strip().splitlines():
            idx, name, used, free, total, temp = [x.strip() for x in line.split(",")]
            gpus.append({
                "index": int(idx),
                "name": name,
                "vram_used_mb": int(used),
                "vram_free_mb": int(free),
                "vram_total_mb": int(total),
                "temp_c": int(temp),
            })
        source = f"nvidia-smi-ssh:{_ssh_host}" if _ssh_host else "nvidia-smi"
        return {"source": source, "gpus": gpus,
                "total_used_mb": sum(g["vram_used_mb"] for g in gpus)}
    except Exception:
        pass

    # Fallback: vLLM /metrics (no per-GPU VRAM MB, but cache utilisation available)
    try:
        metrics = get_vllm_metrics()
        return {
            "source": "vllm-metrics-fallback",
            "note": "nvidia-smi unavailable",
            "gpu_cache_usage_pct": metrics.get("vllm:gpu_cache_usage_perc"),
        }
    except Exception as e:
        return {"source": "unavailable", "error": str(e)}


# ── vLLM lifecycle ─────────────────────────────────────────────────────────────


def _remote(cmd: list[str], check: bool = False, sudo: bool = False) -> subprocess.CompletedProcess:
    """Run a shell command on the target host — via SSH if _ssh_host is set, locally otherwise."""
    if sudo:
        cmd = ["sudo"] + cmd
    full_cmd = (["ssh", _ssh_host] + cmd) if _ssh_host else cmd
    return subprocess.run(full_cmd, capture_output=True, text=True, check=check)


def stop_container(name: str) -> None:
    _remote(["podman", "stop", name], sudo=True)
    _remote(["podman", "rm",   name], sudo=True)


def stop_prod_services() -> None:
    log("Stopping production services to free VRAM...")
    for svc in PROD_SERVICES:
        _remote(["systemctl", "stop", svc], sudo=True)
        log(f"  stopped {svc}")


def restart_prod_services() -> None:
    log("Restarting production services...")
    for svc in reversed(PROD_SERVICES):
        _remote(["systemctl", "start", svc], sudo=True)
        log(f"  started {svc}")


def start_vllm(cfg: dict) -> None:
    # Kill any container with "vllm" in its name — catches manually-started containers
    # (e.g. "vllm-bench-test") that would squat on port 8001 and silently intercept
    # wait_for_ready, causing all subsequent benchmarks to run against the wrong model.
    _remote(["bash", "-c",
             "podman ps -q --filter 'name=vllm' | xargs -r podman stop; "
             "podman ps -aq --filter 'name=vllm' | xargs -r podman rm"],
            sudo=True)
    stop_container(CONTAINER)

    from urllib.parse import urlparse as _up
    vllm_port = _up(_api_url).port or 8001

    image = cfg.get("image", VLLM_IMAGE)

    # Pre-pull the image so progress is visible and podman run -d doesn't block silently.
    inspect = _remote(["podman", "image", "exists", image], sudo=True)
    if inspect.returncode != 0:
        log(f"Pulling image {image} (not cached)...")
        pull = _remote(["podman", "pull", image], sudo=True)
        if pull.returncode != 0:
            raise RuntimeError(f"Failed to pull image {image}:\n{pull.stderr}")
        log("Image pull complete.")

    cmd = [
        "podman", "run", "--name", CONTAINER,
        "--device", "nvidia.com/gpu=all",
        "--ipc=host",
        "--ulimit", "memlock=-1",
        "--network=host",
        "-v", f"{MODEL_CACHE}:/root/.cache/huggingface:z",
        "--env-file", "/etc/vllm/env",
        "-d",
        image,
        "--model", cfg["hf_id"],
        "--tensor-parallel-size", "2",
        "--gpu-memory-utilization", "0.95",
        "--max-num-seqs", "32",
        "--enable-prefix-caching",
        "--host", "0.0.0.0",
        "--port", str(vllm_port),
    ]
    if cfg.get("quantization"):
        cmd += ["--quantization", cfg["quantization"]]
    if cfg.get("max_model_len"):
        cmd += ["--max-model-len", str(cfg["max_model_len"])]
    if cfg.get("reasoning_parser"):
        cmd += ["--reasoning-parser", cfg["reasoning_parser"]]
    if cfg.get("chat_template"):
        # Write the Jinja2 template into MODEL_CACHE (already mounted into the container
        # at /root/.cache/huggingface) so vLLM can read it at the in-container path.
        # Use base64 to avoid quoting issues with template characters like single quotes.
        import base64 as _b64
        host_tpl = f"{MODEL_CACHE}/chat_template.jinja"
        container_tpl = "/root/.cache/huggingface/chat_template.jinja"
        encoded = _b64.b64encode(cfg["chat_template"].encode()).decode()
        _remote(["bash", "-c", f"echo {encoded} | base64 -d > {host_tpl}"], sudo=True)
        cmd += ["--chat-template", container_tpl]

    log(f"Starting vLLM on {'SSH:' + _ssh_host if _ssh_host else 'localhost'}: {' '.join(cmd)}")
    _remote(cmd, check=True, sudo=True)


def _container_logs(tail: int | None = None) -> str:
    """Return container stdout+stderr. Pass tail=N to limit; omit for full log."""
    cmd = ["podman", "logs"]
    if tail is not None:
        cmd += ["--tail", str(tail)]
    cmd.append(CONTAINER)
    result = _remote(cmd, sudo=True)
    combined = (result.stdout or "") + (result.stderr or "")
    return combined.strip()


def _container_status() -> str:
    """Return the container's state (running/exited/…), or 'unknown' on failure."""
    result = _remote(
        ["podman", "inspect", "--format", "{{.State.Status}}", CONTAINER], sudo=True
    )
    return result.stdout.strip() if result.returncode == 0 else "unknown"


def wait_for_ready(timeout: int = STARTUP_WAIT) -> tuple[str, float]:
    """
    Poll /v1/models until the model is loaded and serving.
    Returns (model_id, elapsed_seconds).

    Use DOWNLOAD_WAIT when starting locally (model may need to download first).
    Use STARTUP_WAIT when connecting to a remote that should already be loaded.
    """
    t_start = time.time()
    deadline = t_start + timeout
    last_log = t_start

    log(f"Waiting for model (timeout: {timeout}s)...")
    while time.time() < deadline:
        try:
            result = _get("models", timeout=5)
            if isinstance(result, dict) and result.get("data"):
                elapsed = round(time.time() - t_start, 1)
                model_id = result["data"][0]["id"]
                log(f"Model ready after {elapsed}s: {model_id}")
                return model_id, elapsed
        except Exception:
            pass

        # Check if the container exited unexpectedly — no point waiting the full timeout
        # if vLLM crashed on startup (e.g. unsupported quantization, OOM, bad config).
        status = _container_status()
        if status not in ("running", "unknown"):
            elapsed = round(time.time() - t_start, 1)
            # Capture full log: crash containers are short-lived so the log is small.
            logs = _container_logs()
            log(f"  Container exited early (status={status}) after {elapsed}s")
            log(f"  --- container logs (full) ---\n{logs}\n  ---")
            raise TimeoutError(
                f"vLLM container exited (status={status}) after {elapsed}s\n\n"
                f"Container logs:\n{logs}"
            )

        now = time.time()
        if now - last_log >= 30:
            elapsed = round(now - t_start)
            log(f"  Still waiting... ({elapsed}s elapsed, {round(deadline - now)}s remaining)")
            last_log = now

        time.sleep(5)

    # Genuine timeout (model download / slow startup). Log could be large — cap at 200 lines.
    logs = _container_logs(tail=200)
    log(f"  --- container logs on timeout (last 200 lines) ---\n{logs}\n  ---")
    raise TimeoutError(
        f"vLLM not ready after {timeout}s\n\nContainer logs (last 200 lines):\n{logs}"
    )


# ── Prompt builders ────────────────────────────────────────────────────────────


def codegen_messages(problem: dict) -> list[dict]:
    return [{"role": "user", "content": problem["prompt"] + "\n\nReturn only the function code, no explanation."}]


def bugfix_messages_python(problem: dict) -> list[dict]:
    return [{"role": "user", "content": problem["prompt"] + "\n\nReturn only the fixed function code, no explanation."}]


def fim_chat_messages(prefix_code: str, suffix_code: str, language: str) -> list[dict]:
    prompt = (
        f"Complete the following {language} code. "
        f"Output only the missing code that goes in place of the gap, no explanation, no code fences.\n\n"
        f"[CODE BEFORE GAP]\n{prefix_code}\n"
        f"[CODE AFTER GAP]\n{suffix_code}"
    )
    return [{"role": "user", "content": prompt}]


def fim_native_prompt(tokens: dict, prefix_code: str, suffix_code: str) -> str:
    return (
        tokens["prefix"]
        + prefix_code
        + tokens["suffix"]
        + suffix_code
        + tokens["middle"]
    )


# ── Context stress test ────────────────────────────────────────────────────────


def _check_coherence(reply: str) -> tuple[bool, str]:
    """Return (coherent, reason) for a context stress reply."""
    if not reply.strip():
        return False, "empty_response"
    if "ready" not in reply.lower():
        return False, f"wrong_content: {reply[:80]!r}"
    if len(reply) > 500:
        return False, f"excessive_length: {len(reply)} chars"
    # Garbage check: response should be mostly printable ASCII
    printable = sum(c.isprintable() for c in reply)
    if printable / len(reply) < 0.8:
        return False, "garbage_characters"
    return True, "ok"


def test_context_lengths(api_max_model_len: int | None, config_max_model_len: int | None) -> dict:
    """
    Dynamic context stress test up to the model's actual reported ceiling.

    Test levels: 4k, 8k, 16k, 32k — filtered to those within the ceiling.
    The ceiling itself is added as an extra level if not already in the list.
    Each level is independently time-capped at CONTEXT_TEST_TIMEOUT seconds.
    Reports both pass/fail and whether the response was coherent vs garbage.
    """
    # Use the API-reported value as ground truth; fall back to config cap
    ceiling = api_max_model_len or config_max_model_len

    base_levels = [4096, 8192, 16384, 32768]
    levels = [l for l in base_levels if ceiling is None or l <= ceiling]
    # For constrained models (ceiling < 64k) also test at their exact ceiling so we
    # confirm the cap works end-to-end. Skip this for large-context models (≥ 64k)
    # — testing 128k would take far too long to be worth it in a benchmark sweep.
    if ceiling and ceiling not in levels and ceiling < 65536:
        import bisect
        bisect.insort(levels, ceiling)
    if not levels:
        return {"skipped": f"ceiling={ceiling} is below minimum test level"}

    results: dict = {"ceiling": ceiling, "levels": {}}
    filler = "The quick brown fox jumps over the lazy dog. " * 200  # ~2k tokens of padding stock

    for ctx in levels:
        tokens_needed = ctx - 100   # leave headroom for the instruction + response
        chars_needed = max(0, tokens_needed * 4)
        padding = (filler * ((chars_needed // len(filler)) + 2))[:chars_needed]
        prompt = f"Ignore the following text and reply with only the single word READY.\n\n{padding}"

        t0 = time.perf_counter()
        try:
            reply = chat(
                [{"role": "user", "content": prompt}],
                max_tokens=20,
                timeout=CONTEXT_TEST_TIMEOUT,
            )
            elapsed = round(time.perf_counter() - t0, 1)
            coherent, reason = _check_coherence(reply)
            results["levels"][str(ctx)] = {
                "status": "pass" if coherent else "incoherent",
                "coherence_reason": reason,
                "elapsed_s": elapsed,
                "response_snippet": reply[:120],
            }
        except TimeoutError:
            results["levels"][str(ctx)] = {
                "status": "timeout",
                "elapsed_s": CONTEXT_TEST_TIMEOUT,
            }
        except Exception as e:
            results["levels"][str(ctx)] = {
                "status": "error",
                "error": str(e)[:120],
                "elapsed_s": round(time.perf_counter() - t0, 1),
            }

    return results


# ── Track runners ──────────────────────────────────────────────────────────────


def log(msg: str) -> None:
    ts = datetime.now().strftime("%H:%M:%S")
    print(f"[{ts}] {msg}")


def run_track1(cfg: dict) -> dict:
    log("=== Track 1: Code Generation ===")
    results = {"problems": [], "python": {}, "nodejs": {}, "go": {}}

    node_available = (
        subprocess.run(["which", "node"], capture_output=True).returncode == 0
    )
    go_available = subprocess.run(["which", "go"], capture_output=True).returncode == 0

    def score_group(problems, lang, run_fn):
        passed_total, total = 0, 0
        for p in problems:
            log(f"  [{lang}] {p['id']}")
            msgs = codegen_messages(p)
            try:
                response = chat(msgs, max_tokens=512)
            except Exception as e:
                results["problems"].append({"id": p["id"], "error": str(e)})
                continue
            code = extract_code(response, lang)
            p_pass, p_total, lines = run_fn(p, code)
            passed_total += p_pass
            total += p_total
            results["problems"].append(
                {
                    "id": p["id"],
                    "language": lang,
                    "passed": p_pass,
                    "total": p_total,
                    "test_lines": lines,
                    "response_snippet": code[:300],
                }
            )
            log(f"    {p_pass}/{p_total} tests passed")
        return passed_total, total

    py_pass, py_total = score_group(
        TRACK1_PYTHON, "python", lambda p, code: run_python_tests(code, p["test_cases"])
    )
    results["python"] = {
        "passed": py_pass,
        "total": py_total,
        "pass_rate": round(py_pass / py_total, 3) if py_total else 0,
    }

    if node_available:
        js_pass, js_total = score_group(
            TRACK1_NODEJS,
            "javascript",
            lambda p, code: run_node_tests(code, p["test_js"], p["n_tests"]),
        )
    else:
        log("  node not found — skipping NodeJS problems")
        js_pass, js_total = 0, sum(p["n_tests"] for p in TRACK1_NODEJS)
        results["nodejs"]["skipped"] = "node runtime not found"
    results["nodejs"].update(
        {
            "passed": js_pass,
            "total": js_total,
            "pass_rate": round(js_pass / js_total, 3) if js_total else 0,
        }
    )

    if go_available:
        go_pass, go_total = 0, 0
        for p in TRACK1_GO:
            log(f"  [go] {p['id']}")
            msgs = [
                {
                    "role": "user",
                    "content": p["prompt"] + "\n\nReturn only the Go function, no package declaration, no imports.",
                }
            ]
            try:
                response = chat(msgs, max_tokens=512)
            except Exception as e:
                results["problems"].append({"id": p["id"], "error": str(e)})
                continue
            fn_code = extract_go_function(response, p["func_name"])
            p_pass, p_total, lines = run_go_tests(
                fn_code, p["imports"], p["test_main"], p["n_tests"]
            )
            go_pass += p_pass
            go_total += p_total
            results["problems"].append(
                {
                    "id": p["id"],
                    "language": "go",
                    "passed": p_pass,
                    "total": p_total,
                    "test_lines": lines,
                    "response_snippet": fn_code[:300],
                }
            )
            log(f"    {p_pass}/{p_total} tests passed")
    else:
        log("  go not found — skipping Go problems")
        go_pass, go_total = 0, sum(p["n_tests"] for p in TRACK1_GO)
        results["go"]["skipped"] = "go runtime not found"
    results["go"].update(
        {
            "passed": go_pass,
            "total": go_total,
            "pass_rate": round(go_pass / go_total, 3) if go_total else 0,
        }
    )

    all_pass = py_pass + js_pass + go_pass
    all_total = py_total + js_total + go_total
    results["total_passed"] = all_pass
    results["total"] = all_total
    results["pass_rate"] = round(all_pass / all_total, 3) if all_total else 0
    log(f"Track 1 total: {all_pass}/{all_total} ({results['pass_rate']:.1%})")
    return results


def run_track2(cfg: dict) -> dict:
    log("=== Track 2: Bug Fixing ===")
    results = {"problems": [], "python": {}, "nodejs": {}, "go": {}}

    node_available = (
        subprocess.run(["which", "node"], capture_output=True).returncode == 0
    )
    go_available = subprocess.run(["which", "go"], capture_output=True).returncode == 0

    # Python
    py_pass, py_total = 0, 0
    for p in TRACK2_PYTHON:
        log(f"  [python] {p['id']}")
        msgs = bugfix_messages_python(p)
        try:
            response = chat(msgs, max_tokens=512)
        except Exception as e:
            results["problems"].append({"id": p["id"], "error": str(e)})
            continue
        code = extract_code(response, "python")
        p_pass, p_total, lines = run_python_tests(code, p["test_cases"])
        py_pass += p_pass
        py_total += p_total
        results["problems"].append(
            {
                "id": p["id"],
                "language": "python",
                "passed": p_pass,
                "total": p_total,
                "test_lines": lines,
            }
        )
        log(f"    {p_pass}/{p_total}")
    results["python"] = {
        "passed": py_pass,
        "total": py_total,
        "pass_rate": round(py_pass / py_total, 3) if py_total else 0,
    }

    # NodeJS
    js_pass, js_total = 0, 0
    if node_available:
        for p in TRACK2_NODEJS:
            log(f"  [js] {p['id']}")
            msgs = [
                {
                    "role": "user",
                    "content": p["prompt"] + "\n\nReturn only the fixed JavaScript function code, no explanation.",
                }
            ]
            try:
                response = chat(msgs, max_tokens=512)
            except Exception as e:
                results["problems"].append({"id": p["id"], "error": str(e)})
                continue
            code = extract_code(response, "javascript")
            p_pass, p_total, lines = run_node_tests(code, p["test_js"], p["n_tests"])
            js_pass += p_pass
            js_total += p_total
            results["problems"].append(
                {
                    "id": p["id"],
                    "language": "javascript",
                    "passed": p_pass,
                    "total": p_total,
                    "test_lines": lines,
                }
            )
            log(f"    {p_pass}/{p_total}")
    else:
        js_total = sum(p["n_tests"] for p in TRACK2_NODEJS)
        results["nodejs"]["skipped"] = "node runtime not found"
    results["nodejs"].update(
        {
            "passed": js_pass,
            "total": js_total,
            "pass_rate": round(js_pass / js_total, 3) if js_total else 0,
        }
    )

    # Go
    go_pass, go_total = 0, 0
    if go_available:
        for p in TRACK2_GO:
            log(f"  [go] {p['id']}")
            msgs = [
                {
                    "role": "user",
                    "content": p["prompt"] + "\n\nReturn only the fixed Go function, no package declaration, no imports.",
                }
            ]
            try:
                response = chat(msgs, max_tokens=512)
            except Exception as e:
                results["problems"].append({"id": p["id"], "error": str(e)})
                continue
            fn_code = extract_go_function(response, p["func_name"])
            p_pass, p_total, lines = run_go_tests(
                fn_code, p["imports"], p["test_main"], p["n_tests"]
            )
            go_pass += p_pass
            go_total += p_total
            results["problems"].append(
                {
                    "id": p["id"],
                    "language": "go",
                    "passed": p_pass,
                    "total": p_total,
                    "test_lines": lines,
                }
            )
            log(f"    {p_pass}/{p_total}")
    else:
        go_total = sum(p["n_tests"] for p in TRACK2_GO)
        results["go"]["skipped"] = "go runtime not found"
    results["go"].update(
        {
            "passed": go_pass,
            "total": go_total,
            "pass_rate": round(go_pass / go_total, 3) if go_total else 0,
        }
    )

    # Refactoring — correctness automated, quality reviewed manually
    refactor_pass, refactor_total = 0, 0
    for p in TRACK2_REFACTOR_PYTHON:
        log(f"  [refactor/python] {p['id']}")
        msgs = bugfix_messages_python(p)
        try:
            response = chat(msgs, max_tokens=512)
        except Exception as e:
            results["problems"].append({"id": p["id"], "error": str(e)})
            continue
        code = extract_code(response, "python")
        p_pass, p_total, lines = run_python_tests(code, p["test_cases"])
        refactor_pass += p_pass
        refactor_total += p_total
        results["problems"].append(
            {"id": p["id"], "language": "python", "track": "refactoring",
             "passed": p_pass, "total": p_total, "test_lines": lines,
             "response_snippet": response[:200]}
        )
        log(f"    {p_pass}/{p_total}")

    if node_available:
        for p in TRACK2_REFACTOR_NODEJS:
            log(f"  [refactor/js] {p['id']}")
            msgs = [{"role": "user", "content": p["prompt"] + "\n\nReturn only the refactored JavaScript function, no explanation."}]
            try:
                response = chat(msgs, max_tokens=512)
            except Exception as e:
                results["problems"].append({"id": p["id"], "error": str(e)})
                continue
            code = extract_code(response, "javascript")
            p_pass, p_total, lines = run_node_tests(code, p["test_js"], p["n_tests"])
            refactor_pass += p_pass
            refactor_total += p_total
            results["problems"].append(
                {"id": p["id"], "language": "javascript", "track": "refactoring",
                 "passed": p_pass, "total": p_total, "test_lines": lines,
                 "response_snippet": response[:200]}
            )
            log(f"    {p_pass}/{p_total}")
    else:
        refactor_total += sum(p["n_tests"] for p in TRACK2_REFACTOR_NODEJS)

    results["refactoring"] = {
        "passed": refactor_pass,
        "total": refactor_total,
        "pass_rate": round(refactor_pass / refactor_total, 3) if refactor_total else 0,
        "note": "correctness automated; code quality requires manual review",
    }

    all_pass = py_pass + js_pass + go_pass + refactor_pass
    all_total = py_total + js_total + go_total + refactor_total
    results["total_passed"] = all_pass
    results["total"] = all_total
    results["pass_rate"] = round(all_pass / all_total, 3) if all_total else 0
    log(f"Track 2 total: {all_pass}/{all_total} ({results['pass_rate']:.1%})")
    return results


def run_track3(cfg: dict) -> dict:
    log("=== Track 3: Fill-in-the-Middle ===")
    fim_tokens = cfg.get("fim_tokens")
    results = {"problems": [], "fim_native": fim_tokens is not None}

    node_available = (
        subprocess.run(["which", "node"], capture_output=True).returncode == 0
    )
    go_available = subprocess.run(["which", "go"], capture_output=True).returncode == 0

    total_pass, total_tests = 0, 0

    # Python FIM
    for p in TRACK3_PYTHON:
        log(f"  [python] {p['id']}")
        if fim_tokens:
            raw = complete(
                fim_native_prompt(fim_tokens, p["prefix"], p["suffix"]), max_tokens=200
            )
            middle = raw.strip()
        else:
            msgs = fim_chat_messages(
                p["prefix"], p["suffix"], "Python"
            )
            middle = chat(msgs, max_tokens=200).strip()
            middle = extract_code(middle, "python") if "```" in middle else middle

        # Assemble and run
        assembled = p["run_template"].replace("{FILL}", middle, 1)
        p_pass, _, lines = run_python_fim(assembled, p["expected_output"])
        total_pass += p_pass
        total_tests += 1
        results["problems"].append(
            {
                "id": p["id"],
                "language": "python",
                "passed": p_pass == 1,
                "detail": lines,
                "middle": middle[:200],
            }
        )
        log(f"    {'PASS' if p_pass else 'FAIL'}: {lines}")

    # NodeJS FIM
    for p in TRACK3_NODEJS:
        log(f"  [js] {p['id']}")
        if not node_available:
            results["problems"].append({"id": p["id"], "skipped": "node not found"})
            total_tests += 1
            continue
        if fim_tokens:
            raw = complete(
                fim_native_prompt(fim_tokens, p["prefix"], p["suffix"]), max_tokens=200
            )
            middle = raw.strip()
        else:
            msgs = fim_chat_messages(
                p["prefix"], p["suffix"], "JavaScript"
            )
            middle = chat(msgs, max_tokens=200).strip()
            middle = extract_code(middle, "javascript") if "```" in middle else middle

        assembled = p["run_template"].replace("{FILL}", middle, 1)
        p_pass, _, lines = run_node_fim(assembled, p["expected_output"])
        total_pass += p_pass
        total_tests += 1
        results["problems"].append(
            {
                "id": p["id"],
                "language": "javascript",
                "passed": p_pass == 1,
                "detail": lines,
                "middle": middle[:200],
            }
        )
        log(f"    {'PASS' if p_pass else 'FAIL'}: {lines}")

    # Go FIM
    for p in TRACK3_GO:
        log(f"  [go] {p['id']}")
        if not go_available:
            results["problems"].append({"id": p["id"], "skipped": "go not found"})
            total_tests += 1
            continue
        if fim_tokens:
            raw = complete(
                fim_native_prompt(fim_tokens, p["prefix"], p["suffix"]), max_tokens=200
            )
            middle = raw.strip()
        else:
            msgs = fim_chat_messages(
                p["prefix"], p["suffix"], "Go"
            )
            middle = chat(msgs, max_tokens=200).strip()
            middle = extract_code(middle, "go") if "```" in middle else middle

        full_program = p["run_template"].replace("{FILL}", middle, 1)
        p_pass, _, lines = run_go_program(full_program, p["expected_output"])
        total_pass += p_pass
        total_tests += 1
        results["problems"].append(
            {
                "id": p["id"],
                "language": "go",
                "passed": p_pass == 1,
                "detail": lines,
                "middle": middle[:200],
            }
        )
        log(f"    {'PASS' if p_pass else 'FAIL'}: {lines}")

    results["total_passed"] = total_pass
    results["total"] = total_tests
    results["pass_rate"] = round(total_pass / total_tests, 3) if total_tests else 0
    log(f"Track 3 total: {total_pass}/{total_tests} ({results['pass_rate']:.1%})")
    return results


def run_performance(cfg: dict, api_max_model_len: int | None = None) -> dict:
    log("=== Performance Measurements ===")
    results = {}

    # TTFT: 5 samples with a short coding prompt
    log("  Measuring TTFT (5 samples)...")
    ttft_prompt = "Write a Python function that returns the nth Fibonacci number."
    ttft_samples = []
    for i in range(5):
        try:
            t = measure_ttft(ttft_prompt)
            ttft_samples.append(round(t * 1000, 1))
            log(f"    sample {i+1}: {ttft_samples[-1]} ms")
        except Exception as e:
            log(f"    sample {i+1}: error — {e}")
    if ttft_samples:
        s = sorted(ttft_samples)
        results["ttft_ms"] = {
            "samples": ttft_samples,
            "min": s[0],
            "max": s[-1],
            "mean": round(sum(s) / len(s), 1),
            "p50": s[len(s) // 2],
            "p95": s[int(len(s) * 0.95)],
        }

    # Throughput: timed batch of requests, splitting total tokens from answer-only tokens.
    # Reasoning models generate thinking tokens that don't appear in the response — measuring
    # only completion tokens would make them look slower than they are for actual output.
    # We track both so the comparison is fair across model types.
    log("  Measuring throughput (5 timed requests)...")
    tput_prompt = [{"role": "user", "content": "Write a Python hello world function."}]
    total_tokens_all = 0
    completion_tokens_all = 0
    reasoning_tokens_all = 0
    tput_wall = 0.0
    tput_requests = 0
    for _ in range(5):
        try:
            t0 = time.time()
            _, usage = chat_with_usage(tput_prompt, max_tokens=200)
            elapsed = time.time() - t0
            tput_wall += elapsed
            tput_requests += 1
            # completion_tokens = answer tokens only (thinking stripped by vLLM reasoning-parser)
            # total_tokens = prompt + completion (no thinking — vLLM strips before reporting)
            # reasoning_tokens_details may be present if vLLM exposes it
            ct = usage.get("completion_tokens", 0)
            tt = usage.get("total_tokens", 0)
            rt = (usage.get("completion_tokens_details") or {}).get("reasoning_tokens", 0)
            completion_tokens_all += ct
            total_tokens_all += tt
            reasoning_tokens_all += rt
        except Exception:
            pass
    if tput_requests > 0 and tput_wall > 0:
        answer_tps = round(completion_tokens_all / tput_wall, 2)
        total_tps  = round(total_tokens_all / tput_wall, 2)
        results["throughput"] = {
            "answer_toks_per_sec": answer_tps,
            "total_toks_per_sec": total_tps,
            "reasoning_tokens_observed": reasoning_tokens_all,
            "requests": tput_requests,
            "wall_seconds": round(tput_wall, 2),
            "note": (
                "answer_toks_per_sec counts only visible completion tokens; "
                "total_toks_per_sec includes all tokens vLLM reports (prompt+completion); "
                "reasoning tokens are stripped by vLLM before reporting so this figure "
                "understates true GPU work for reasoning models"
            ),
        }
        log(f"  throughput: {answer_tps} answer tok/s  |  {total_tps} total tok/s"
            + (f"  (reasoning_tokens: {reasoning_tokens_all})" if reasoning_tokens_all else ""))
    else:
        results["throughput"] = None
        log("  throughput: measurement failed")

    # Also snapshot vLLM's own rolling metric for reference
    time.sleep(2)
    metrics = get_vllm_metrics()
    results["vllm_metrics_snapshot"] = metrics
    results["throughput_toks_per_sec"] = None  # deprecated field; use results["throughput"]

    # Context stress
    log("  Context stress test...")
    results["context_stress"] = test_context_lengths(api_max_model_len, cfg.get("max_model_len"))
    for ctx, level in results["context_stress"].get("levels", {}).items():
        log(f"    {ctx} tokens: {level['status']} ({level.get('elapsed_s', '?')}s)")

    return results


# ── evalplus (HumanEval+) ──────────────────────────────────────────────────────


def run_evalplus(model_id: str, cfg: dict) -> dict:
    """
    Run HumanEval+ via evalplus.
    Reasoning models use temp=0 (greedy) — they are optimized for it and sampling
    at temp>0 with thinking enabled degrades output quality.
    Non-reasoning models use EVALPLUS_TEMP (0.2) with n=EVALPLUS_N samples for pass@1.

    Requires: pip install evalplus
    """
    import glob as _glob
    import shutil

    log("=== evalplus: HumanEval+ ===")

    is_reasoning = cfg.get("is_reasoning", False)
    # Reasoning models: near-greedy (temp=0.001), single sample.
    # evalplus openai provider asserts temperature > 0, so 0.0 is not allowed.
    # At n=1, 0.001 is functionally identical to greedy.
    # Non-reasoning models: temp sampling, n=EVALPLUS_N for pass@1 estimate
    evalplus_temp = 0.001 if is_reasoning else EVALPLUS_TEMP
    evalplus_n    = 1     if is_reasoning else EVALPLUS_N
    log(f"  mode: {'reasoning → temp=0.001, n=1' if is_reasoning else f'sampling → temp={evalplus_temp}, n={evalplus_n}'}")

    if not shutil.which("evalplus") and not any(
        shutil.which(p) for p in ["python3", "python"]
        if subprocess.run(
            [p, "-c", "import evalplus"], capture_output=True
        ).returncode == 0
    ):
        log("  evalplus not installed — skipping (pip install evalplus)")
        return {"error": "evalplus not installed"}

    # evalplus openai backend passes base_url directly to the openai SDK,
    # which appends endpoint paths without adding /v1 — so we must include it.
    from urllib.parse import urlparse
    parsed = urlparse(_api_url)
    base_url = f"{parsed.scheme}://{parsed.netloc}/v1"

    # evalplus writes to evalplus_results/humaneval/ relative to cwd — --output is not
    # a valid flag and causes fire CLI to crash after codegen completes. Run from poc dir.
    poc_dir = os.path.dirname(os.path.abspath(__file__))
    evalplus_out_dir = os.path.join(poc_dir, "evalplus_results", "humaneval")

    # ── Step 1: generate samples ───────────────────────────────────────────────
    t0 = time.time()

    if is_reasoning:
        # evalplus hardcodes max_new_tokens=768 with no CLI override. Thinking models
        # consume 2000–4000+ tokens in the <think> block before producing any code,
        # so the default silently truncates every response mid-thought and produces
        # no evaluable output. We call the Python API directly and monkey-patch
        # DecoderBase to raise the budget high enough to complete both thinking and code.
        # 4096 wasn't enough for qwen3-30b on some HumanEval problems — vLLM returned
        # null content after the budget was consumed by reasoning, crashing evalplus
        # with NoneType.split. 8192 matches the bench-track headroom (512 + _thinking_budget).
        REASONING_MAX_TOKENS = 8192
        log(f"  Generating {evalplus_n} samples per problem (temp={evalplus_temp}, "
            f"max_tokens={REASONING_MAX_TOKENS} for thinking model)...")
        try:
            from evalplus.provider import base as _ep_base
            from evalplus.provider import openai as _ep_openai
            from evalplus.codegen import run_codegen as _run_codegen
        except ImportError:
            log("  evalplus not installed — skipping (pip install evalplus)")
            return {"error": "evalplus not installed"}

        # DecoderBase.__init__ signature (excluding self and name which have no default):
        #   batch_size=1, temperature=0.8, max_new_tokens=768, dtype="bfloat16",
        #   trust_remote_code=False, instruction_prefix=None, response_prefix=None
        # max_new_tokens is index 2 in __defaults__.
        _orig_defaults = _ep_base.DecoderBase.__init__.__defaults__
        patched = list(_orig_defaults)
        patched[2] = REASONING_MAX_TOKENS
        _ep_base.DecoderBase.__init__.__defaults__ = tuple(patched)

        # Wrap OpenAIChatDecoder.codegen so None content (vLLM reasoning-parser strips
        # unfinished <think> blocks) becomes "" instead of crashing downstream .split().
        # Even at 8192 max_tokens, some HumanEval problems exhaust the budget on thinking.
        _orig_codegen = _ep_openai.OpenAIChatDecoder.codegen
        def _safe_codegen(self, *a, **kw):
            return [(o if isinstance(o, str) else "") for o in _orig_codegen(self, *a, **kw)]
        _ep_openai.OpenAIChatDecoder.codegen = _safe_codegen

        try:
            samples_file = _run_codegen(
                model=model_id,
                dataset="humaneval",
                backend="openai",
                n_samples=evalplus_n,
                temperature=evalplus_temp,
                base_url=base_url,
                root=os.path.join(poc_dir, "evalplus_results"),
                resume=False,  # prior runs produced truncated results; always regenerate
            )
        except Exception as exc:
            log(f"  codegen failed: {exc}")
            return {"error": f"codegen failed: {exc}"}
        finally:
            _ep_base.DecoderBase.__init__.__defaults__ = _orig_defaults
            _ep_openai.OpenAIChatDecoder.codegen = _orig_codegen

        gen_duration = round(time.time() - t0, 1)
        log(f"  Codegen complete in {gen_duration}s → {samples_file}")
    else:
        codegen_cmd = [
            sys.executable, "-m", "evalplus.codegen",
            "--model", model_id,
            "--dataset", "humaneval",
            "--backend", "openai",
            "--base-url", base_url,
            "--n-samples", str(evalplus_n),
            "--temperature", str(evalplus_temp),
        ]
        log(f"  Generating {evalplus_n} samples per problem (temp={evalplus_temp})...")
        log(f"  cmd: {' '.join(codegen_cmd)}")

        gen_result = subprocess.run(
            codegen_cmd, capture_output=True, text=True, timeout=7200, cwd=poc_dir
        )
        gen_duration = round(time.time() - t0, 1)

        if gen_result.returncode != 0:
            log(f"  codegen failed (rc={gen_result.returncode})")
            return {
                "error": "codegen failed",
                "stderr": gen_result.stderr[-2000:],
                "stdout": gen_result.stdout[-1000:],
            }

        # evalplus names files: {model_id_with_/→--}_openai_temp_{temp}.jsonl
        safe_model = model_id.replace("/", "--")
        expected = os.path.join(evalplus_out_dir, f"{safe_model}_openai_temp_{evalplus_temp}.jsonl")
        if os.path.exists(expected):
            samples_file = expected
        else:
            # Fallback: find any matching jsonl (handles minor naming variations)
            candidates = _glob.glob(os.path.join(evalplus_out_dir, f"{safe_model}*.jsonl"))
            candidates = [c for c in candidates if ".raw." not in c]
            if not candidates:
                log("  No .jsonl file found after codegen")
                return {"error": "samples.jsonl not found after codegen",
                        "stdout": gen_result.stdout[-500:]}
            samples_file = sorted(candidates)[-1]
        log(f"  Samples written to: {samples_file}")

    # ── Step 2: evaluate ───────────────────────────────────────────────────────
    eval_cmd = [
        sys.executable, "-m", "evalplus.evaluate",
        "--dataset", "humaneval",
        "--samples", samples_file,
    ]
    log("  Evaluating samples...")
    eval_result = subprocess.run(eval_cmd, capture_output=True, text=True, timeout=3600)
    combined = eval_result.stdout + eval_result.stderr

    # Parse pass@k. evalplus prints the label and score on separate lines:
    #   humaneval (base tests)
    #   pass@1:\t0.869
    #   humaneval+ (base + extra tests)
    #   pass@1:\t0.826
    # Track the most recent label line, then attach it to the next pass@k line.
    scores: dict[str, float] = {}
    last_label = None
    for line in combined.splitlines():
        ls = line.strip()
        lbl = re.search(r"\((base\s*\+?\s*extra\s*tests?|base\s*tests?)\)", ls, re.IGNORECASE)
        if lbl:
            last_label = "base_plus_extra" if "extra" in lbl.group(1).lower() else "base"
            continue
        m = re.match(r"pass@(\d+)\s*:?\s*([\d.]+)", ls, re.IGNORECASE)
        if m and last_label:
            k, val = m.group(1), float(m.group(2))
            key = f"pass_at_{k}_{last_label}"
            scores[key] = val
            log(f"  {key}: {val:.3f}")

    return {
        "dataset": "humaneval",
        "n_samples": evalplus_n,
        "temperature": evalplus_temp,
        "scores": scores,
        "samples_file": samples_file,
        "codegen_duration_seconds": gen_duration,
        "raw_output_tail": combined[-2000:],
    }


# ── Weighted score ─────────────────────────────────────────────────────────────


def compute_weighted_score(t1: dict, t2: dict, t3: dict, perf: dict) -> dict:
    """Phase 1 scoring weights from coding-models-evaluation.md."""
    scores = {
        "codegen_pass_rate": t1.get("pass_rate", 0),  # 30%
        "bugfix_pass_rate": t2.get("pass_rate", 0),  # 25%
        "fim_pass_rate": t3.get("pass_rate", 0),  # 15%
        "throughput_normalized": 0,  # 15% — normalized later vs other models
    }
    # Partial weighted score (excludes throughput normalization and manual refactoring)
    weighted = (
        scores["codegen_pass_rate"] * 0.30
        + scores["bugfix_pass_rate"] * 0.25
        + scores["fim_pass_rate"] * 0.15
    )
    return {
        "component_scores": scores,
        "partial_weighted_score": round(weighted, 3),
        "note": "throughput_normalized and refactoring_quality require cross-model comparison",
    }


# ── Main ───────────────────────────────────────────────────────────────────────


def main() -> None:
    global _current_model_id, _api_url, _ssh_host, _thinking_budget

    parser = argparse.ArgumentParser(
        description="Phase 1 coding model benchmark harness"
    )
    parser.add_argument("model_key", help="Model key from MODEL_CONFIGS")
    parser.add_argument(
        "--api-url",
        default=DEFAULT_API_URL,
        help=f"vLLM API base URL (default: {DEFAULT_API_URL})",
    )
    parser.add_argument(
        "--tracks",
        default="perf,track1,track2,track3",
        help="Comma-separated tracks to run (default: all). evalplus is opt-in via --evalplus.",
    )
    parser.add_argument(
        "--evalplus",
        action="store_true",
        help="Also run HumanEval+ via evalplus (n=5, temp=0.2). Requires: pip install evalplus",
    )
    parser.add_argument(
        "--ssh-host",
        default="",
        help="SSH target for remote lifecycle commands (e.g. drewburr@airunner01.drewburr.com). "
             "Required to start/stop vLLM on ai-runner from this machine.",
    )
    parser.add_argument(
        "--no-start",
        action="store_true",
        default=False,
        help="Skip vLLM container startup (use if model is already running)",
    )
    parser.add_argument(
        "--no-stop",
        action="store_true",
        default=False,
        help="Skip vLLM container shutdown after benchmarking",
    )
    parser.add_argument(
        "--no-stop-prod",
        action="store_true",
        help="Do not stop production vllm-1/litellm services before starting bench container",
    )
    parser.add_argument(
        "--restart-prod",
        action="store_true",
        help="Restart production services after benchmarking",
    )
    args = parser.parse_args()

    _ssh_host = args.ssh_host

    if args.model_key not in MODEL_CONFIGS:
        print(f"Unknown model key: {args.model_key!r}")
        print(f"Available: {', '.join(MODEL_CONFIGS)}")
        sys.exit(1)

    cfg = MODEL_CONFIGS[args.model_key]
    _api_url = args.api_url
    # Reasoning models think before answering; the thinking tokens consume max_tokens budget
    # before any visible content is produced. 2048 was insufficient — qwen3-30b regularly
    # spent >2500 tokens reasoning on standard codegen prompts, exhausting the budget and
    # leaving message.content=null after the parser stripped the unfinished <think>. 6144
    # gives margin over the worst case observed in qwen3 probes (3312 completion tokens).
    _thinking_budget = 6144 if cfg.get("is_reasoning") else 0
    tracks = [t.strip() for t in args.tracks.split(",")]
    os.makedirs(RESULTS_DIR, exist_ok=True)
    output_path = os.path.join(RESULTS_DIR, f"{args.model_key}.json")

    log(f"Benchmarking: {args.model_key} ({cfg['hf_id']})")
    log(f"API URL:  {_api_url}")
    log(f"SSH host: {_ssh_host or '(none — lifecycle commands run locally)'}")
    log(f"Tracks:   {tracks}" + (" + evalplus" if args.evalplus else ""))
    log(f"Output:   {output_path}")

    t_start = time.time()
    record: dict = {
        "meta": {
            "model_key": args.model_key,
            "hf_id": cfg["hf_id"],
            "quantization": cfg.get("quantization"),
            "max_model_len_config": cfg.get("max_model_len"),
            "is_reasoning": cfg.get("is_reasoning", False),
            "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        },
        "hardware_baseline": get_gpu_stats(),
    }

    try:
        # ── Start vLLM ─────────────────────────────────────────────────────────
        if not args.no_start:
            if not args.no_stop_prod:
                stop_prod_services()
            start_vllm(cfg)
        # Always allow full download time — model may not be cached on the remote yet
        ready_timeout = DOWNLOAD_WAIT

        model_id, startup_seconds = wait_for_ready(ready_timeout)
        _current_model_id = model_id
        record["model_info"] = {
            "reported_model_id": model_id,
            "startup_seconds": startup_seconds,
        }

        # ── VRAM at load ────────────────────────────────────────────────────────
        log("Sampling VRAM after model load...")
        time.sleep(3)
        record["hardware_at_load"] = get_gpu_stats()

        # ── Model metadata from API ─────────────────────────────────────────────
        try:
            models_resp = _get("models")
            if isinstance(models_resp, dict) and models_resp.get("data"):
                m = models_resp["data"][0]
                # api_max_model_len: what vLLM actually loaded the model with
                # (may be lower than the model's trained max due to --max-model-len cap or VRAM)
                record["model_info"]["api_max_model_len"] = m.get("max_model_len")
                record["model_info"]["api_context_window"] = (
                    m.get("context_window") or m.get("max_model_len")
                )
        except Exception:
            pass

        # ── Tracks ─────────────────────────────────────────────────────────────
        api_max_model_len = record.get("model_info", {}).get("api_max_model_len")

        if "perf" in tracks:
            record["performance"] = run_performance(cfg, api_max_model_len)

        if "track1" in tracks:
            record["track1_codegen"] = run_track1(cfg)
            record["hardware_after_track1"] = get_gpu_stats()

        if "track2" in tracks:
            record["track2_bugfix"] = run_track2(cfg)

        if "track3" in tracks:
            record["track3_fim"] = run_track3(cfg)

        # ── evalplus ───────────────────────────────────────────────────────────
        if args.evalplus:
            record["evalplus"] = run_evalplus(_current_model_id, cfg)

        # ── Weighted score ─────────────────────────────────────────────────────
        if all(t in tracks for t in ("track1", "track2", "track3")):
            record["phase1_score"] = compute_weighted_score(
                record.get("track1_codegen", {}),
                record.get("track2_bugfix", {}),
                record.get("track3_fim", {}),
                record.get("performance", {}),
            )

    except KeyboardInterrupt:
        log("Interrupted — saving partial results")
    except Exception as e:
        log(f"ERROR: {e}")
        record["error"] = str(e)
        import traceback

        record["traceback"] = traceback.format_exc()
    finally:
        record["meta"]["duration_seconds"] = round(time.time() - t_start, 1)
        record["hardware_final"] = get_gpu_stats()

        if not args.no_stop:
            log("Stopping benchmark container...")
            stop_container(CONTAINER)

        if args.restart_prod:
            restart_prod_services()

        with open(output_path, "w") as f:
            json.dump(record, f, indent=2)
        log(f"Results written to: {output_path}")

        # Print summary
        print("\n── Summary ──────────────────────────────────────")
        if "track1_codegen" in record:
            t1 = record["track1_codegen"]
            print(
                f"Track 1 (codegen):  {t1['total_passed']}/{t1['total']}  ({t1['pass_rate']:.1%})"
            )
        if "track2_bugfix" in record:
            t2 = record["track2_bugfix"]
            print(
                f"Track 2 (bugfix):   {t2['total_passed']}/{t2['total']}  ({t2['pass_rate']:.1%})"
            )
        if "track3_fim" in record:
            t3 = record["track3_fim"]
            print(
                f"Track 3 (FIM):      {t3['total_passed']}/{t3['total']}  ({t3['pass_rate']:.1%})"
            )
        if "performance" in record:
            p = record["performance"]
            ttft = p.get("ttft_ms", {})
            tput = p.get("throughput") or {}
            print(f"TTFT p50:           {ttft.get('p50', 'n/a')} ms")
            print(f"Throughput (ans):   {tput.get('answer_toks_per_sec', 'n/a')} tok/s")
            print(f"Throughput (total): {tput.get('total_toks_per_sec', 'n/a')} tok/s")
        if "phase1_score" in record:
            print(
                f"Weighted score:     {record['phase1_score']['partial_weighted_score']:.3f}"
            )
        if "evalplus" in record:
            ep = record["evalplus"]
            scores = ep.get("scores", {})
            base     = scores.get("pass_at_1_base",            "n/a")
            extended = scores.get("pass_at_1_base_plus_extra", "n/a")
            base_str     = f"{base:.3f}"     if isinstance(base, float)     else base
            extended_str = f"{extended:.3f}" if isinstance(extended, float) else extended
            print(f"HumanEval+ base:    {base_str}")
            print(f"HumanEval+ extra:   {extended_str}")
        print(f"Output:             {output_path}")


if __name__ == "__main__":
    main()
