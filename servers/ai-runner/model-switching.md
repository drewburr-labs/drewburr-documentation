# Model Switching Guide

How to swap or add models in vLLM and LiteLLM on airunner01 without external help.

> All commands run on `airunner01.drewburr.com`. SSH in first.

## Predefined modes

For common workload configurations, see the mode-specific docs rather than configuring from scratch:

| Mode        | Doc                                          | Primary model                     | Use when                               |
| ----------- | -------------------------------------------- | --------------------------------- | -------------------------------------- |
| General     | [vllm-setup.md](./vllm-setup.md)             | `llama3.3:70b` (AWQ)              | General Q&A, summarization, misc tasks |
| Development | [mode-development.md](./mode-development.md) | `devstral:24b` (Devstral Small 2) | Agentic coding, tool use, code agents  |

---

---

## Overview of moving parts

| File                                 | What to change                                  |
| ------------------------------------ | ----------------------------------------------- |
| `/etc/systemd/system/vllm-1.service` | Model, quantization, tensor parallel size, port |
| `/etc/litellm/config.yaml`           | Model name exposed to clients (Open WebUI, API) |

vLLM loads the model. LiteLLM gives it a friendly name. Clients always talk to LiteLLM on `:8000`.

---

## Step 1 — Get the model

### Option A: HuggingFace (automatic on first start)

vLLM downloads the model automatically if it isn't cached. Models are stored at `/var/lib/vllm/models`.

Set the `--model` flag to the HuggingFace repo ID (e.g. `Qwen/Qwen3-VL-30B-A3B-Instruct`). vLLM will pull it on startup.

> For gated models (requires HF token), add `--env HF_TOKEN=hf_...` to the `podman run` command.

### Option B: GGUF from Ollama (avoids HF download, reuses pulled weights)

If you've already pulled a model in Ollama, its GGUF blob is on disk and vLLM can load it directly.

```sh
# Pull the model in Ollama (skip if already pulled)
ollama pull qwen3-vl:30b-a3b-instruct

# Find the GGUF blob path
ollama show --modelfile qwen3-vl:30b-a3b-instruct | grep FROM
# Output: FROM /usr/share/ollama/.ollama/models/blobs/sha256-<hash>
```

Use that path as the `--model` value and add `--tokenizer <hf-repo>` so vLLM can find the tokenizer:

```sh
--model /usr/share/ollama/.ollama/models/blobs/sha256-<hash> \
--tokenizer Qwen/Qwen3-VL-30B-A3B-Instruct \
```

### Option C: Pre-download manually

```sh
sudo mkdir -p /var/lib/vllm/models
sudo podman run --rm \
  -v /var/lib/vllm/models:/root/.cache/huggingface \
  docker.io/vllm/vllm-openai:latest \
  huggingface-cli download Qwen/Qwen3-VL-30B-A3B-Instruct
```

```sh
podman run --name vllm-1 --device nvidia.com/gpu=all --network=host --ipc=host --ulimit memlock=-1 -v /var/lib/vllm/models:/root/.cache/huggingface docker.io/vllm/vllm-openai:latest \
--tensor-parallel-size 2 --enable-auto-tool-choice --enable-prefix-caching --host 127.0.0.1 --port 8001
--max-model-len 98304 --gpu-memory-utilization 0.90 --tool-call-parser mistral --model mistralai/Devstral-Small-2-24B-Instruct-2512
```

```sh
podman run --rm --name vllm-1 --device nvidia.com/gpu=all --network=host --ipc=host --ulimit memlock=-1 \
-v /var/lib/vllm/models:/root/.cache/huggingface docker.io/vllm/vllm-openai:latest \
--tensor-parallel-size 2 --enable-auto-tool-choice --enable-prefix-caching --host 127.0.0.1 --port 8001 \
--max-model-len 50000 --gpu-memory-utilization 0.90 --tool-call-parser hermes --model Qwen/Qwen3-VL-30B-A3B-Instruct
```

---

## Step 2 — Update the vLLM service

Edit the service file:

```sh
sudo nano /etc/systemd/system/vllm-1.service
```

Key flags to change:

