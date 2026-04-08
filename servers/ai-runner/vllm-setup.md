# vLLM Setup

Design document for running vLLM on `airunner01.drewburr.com` as the primary inference backend for `llama3.3:70b`.

## Overview

vLLM replaces Ollama as the inference backend for the 70B text model. Ollama is retained for `llama3.2-vision:11b` (vision tasks only). LiteLLM acts as a unified OpenAI-compatible router in front of both.

### Why vLLM

- **Tensor parallelism**: Both GPUs work on every layer simultaneously (vs. Ollama's pipeline parallelism where GPUs take turns)
- **PagedAttention**: KV cache managed as virtual memory pages — much more efficient under concurrent load
- **Continuous batching**: New requests are batched into ongoing inference, keeping GPU utilization high
- **Native Prometheus metrics**: Built-in `/metrics` endpoint, no proxy needed

### Architecture

```
LAN clients / Open WebUI
        │
        ▼
  :8000  LiteLLM (router, OpenAI API)
    ├─── llama3.3:70b  ──► :8001  vLLM  (Podman, both GPUs, TP=2)
    └─── llama3.2-vision:11b ──► :11434  Ollama  (native, loopback)
```

### GPU allocation

| Service | GPUs | Notes |
|---|---|---|
| `vllm-1` | GPU 0 + GPU 1 (TP=2) | Tensor parallel — both active per token |
| `vllm-11b-vision` | GPU 0 only | Alternative to Ollama for vision; not enabled by default |
| Ollama (`llama3.2-vision:11b`) | GPU 0 + GPU 1 | Used for vision; conflicts with vLLM 70B if loaded simultaneously |

**Both models cannot be loaded in VRAM at the same time.** The 70B uses ~40GB across both GPUs; 11B vision uses an additional ~22GB. vLLM and Ollama manage their own VRAM independently — when 70B is serving, vision requests may incur a model-swap delay in Ollama.

---

## Prerequisites

### Container runtime

vLLM runs in Podman containers (rootful, as system services).

```sh
# Podman is included in Fedora by default
podman --version
```

### nvidia-container-toolkit

Required for GPU access inside Podman containers. Uses CDI (Container Device Interface).

```sh
# Add NVIDIA container toolkit repo
curl -s -L https://nvidia.github.io/libnvidia-container/stable/rpm/nvidia-container-toolkit.repo \
  | sudo tee /etc/yum.repos.d/nvidia-container-toolkit.repo

sudo dnf install -y nvidia-container-toolkit

# Generate CDI specification (makes GPUs available to Podman)
sudo nvidia-ctk cdi generate --output=/etc/cdi/nvidia.yaml

# Verify — should show both 3090s
sudo podman run --rm --device nvidia.com/gpu=all \
  docker.io/nvidia/cuda:12.4.1-base-ubi8 nvidia-smi
```

Note: CDI requires regenerating after driver updates:
```sh
sudo nvidia-ctk cdi generate --output=/etc/cdi/nvidia.yaml
```

> **Networking:** vLLM containers use `--network=host` so they share the host's network
> stack and can resolve DNS and reach HuggingFace for model downloads. Podman's default
> bridge network cannot route to the LAN gateway for DNS. The `--host 127.0.0.1` vLLM flag
> ensures it only listens on loopback despite sharing the host network.

---

## Model

`casperhansen/llama-3.3-70b-instruct-awq`

- AWQ quantization (~40GB), no HuggingFace token required
- Note: `hugging-quants/Meta-Llama-3.3-70B-Instruct-AWQ-INT4` does not exist; casperhansen is the correct community quant for 3.3
- Downloaded automatically on first start to `/var/lib/vllm/models`

```sh
sudo mkdir -p /var/lib/vllm/models
```

---

## vLLM 70B service

`/etc/systemd/system/vllm-1.service`

```ini
[Unit]
Description=vLLM - llama3.3:70b (tensor parallel)
After=network-online.target
Wants=network-online.target

[Service]
Restart=always
RestartSec=10
ExecStartPre=-/usr/bin/podman stop vllm-1
ExecStartPre=-/usr/bin/podman rm vllm-1
ExecStart=/usr/bin/podman run --name vllm-1 \
  --device nvidia.com/gpu=all \
  --ipc=host \
  --ulimit memlock=-1 \
  -p 8001:8000 \
  -v /var/lib/vllm/models:/root/.cache/huggingface \
  docker.io/vllm/vllm-openai:latest \
    --model casperhansen/llama-3.3-70b-instruct-awq \
    --quantization awq_marlin \
    --tensor-parallel-size 2 \
    --max-model-len 8192 \
    --gpu-memory-utilization 0.90 \
    --enable-prefix-caching \
    --host 0.0.0.0 \
    --port 8000
ExecStop=/usr/bin/podman stop vllm-1

[Install]
WantedBy=multi-user.target
```

### Key flags

| Flag | Value | Reason |
|---|---|---|
| `--device nvidia.com/gpu=all` | both GPUs | CDI device passthrough |
| `--ipc=host` | host IPC namespace | Required for shared memory between GPU processes |
| `--tensor-parallel-size` | `2` | Split each layer across both GPUs simultaneously |
| `--quantization` | `awq_marlin` | Use Marlin kernel for AWQ — faster than standard AWQ |
| `--gpu-memory-utilization` | `0.90` | Leave 10% VRAM headroom for CUDA overhead |
| `--enable-prefix-caching` | — | Cache KV for repeated system prompts (e.g. Open WebUI) |
| `--max-model-len` | `8192` | Matches Ollama context cap; increase if needed (uses more VRAM) |

---

## vLLM 11B vision service (optional)

`/etc/systemd/system/vllm-11b-vision.service`

Not enabled by default — Ollama serves vision. Enable this if Ollama is removed or if better multi-user vision performance is needed. **Cannot run simultaneously with vLLM 70B** (GPU conflict).

```ini
[Unit]
Description=vLLM - llama3.2-vision:11b (single GPU)
After=network-online.target
Wants=network-online.target

[Service]
Restart=on-failure
RestartSec=10
ExecStartPre=-/usr/bin/podman stop vllm-11b-vision
ExecStartPre=-/usr/bin/podman rm vllm-11b-vision
ExecStart=/usr/bin/podman run --name vllm-11b-vision \
  --device nvidia.com/gpu=0 \
  --ipc=host \
  --ulimit memlock=-1 \
  -p 127.0.0.1:8002:8000 \
  -v /var/lib/vllm/models:/root/.cache/huggingface \
  docker.io/vllm/vllm-openai:latest \
    --model meta-llama/Llama-3.2-11B-Vision-Instruct \
    --max-model-len 8192 \
    --gpu-memory-utilization 0.90 \
    --enable-prefix-caching \
    --host 0.0.0.0 \
    --port 8000
ExecStop=/usr/bin/podman stop vllm-11b-vision

[Install]
WantedBy=multi-user.target
```

Note: `meta-llama/Llama-3.2-11B-Vision-Instruct` is a gated model — requires a HuggingFace token:
```sh
sudo mkdir -p /etc/vllm
echo "HF_TOKEN=hf_..." | sudo tee /etc/vllm/env
```
Then add `--env-file /etc/vllm/env` to the `podman run` command.

---

## LiteLLM router

LiteLLM proxies all inference traffic on `:8000` and routes by model name.

### Config: `/etc/litellm/config.yaml`

```yaml
model_list:
  - model_name: llama3.3:70b
    litellm_params:
      model: openai/casperhansen/llama-3.3-70b-instruct-awq
      api_base: http://127.0.0.1:8001/v1
      api_key: none

  - model_name: llama3.2-vision:11b
    litellm_params:
      model: ollama/llama3.2-vision:11b
      api_base: http://127.0.0.1:11434

litellm_settings:
  drop_params: true

general_settings:
  master_key: none
```

### Service: `/etc/systemd/system/litellm.service`

```ini
[Unit]
Description=LiteLLM Proxy Router
After=network-online.target vllm-1.service
Wants=network-online.target vllm-1.service

[Service]
Restart=always
RestartSec=10
ExecStartPre=-/usr/bin/podman stop litellm
ExecStartPre=-/usr/bin/podman rm litellm
ExecStart=/usr/bin/podman run --name litellm \
  --network=host \
  -v /etc/litellm/config.yaml:/app/config.yaml:ro \
  -v /etc/litellm/fix_tool_messages.py:/app/fix_tool_messages.py:ro \
  ghcr.io/berriai/litellm:main-latest \
    --config /app/config.yaml \
    --port 8000 \
    --host 0.0.0.0
ExecStop=/usr/bin/podman stop litellm

[Install]
WantedBy=multi-user.target
```

---

## Metrics

vLLM exposes Prometheus metrics natively at `http://127.0.0.1:8001/metrics`. The `ollama_exporter` proxy is no longer needed and has been removed.

### Key vLLM metrics

| Metric | Description |
|---|---|
| `vllm:e2e_request_latency_seconds` | End-to-end request latency |
| `vllm:request_prompt_tokens` | Input tokens per request |
| `vllm:request_generation_tokens` | Output tokens per request |
| `vllm:gpu_cache_usage_perc` | KV cache utilization (PagedAttention) |
| `vllm:num_requests_running` | Requests currently being processed |
| `vllm:num_requests_waiting` | Requests queued |
| `vllm:avg_generation_throughput_toks_per_s` | Generation throughput |

Prometheus scrapes `:8001/metrics` via the `airunner-vllm-exporter` ServiceMonitor in `k8s/pve-node-exporters/values.yaml`.

---

## Firewall

Port 8000 is already open to the LAN (from the previous Ollama exporter).

Port 8001 must be open to the LAN so Prometheus can scrape vLLM metrics:

```sh
sudo firewall-cmd --permanent --add-rich-rule='rule family="ipv4" source address="192.168.4.0/23" port protocol="tcp" port="8001" accept'
sudo firewall-cmd --reload
```

vLLM's vision service (`:8002`) is not exposed to LAN.

---

## Verification

```sh
# Check all services
systemctl is-active vllm-1 litellm ollama

# vLLM model loaded (after ~40GB download on first start)
curl -s http://localhost:8001/v1/models | python3 -m json.tool

# LiteLLM routing (OpenAI API)
curl http://localhost:8000/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{"model":"llama3.3:70b","messages":[{"role":"user","content":"Say hello"}],"max_tokens":20}'

# vLLM metrics
curl -s http://localhost:8001/metrics | grep vllm:avg_generation_throughput
```
