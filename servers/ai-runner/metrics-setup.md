# Metrics Setup

Prometheus exporters for monitoring the AI runner. Three sources are configured:

| Exporter | Port | Covers |
|---|---|---|
| node_exporter | 9100 | CPU, memory, disk, network, system, GPU die hot-spot + GDDR6X VRAM temps (textfile collector) |
| nvidia_gpu_exporter | 9835 | GPU utilization, VRAM size, edge temperature, power, throttle reasons |
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
| `nvidia_smi_temperature_gpu` | GPU edge temp in °C (averaged die sensor — does NOT include hot spot or VRAM) |
| `nvidia_smi_power_draw_watts` | Current power draw |
| `nvidia_smi_fan_speed_ratio` | Fan speed (0–1) — always 0 here, no air fans on water-cooled blocks |

---

## 2b. GPU die hot-spot + GDDR6X VRAM temps (out-of-tree)

NVIDIA does not expose GPU die hot-spot or GDDR6X memory junction temperatures via nvidia-smi or NVML on consumer Ampere cards. This is filled in by a small C tool that reads the GPU's MMIO temperature registers directly, then exports as `nvidia_gddr6_*` metrics through the existing node_exporter via its textfile collector.

Source: [ThomasBaruzier/gddr6-core-junction-vram-temps](https://github.com/ThomasBaruzier/gddr6-core-junction-vram-temps) (derived from olealgoritme/gddr6).

Local copy on host: `~/build/gddr6-temps/`. Note: the repo's stock source uses `/dev/mem`, which CONFIG_IO_STRICT_DEVMEM blocks unless `iomem=relaxed` is in the kernel cmdline — that flag is set on this host. (A patch to use `/sys/bus/pci/.../resource0` instead was attempted but Linux blocks mmap of non-prefetchable BARs through sysfs on this kernel; reboot with `iomem=relaxed` is the working path.)

### Layout

| File | Purpose |
| --- | --- |
| `/usr/local/bin/gputemps` | The C binary (root required to read MMIO) |
| `/usr/local/bin/gpu-extra-temps-export.py` | Wrapper: runs gputemps, joins to nvidia-smi UUID, writes Prometheus textfile |
| `/etc/systemd/system/gpu-extra-temps.service` | oneshot, runs the wrapper |
| `/etc/systemd/system/gpu-extra-temps.timer` | every 10s, calls the service |
| `/etc/systemd/system/node_exporter.service.d/textfile.conf` | drop-in adding `--collector.textfile.directory=/var/lib/node_exporter/textfile_collector` |
| `/var/lib/node_exporter/textfile_collector/gpu_extra_temps.prom` | output file consumed by node_exporter |

### Metrics exposed (via node_exporter on :9100)

| Metric | Description |
| --- | --- |
| `nvidia_gddr6_core_temp_celsius` | Same as `nvidia_smi_temperature_gpu` but read via NVML directly (sanity check / matches the value at `index` for the same UUID) |
| `nvidia_gddr6_junction_temp_celsius` | **GPU die hot-spot** — peak point on the silicon. Healthy delta vs core is 10-15°C; we observed 35°C, indicating poor cold-plate contact at the hottest die region |
| `nvidia_gddr6_vram_temp_celsius` | **GDDR6X memory junction** — typically the limiting factor on 3090s under load, but on this host it sits at 70-72°C even under full load, well within safe range |

Both metrics are labeled with `uuid` matching the gpu-exporter, so they join cleanly with `nvidia_smi_*` series in dashboards.

### Kernel parameter

`iomem=relaxed` was added via `grubby --update-kernel=ALL --args='iomem=relaxed'`, and to `/etc/default/grub` for future kernel installs. Required for `/dev/mem` mmap of GPU MMIO regions claimed by the nvidia driver.

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

# vLLM metrics (Prometheus scrape)
sudo firewall-cmd --permanent --add-rich-rule='rule family="ipv4" source address="192.168.4.0/23" port protocol="tcp" port="8001" accept'

# LiteLLM / ollama_exporter (proxy + /metrics)
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
systemctl is-active node_exporter nvidia_gpu_exporter ollama vllm-1 litellm

# Quick metric spot-checks
curl -s http://localhost:9100/metrics | grep 'node_cpu_seconds_total'
curl -s http://localhost:9835/metrics | grep 'nvidia_smi_memory_used_bytes'
curl -s http://localhost:8001/metrics | grep 'vllm:avg_generation_throughput'

# Verify LiteLLM router is serving on :8000
curl -s http://localhost:8000/v1/models
```
