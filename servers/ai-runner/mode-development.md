# Development Mode

Configuration for agentic software development workloads: code generation, tool use, multi-step reasoning.

> All commands run on `airunner01.drewburr.com`. SSH in first.

---

## Model: Devstral Small 2 (24B)

`mistralai/Devstral-Small-2-24B-Instruct-2512`

| Attribute | Value |
|---|---|
| VRAM at AWQ INT4 | ~15GB (33GB free for KV cache) |
| Context window | 256k tokens |
| SWE-bench Verified | 68% |
| Tool calling | First-class — `--tool-call-parser mistral` |
| vLLM TP=2 | Officially supported |
| Released | December 2025 |

Designed by Mistral specifically for agentic multi-file code tasks. Best SWE-bench score of any model that fits comfortably in 48GB. The low VRAM footprint means the full 256k context is usable without VRAM pressure.

**Why this over alternatives:**
- Qwen2.5-Coder-32B (fallback): 53% SWE-bench, 128k context — good but older
- Qwen3-Coder-Next 80B MoE: #1 on leaderboards but ~46GB at Q4, leaves no room for KV cache at long context on 48GB
- Devstral 2 123B: 72.2% SWE-bench but needs 72GB+ — out of reach

---

## vLLM service config

Replace the `ExecStart` block in `/etc/systemd/system/vllm-1.service`:

```ini
ExecStart=/usr/bin/podman run --name vllm-1 \
  --device nvidia.com/gpu=all \
  --network=host \
  --ipc=host \
  --ulimit memlock=-1 \
  -v /var/lib/vllm/models:/root/.cache/huggingface \
  -v /etc/vllm/mistral_tool_parser.py:/usr/local/lib/python3.12/dist-packages/vllm/tool_parsers/mistral_tool_parser.py:ro \
  docker.io/vllm/vllm-openai:latest \
    --model mistralai/Devstral-Small-2-24B-Instruct-2512 \
    --tensor-parallel-size 2 \
    --max-model-len 116000 \
    --gpu-memory-utilization 0.95 \
    --tool-call-parser mistral \
    --enable-auto-tool-choice \
    --enable-prefix-caching \
    --host 0.0.0.0 \
    --port 8001
```