| Flag                       | Notes                                                              |
| -------------------------- | ------------------------------------------------------------------ |
| `--model`                  | HF repo ID or absolute GGUF path                                   |
| `--quantization`           | `awq_marlin` (AWQ), `gptq` (GPTQ), omit for FP8/BF16               |
| `--tensor-parallel-size`   | `1` (single GPU) or `2` (both GPUs)                                |
| `--max-model-len`          | Context length; reduce if VRAM is tight                            |
| `--gpu-memory-utilization` | `0.90` default; lower if OOM                                       |
| `--trust-remote-code`      | Add this flag for models that require it (e.g. some Qwen variants) |

### MoE-specific notes (e.g. Qwen3-VL-30B-A3B)

MoE models load all expert weights into VRAM but only compute a subset per token. No special flags needed — vLLM detects the architecture automatically. `--tensor-parallel-size 2` still works.

### Example: switch to Qwen3-VL-30B-A3B

```ini
ExecStart=/usr/bin/podman run --name vllm-1 \
  --device nvidia.com/gpu=all \
  --network=host \
  --ipc=host \
  --ulimit memlock=-1 \
  -v /var/lib/vllm/models:/root/.cache/huggingface \
  docker.io/vllm/vllm-openai:latest \
    --model Qwen/Qwen3-VL-30B-A3B-Instruct \
    --tensor-parallel-size 2 \
    --max-model-len 8192 \
    --gpu-memory-utilization 0.90 \
    --enable-prefix-caching \
    --trust-remote-code \
    --host 0.0.0.0 \
    --port 8001
```

Note: FP8 models don't need `--quantization`. AWQ models need `--quantization awq_marlin`.

---

## Step 3 — Reload and restart

```sh
sudo systemctl daemon-reload
sudo systemctl restart vllm-1

# Watch startup logs — model loading takes 1-5 min depending on size
sudo journalctl -u vllm-1 -f
```

Look for:

```
INFO: Application startup complete.
```

If it crashes, check for OOM (`CUDA out of memory`) or unsupported architecture errors.

---

## Step 4 — Update LiteLLM config

Edit `/etc/litellm/config.yaml` to add or rename the model entry:

```sh
sudo nano /etc/litellm/config.yaml
```

```yaml
model_list:
    - model_name: qwen3-vl:30b # what clients use to call it
      litellm_params:
          model: openai/Qwen/Qwen3-VL-30B-A3B-Instruct # must match --model value in vLLM
          api_base: http://127.0.0.1:8001/v1
          api_key: none

    - model_name: llama3.2-vision:11b
      litellm_params:
          model: ollama/llama3.2-vision:11b
          api_base: http://127.0.0.1:11434

litellm_settings:
    drop_params: true
```

> The `model` field under `litellm_params` must match what vLLM reports at `/v1/models`. Check with:
>
> ```sh
> curl -s http://localhost:8001/v1/models | python3 -m json.tool
> ```

Restart LiteLLM after config changes:

```sh
sudo systemctl restart litellm
```

---

## Step 5 — Verify

```sh
# Services running
systemctl is-active vllm-1 litellm

# Model loaded in vLLM
curl -s http://localhost:8001/v1/models | python3 -m json.tool

# LiteLLM routing (use whatever model_name you set in config.yaml)
curl http://localhost:8000/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{"model":"qwen3-vl:30b","messages":[{"role":"user","content":"Say hello"}],"max_tokens":20}'
```

Open WebUI will pick up the new model automatically after LiteLLM restarts.

---

## Running two models simultaneously

Run a second vLLM instance on a different port with its own service file:

```sh
sudo cp /etc/systemd/system/vllm-1.service /etc/systemd/system/vllm-second.service
sudo nano /etc/systemd/system/vllm-second.service
```

Change:

- `--name vllm-second` (container name)
- `-p 127.0.0.1:8002:8000` (different host port)
- `--model`, `--tensor-parallel-size`, `--device` as needed

Then add a second entry in LiteLLM config pointing to `:8002/v1`.

> **VRAM budget**: check free VRAM before starting a second model.
>
> ```sh
> nvidia-smi --query-gpu=memory.used,memory.free --format=csv
> ```

---

## Rollback

The previous working config for llama3.3:70b:

```ini
--model casperhansen/llama-3.3-70b-instruct-awq \
--quantization awq_marlin \
--tensor-parallel-size 2 \
--max-model-len 8192 \
--gpu-memory-utilization 0.90 \
--enable-prefix-caching \
--host 0.0.0.0 \
--port 8001
```

LiteLLM model name: `llama3.3:70b`, `api_base: http://127.0.0.1:8001/v1`.
