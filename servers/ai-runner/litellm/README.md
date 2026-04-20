# LiteLLM Proxy (airunner01)

LiteLLM runs as a podman container on airunner01 (managed by `litellm.service`) and fronts the vLLM backend on port 8001, exposing a unified OpenAI-compatible endpoint on port 8000.

## Files

- `fix_tool_messages.py` — custom LiteLLM callback bundling three fixes that the bare vLLM + OpenAI surface does not handle. Mounted into the container at `/app/fix_tool_messages.py` and referenced in `config.yaml` as `callbacks: ["fix_tool_messages.tool_message_fixer"]`.

## Deploy path

Canonical location on airunner01: `/etc/litellm/fix_tool_messages.py`.

```
sudo cp fix_tool_messages.py /etc/litellm/fix_tool_messages.py
sudo chmod 644 /etc/litellm/fix_tool_messages.py
sudo systemctl restart litellm
```

Prior versions on the host are backed up as `.bak.<timestamp>` in the same directory by convention.

## What the callback does

### 1. Mistral message-ordering shim (`async_pre_call_hook`)

Some models reject the `tool → user` role transition that can occur in tool-heavy conversations. When the shim sees that pattern in the incoming `messages` list, it inserts a synthetic empty assistant turn so the ordering becomes `tool → assistant → user`.

### 2. Qwen/Hermes tool-call extraction (`_extract_tool_calls`)

Qwen2.5-Coder-AWQ is unreliable about the wrapping of its tool calls. Observed variants: `<tools>…</tools>` (wrong tag), bare JSON, Python-literal dicts (single-quoted keys), and markdown code fences. The callback rewrites any of these into proper OpenAI `tool_calls` on the assistant message and strips the raw text from `content`, so downstream agents see a clean `tool_calls` array.

Parse order:

1. `<tool_call>…</tool_call>` (canonical hermes)
2. `<tools>…</tools>` (Qwen's preferred wrapping)
3. Markdown code fences (````json` /````python`)
4. Bare brace-balanced JSON / Python-literal objects in plain text

Both streaming (`async_post_call_streaming_iterator_hook`) and non-streaming (`async_post_call_success_hook`) paths are handled.

### 3. Repeat-tool-call guard (`_apply_repeat_guard`)

Added 2026-04-19 after a Ralph+Goose run against qwen2.5-coder-32b-AWQ entered a self-feedback loop at long context and fired an identical `pnpm add zod --save` shell command 94 times in 3.5 minutes, spawning enough Node subprocesses to nearly destabilize the host.

**Behavior.** When the model emits a tool call, the callback walks backward through the incoming request's messages and counts consecutive most-recent assistant turns whose single `tool_calls[0]` matches the current one (by name + canonical-JSON arguments). Tool-result turns (`role: "tool"`) are skipped — they sit between an assistant's call and its next turn. Any non-matching assistant turn, user turn, or multi-call assistant message ends the run.

If the count of prior identical calls is `>= LITELLM_REPEAT_THRESHOLD` (default 3 → the 4th identical call is blocked), the callback:

- drops `tool_calls` on the outgoing response,
- sets `content` to a guard message naming the offending tool and the repeat count,
- sets `finish_reason: "stop"`.

Downstream goose sees a plain text turn with no tool call, finishes its turn, and returns control. Ralph's per-phase goose calls use fresh sessions (`--no-session`), so the next iteration starts with no loop history.

**Tuning.** Set `LITELLM_REPEAT_THRESHOLD` env var on the litellm service (via a drop-in unit file or by editing the container command) to adjust. `0` disables the guard entirely.

**What it does not catch.**

- Near-duplicate calls where arguments differ by a single character (e.g., rotating timestamps or counter suffixes). The signature is exact-match on canonicalized arguments.
- Rapidly alternating A-B-A-B patterns (the walk-back stops at the first non-matching turn).
- Genuine deadlocks where the model produces no tool call at all — that's a different failure mode, handled by the agent host's own timeouts.

## Operational notes

- The callback emits a `[fix_tool_messages] repeat-guard fired: …` line to stdout when it triggers. That line shows up in `podman logs litellm` and in the journal — grep for it to spot loop incidents.
- `fix_tool_messages.py` must match the host copy byte-for-byte to avoid surprises. After editing this file, always scp/rsync to airunner01 and restart the litellm service.
- Unit tests: see the inline guard logic in the module docstring. Smoke-test locally with the stubs pattern (mock the `litellm` import and call `_apply_repeat_guard` directly).