The extra volume mount patches a vLLM bug in the mistral tool parser (see [Known issues](#known-issues) below).

**Flag notes:**

| Flag | Value | Reason |
|---|---|---|
| `--tensor-parallel-size` | `2` | Both GPUs active per token via NVLink |
| `--max-model-len` | `116000` | 113k context — with 0.95 utilization, ~8.9 GiB KV cache headroom (116,576 token capacity) |
| `--tool-call-parser mistral` | mistral | Required for correct tool call parsing |
| `--enable-auto-tool-choice` | — | Required for tool use to function |
| `--enable-prefix-caching` | — | Cache KV for repeated system prompts |

> **Context ceiling:** With BF16 weights and `gpu_memory_utilization 0.90`, approximately 7.72 GiB remains for KV cache across both GPUs. vLLM estimates the hard max at ~101k tokens; 98304 keeps a small safety margin.

No `--quantization` flag — Devstral Small 2 is served in BF16 by default. The model fits in 48GB without quantization. If you want to load an AWQ variant, add `--quantization awq_marlin`.

---

## LiteLLM config

Two files are required: the config and a callback hook.

### `/etc/litellm/fix_tool_messages.py`

Mistral's validator rejects `user` messages directly after `tool` messages. OpenAI-compatible clients (like Goose) send this pattern in multi-turn conversations. This callback inserts a bridge assistant turn before forwarding to vLLM.

```python
from litellm.integrations.custom_logger import CustomLogger


class ToolMessageFixer(CustomLogger):
    async def async_pre_call_hook(self, user_api_key_dict, cache, data, call_type):
        messages = data.get("messages", [])
        if not messages:
            return data

        fixed = []
        for i, msg in enumerate(messages):
            fixed.append(msg)
            if (
                msg.get("role") == "tool"
                and i + 1 < len(messages)
                and messages[i + 1].get("role") == "user"
            ):
                fixed.append({"role": "assistant", "content": "..."})

        data["messages"] = fixed
        return data


tool_message_fixer = ToolMessageFixer()
```

### `/etc/litellm/config.yaml`

```yaml
model_list:
  - model_name: devstral:24b
    litellm_params:
      model: openai/mistralai/Devstral-Small-2-24B-Instruct-2512
      api_base: http://127.0.0.1:8001/v1
      api_key: none

  - model_name: llama3.2-vision:11b
    litellm_params:
      model: ollama/llama3.2-vision:11b
      api_base: http://127.0.0.1:11434

litellm_settings:
  drop_params: true
  callbacks: ["fix_tool_messages.tool_message_fixer"]

general_settings:
  master_key: none
```

The callback is mounted into the LiteLLM container via the service file (see below).

---

## Switching to development mode

Follow the steps in [model-switching.md](./model-switching.md). Summary:

```sh
# 1. Edit vLLM service (paste ExecStart block above)
sudo nano /etc/systemd/system/vllm-1.service

# 2. Reload and restart vLLM
sudo systemctl daemon-reload
sudo systemctl restart vllm-1

# Watch startup — model download is ~48GB on first run, ~2 min on subsequent starts
sudo journalctl -u vllm-1 -f

# 3. Update LiteLLM config and callback
sudo nano /etc/litellm/config.yaml
sudo nano /etc/litellm/fix_tool_messages.py

# 4. Ensure litellm.service mounts the callback file
# Add this volume to the podman run command in /etc/systemd/system/litellm.service:
#   -v /etc/litellm/fix_tool_messages.py:/app/fix_tool_messages.py:ro
sudo nano /etc/systemd/system/litellm.service
sudo systemctl daemon-reload
sudo systemctl restart litellm
```

Look for `INFO: Application startup complete.` in the vLLM logs before testing.

---

## Verification

```sh
# Services up
systemctl is-active vllm-1 litellm

# Model loaded
curl -s http://localhost:8001/v1/models | python3 -m json.tool

# Tool call smoke test
curl http://localhost:8000/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "devstral:24b",
    "messages": [{"role": "user", "content": "Write a Python function to check if a number is prime."}],
    "max_tokens": 200
  }'
```

---

## Goose CLI

[Goose](https://github.com/block/goose) is a local AI agent CLI. It connects to `devstral:24b` via LiteLLM on port 8000.

### Custom provider config

`~/.config/goose/custom_providers/custom_airunner.json`:

```json
{
  "name": "custom_airunner",
  "engine": "openai",
  "display_name": "airunner",
  "description": "Custom airunner provider",
  "api_key_env": "",
  "base_url": "http://airunner01.drewburr.com:8000/v1",
  "models": [
    {
      "name": "devstral:24b",
      "context_limit": 98304,
      "max_tokens": 32768,
      "input_token_cost": null,
      "output_token_cost": null,
      "currency": null,
      "supports_cache_control": null
    }
  ],
  "headers": null,
  "timeout_seconds": null,
  "supports_streaming": true,
  "requires_auth": false,
  "catalog_provider_id": null,
  "base_path": null,
  "env_vars": null,
  "dynamic_models": null
}
```

### Set as default in `~/.config/goose/config.yaml`

```yaml
GOOSE_PROVIDER: custom_airunner
GOOSE_MODEL: devstral:24b
```

### Verify

```sh
goose run --text "Say hello"
```

Expected output shows `custom_airunner devstral:24b` in the session header.

### Notes

- Goose talks to **LiteLLM on port 8000**, not vLLM directly.
- Port 8000 is open to the LAN (`192.168.4.0/23`) via firewall rich rule.
- `--tool-call-parser mistral` and `--enable-auto-tool-choice` in the vLLM service enable tool use for agentic workflows.

---

## Rollback to previous mode

The model running before development mode was `Qwen/Qwen3-VL-30B-A3B-Instruct-FP8` (`qwen3-vl:30b`).

Key flags to restore:
```
--model Qwen/Qwen3-VL-30B-A3B-Instruct-FP8
--tensor-parallel-size 2
--max-model-len 32768
--gpu-memory-utilization 0.90
--enable-prefix-caching
--trust-remote-code
--tool-call-parser hermes
--enable-auto-tool-choice
```

LiteLLM model name: `qwen3-vl:30b`, `model: openai/Qwen/Qwen3-VL-30B-A3B-Instruct-FP8`.

---

## Known issues

Both issues are specific to Devstral (Mistral model) + vLLM's `--tool-call-parser mistral`. They do not affect other models.

### 1. `user after tool` message ordering (fixed via LiteLLM hook)

Mistral's `mistral_common` validator enforces that after a `tool` message, only `assistant` or another `tool` can follow — not `user`. Goose sends `user` directly after `tool` results in multi-turn conversations, which violates this.

**Fix**: `/etc/litellm/fix_tool_messages.py` — a LiteLLM pre-call hook that inserts a bridge `{"role": "assistant", "content": "..."}` between `tool` and `user` messages before forwarding to vLLM.

### 2. `list index out of range` mid-stream (fixed via parser patch)

vLLM bug in `mistral_tool_parser.py`: the streaming parser sets `prev_tool_call_arr` (needed by `serving.py`) but never sets the paired `streamed_args_for_tool`, causing an `IndexError` on the final chunk of every streaming tool call response.

**Fix**: `/etc/vllm/mistral_tool_parser.py` — a patched copy mounted into the vLLM container. Adds `self.streamed_args_for_tool = [""]` alongside the existing `prev_tool_call_arr` assignment (two locations in the file).

When vLLM releases a fix upstream, remove the volume mount from the service file and delete `/etc/vllm/mistral_tool_parser.py`.
