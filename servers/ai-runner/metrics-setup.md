# Metrics Setup

Prometheus exporters for monitoring the AI runner. Three sources are configured:

| Exporter | Port | Covers |
|---|---|---|
| node_exporter | 9100 | CPU, memory, disk, network, system |
| nvidia_gpu_exporter | 9835 | GPU utilization, VRAM, temperature, power |
| vLLM (built-in) | 8001 | Request latency, token throughput, KV cache utilization, queue depth |

> **Note:** The `ollama_exporter` transparent proxy (frcooper) has been removed. vLLM exposes
> Prometheus metrics natively at `/metrics` on its API port. Ollama no longer has a public port.

> **Note:** All commands must be run on the `ai-runner` machine. SSH in first:
> ```sh
> ssh airunner01.drewburr.com
> ```

---

## 1. node_exporter

Available directly from the Fedora package repos.

```sh
sudo dnf install -y golang-github-prometheus-node-exporter

sudo systemctl enable --now node_exporter
```

The default systemd unit listens on `0.0.0.0:9100`. Verify:

```sh
systemctl status node_exporter
curl -s http://localhost:9100/metrics | head -20
```

---

## 2. nvidia_gpu_exporter

[`utkuozdemir/nvidia_gpu_exporter`](https://github.com/utkuozdemir/nvidia_gpu_exporter) wraps `nvidia-smi` and exposes GPU metrics on port 9835. No DCGM or special NVIDIA tooling required.

### Install

Download the latest release binary for Linux amd64 from the [GitHub releases page](https://github.com/utkuozdemir/nvidia_gpu_exporter/releases). Install it to `/usr/local/bin`:

```sh
# Check https://github.com/utkuozdemir/nvidia_gpu_exporter/releases for the latest version
NVIDIA_GPU_EXPORTER_VERSION=1.3.0

curl -L "https://github.com/utkuozdemir/nvidia_gpu_exporter/releases/download/v${NVIDIA_GPU_EXPORTER_VERSION}/nvidia_gpu_exporter_${NVIDIA_GPU_EXPORTER_VERSION}_linux_x86_64.tar.gz" \
  | sudo tar -xz -C /usr/local/bin nvidia_gpu_exporter

sudo chmod +x /usr/local/bin/nvidia_gpu_exporter
```

### systemd unit

Create a dedicated system user and a service unit:

```sh
sudo useradd -r -s /sbin/nologin -M nvidia-exporter
```

```sh
sudo tee /etc/systemd/system/nvidia_gpu_exporter.service <<'EOF'
[Unit]
Description=NVIDIA GPU Prometheus Exporter
After=network.target

[Service]
User=nvidia-exporter
ExecStart=/usr/local/bin/nvidia_gpu_exporter
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF
```

```sh
sudo systemctl daemon-reload
sudo systemctl enable --now nvidia_gpu_exporter
```

Verify:

```sh
systemctl status nvidia_gpu_exporter
curl -s http://localhost:9835/metrics | grep nvidia_smi_gpu_utilization_ratio
```

### Key metrics exposed

| Metric | Description |
|---|---|
| `nvidia_smi_gpu_utilization_ratio` | GPU core utilization (0–1) |
| `nvidia_smi_memory_used_bytes` | VRAM in use |
| `nvidia_smi_memory_free_bytes` | VRAM free |
| `nvidia_smi_temperature_gpu` | GPU temp in °C |
| `nvidia_smi_power_draw_watts` | Current power draw |
| `nvidia_smi_fan_speed_ratio` | Fan speed (0–1) |

---

## 3. vLLM built-in metrics

vLLM exposes Prometheus metrics natively at `http://127.0.0.1:8001/metrics`. No additional exporter needed. See [vllm-setup.md](./vllm-setup.md) for metric details.

---

## ~~3. ollama_exporter (frcooper/ollama-exporter)~~ (removed)

> **This exporter has been removed.** vLLM replaced Ollama as the primary inference backend
> and includes native Prometheus metrics. The steps below are kept for reference only.

## ollama_exporter (frcooper/ollama-exporter)

Ollama v0.20.2 has no native `/metrics` endpoint. [`frcooper/ollama-exporter`](https://github.com/frcooper/ollama-exporter) works as a **transparent proxy**: LAN clients hit port 8000 instead of 11434, the exporter intercepts `/api/chat` and `/api/generate` to record metrics, and proxies everything else through to Ollama on `127.0.0.1:11435`.

Ollama is moved to loopback-only so all external traffic is metered.

### Prereqs

```sh
sudo dnf install -y python3-fastapi python3-uvicorn python3-prometheus_client python3-httpx
```

### Install

```sh
sudo curl -fsSL -o /usr/local/bin/ollama_exporter.py \
  https://raw.githubusercontent.com/frcooper/ollama-exporter/main/ollama_exporter.py
```

### Move Ollama to loopback

Update the systemd override to bind Ollama to `127.0.0.1:11435` only:

```sh
sudo tee /etc/systemd/system/ollama.service.d/override.conf > /dev/null << 'EOF'
[Service]
Environment=OLLAMA_HOST=127.0.0.1:11435
Environment=OLLAMA_MODELS=/var/lib/ollama/models
Environment=OLLAMA_NUM_PARALLEL=2
Environment=OLLAMA_MAX_LOADED_MODELS=2
EOF

sudo mkdir -p /var/lib/ollama/models
sudo chown -R ollama:ollama /var/lib/ollama

sudo systemctl daemon-reload
sudo systemctl restart ollama
```

### systemd unit

```sh
sudo tee /etc/systemd/system/ollama_exporter.service > /dev/null << 'EOF'
[Unit]
Description=Ollama Prometheus Exporter (transparent proxy)
After=network.target ollama.service
Requires=ollama.service

[Service]
ExecStart=/usr/bin/python3 /usr/local/bin/ollama_exporter.py
Environment=OLLAMA_HOST=http://127.0.0.1:11435
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable --now ollama_exporter
```

### Key metrics

| Metric | Description |
|---|---|
| `ollama_requests_total` | Request count per model |
| `ollama_response_seconds` | End-to-end response latency |
| `ollama_load_duration_seconds` | Model load time |
| `ollama_tokens_generated_total` | Output tokens per model |
| `ollama_tokens_processed_total` | Input (prompt) tokens per model |
| `ollama_tokens_per_second` | Generation throughput |

---

## Firewall

Open the exporter ports to the LAN subnet so Prometheus can scrape them. Adjust `192.168.4.0/23` if your Prometheus host is on a different subnet.

Port 8001 (vLLM) and port 11434 (Ollama) bind to `127.0.0.1` only. All LAN inference traffic goes through LiteLLM on port 8000.

```sh
# node_exporter
sudo firewall-cmd --permanent --add-rich-rule='rule family="ipv4" source address="192.168.4.0/23" port protocol="tcp" port="9100" accept'

# nvidia_gpu_exporter
sudo firewall-cmd --permanent --add-rich-rule='rule family="ipv4" source address="192.168.4.0/23" port protocol="tcp" port="9835" accept'

# ollama_exporter (proxy + /metrics)
sudo firewall-cmd --permanent --add-rich-rule='rule family="ipv4" source address="192.168.4.0/23" port protocol="tcp" port="8000" accept'

sudo firewall-cmd --reload

# Verify
sudo firewall-cmd --list-rich-rules
```

---

## Prometheus scrape config

Add these jobs to your Prometheus `scrape_configs`:

```yaml
scrape_configs:
  - job_name: airunner01_node
    static_configs:
      - targets: ['192.168.4.56:9100']
        labels:
          instance: airunner01

  - job_name: airunner01_gpu
    static_configs:
      - targets: ['192.168.4.56:9835']
        labels:
          instance: airunner01

  - job_name: airunner01_vllm
    static_configs:
      - targets: ['192.168.4.56:8001']
        labels:
          instance: airunner01
```

---

## Verification

After all services are running and Prometheus is scraping:

```sh
# Check all services are up
systemctl is-active node_exporter nvidia_gpu_exporter ollama vllm-70b litellm

# Quick metric spot-checks
curl -s http://localhost:9100/metrics | grep 'node_cpu_seconds_total'
curl -s http://localhost:9835/metrics | grep 'nvidia_smi_memory_used_bytes'
curl -s http://localhost:8001/metrics | grep 'vllm:avg_generation_throughput'

# Verify LiteLLM router is serving on :8000
curl -s http://localhost:8000/v1/models
```
