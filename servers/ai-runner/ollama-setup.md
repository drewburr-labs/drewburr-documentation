# Ollama Setup Design

Design document for installing and configuring Ollama on `airunner01.drewburr.com`.

## Overview

Ollama will be installed as a native systemd service (not containerized) to minimize
driver complexity and overhead. It will serve inference requests to other machines on the
LAN on port `11434`.

### Goals

- Expose a stable LAN inference endpoint for LLM and vision tasks
- Keep the 11b vision model and 70b text model loaded simultaneously (~45GB VRAM)
- Allow on-demand loading of the 90b vision model when needed

---

## Current State

| Item            | Status                                    |
|-----------------|-------------------------------------------|
| Root partition  | 1.6TB free (already expanded)             |
| CUDA toolkit    | 12.9 installed                            |
| GPU 0           | RTX 3090, 24GB free                       |
| GPU 1           | RTX 3090, 24GB free                       |
| NVLink          | 4-link bridge (56 GB/s)                   |
| Ollama          | 0.20.2 installed, service active/enabled  |
| Models          | llama3.2-vision:11b (7.8GB), llama3.3:70b (42GB) |
| Firewall port   | 11434 open to 192.168.4.0/23              |

---

## Installation

Install Ollama using the official install script. This creates a `ollama` system user,
places the binary at `/usr/local/bin/ollama`, and drops a systemd unit at
`/etc/systemd/system/ollama.service`.

```sh
curl -fsSL https://ollama.com/install.sh | sh
```

---

## Configuration

Ollama is configured via environment variables in the systemd override file. Create the
drop-in directory and override:

```sh
sudo mkdir -p /etc/systemd/system/ollama.service.d
cat > /tmp/ollama_override.conf << EOF
[Service]
Environment=OLLAMA_HOST=0.0.0.0:11434
Environment=OLLAMA_NUM_PARALLEL=2
Environment=OLLAMA_MAX_LOADED_MODELS=2
Environment=OLLAMA_CONTEXT_LENGTH=8192
Environment=OLLAMA_FLASH_ATTENTION=1
Environment=OLLAMA_KV_CACHE_TYPE=q8_0
Environment=OLLAMA_GPU_OVERHEAD=0
EOF
sudo cp /tmp/ollama_override.conf /etc/systemd/system/ollama.service.d/override.conf

sudo systemctl daemon-reload
sudo systemctl enable --now ollama
```

### Key settings

| Variable                  | Value           | Reason                                                                          |
|---------------------------|-----------------|---------------------------------------------------------------------------------|
| `OLLAMA_HOST`             | `0.0.0.0:11434` | Bind to all interfaces so other LAN hosts can reach the endpoint                |
| `OLLAMA_NUM_PARALLEL`     | `2`             | Allow 2 concurrent inference requests                                           |
| `OLLAMA_MAX_LOADED_MODELS`| `2`             | Keep vision + text model both resident in VRAM simultaneously                   |
| `OLLAMA_CONTEXT_LENGTH`   | `8192`          | Cap KV cache allocation so both models fit in 48GB VRAM at the same time        |
| `OLLAMA_FLASH_ATTENTION`  | `1`             | Enable Flash Attention — reduces KV cache memory bandwidth, faster prefill      |
| `OLLAMA_KV_CACHE_TYPE`    | `q8_0`          | Quantize KV cache to 8-bit, halving its VRAM footprint (5GB → 2.7GB at 8192 ctx) |
| `OLLAMA_GPU_OVERHEAD`     | `0`             | Remove VRAM reservation so more model layers fit on GPU (79/81 vs 75/81)        |

Model weights are stored at the default location (`~ollama/.ollama/models` →
`/usr/share/ollama/.ollama/models`), which is on the 1.6TB root LV.

> **Note on context length:** Without this cap, Ollama auto-sizes context to fill all
> available VRAM (256K tokens on a 48GB pool). With both the 11b (~8GB) and 70b (~42GB)
> models totalling ~50GB of weights, capping context to 8192 ensures both stay resident.
> With `OLLAMA_KV_CACHE_TYPE=q8_0`, the KV cache is halved to ~2.7GB at 8192 context,
> which gives enough headroom to keep both models loaded and 79/81 layers on GPU.

Ollama detects and uses both GPUs automatically via CUDA. No `CUDA_VISIBLE_DEVICES`
override is needed — the driver exposes the NVLink pair as a unified 48GB pool.

---

## Firewall

The default Fedora firewall blocks port 11434. Restrict access to the LAN subnet only:

```sh
# Allow Ollama API from the LAN (adjust subnet if needed)
sudo firewall-cmd --permanent --add-rich-rule="rule family=ipv4 source address=192.168.4.0/23 port protocol=tcp port=11434 accept"
sudo firewall-cmd --reload

# Verify
sudo firewall-cmd --list-rich-rules
```

---

## Models

Pull models after the service is running. Based on the [model strategy](./model-strategy.md):

```sh
# Primary — always loaded
ollama pull llama3.2-vision:11b   # ~8GB VRAM, vision tasks
ollama pull llama3.3:70b          # ~40GB VRAM, general text

# Optional — pull if 11b vision quality is insufficient
ollama pull llama3.2-vision:90b   # ~45GB VRAM, spans both GPUs
```

The 11b vision + 70b text combo uses ~48GB combined, which fits exactly within the
48GB NVLink pool. Loading the 90b vision model requires the other models to be unloaded
first.

---

## Verification

```sh
# Service status
systemctl status ollama

# GPU utilization after a request
nvidia-smi

# Test inference from the server itself
ollama run llama3.1:8b "Say hello"

# Test from another LAN host
curl http://192.168.4.56:11434/api/generate \
  -d '{"model":"llama3.3:70b","prompt":"Hello","stream":false}'
```

---

## Open Questions

- **Open WebUI**: A browser-based chat UI (Open WebUI) could be added later as a
  container alongside Ollama for manual testing and experimentation. Not in scope for
  initial setup.
- **Auth**: Ollama has no built-in auth. The firewall rule limits exposure to the LAN,
  which is acceptable for now. If the server ever needs to be reachable from outside the
  LAN, a reverse proxy with auth (e.g. Caddy + basic auth) should be added first.
- **Automatic model loading**: Ollama only loads models on first request. If always-hot
  VRAM residency is needed, a keep-alive request can be sent via a systemd timer or
  cron job after startup.
