# 2026-04-12 — System Freeze: Memory Exhaustion + Swap Saturation

## Summary

`spud` (192.168.1.177) became completely unresponsive and required a hard power-cycle. The system had been up for 7 days. Root cause was anonymous memory growth — almost certainly from one or more Electron apps (Discord, browser) left running without restart from Saturday morning through Sunday evening — which exhausted both RAM and swap, causing the kernel to thrash the disk and starve the Wayland compositor's main thread of CPU.

## System

| Field | Value |
|---|---|
| Host | `spud` (192.168.1.177) |
| OS | Fedora Linux 6.19.10-200.fc43.x86_64 |
| Desktop | KDE Plasma / Wayland (`kwin_wayland`) |
| GPU | AMD RX 9070XT |
| Uptime before crash | ~7 days (booted Sun Apr 5 ~20:38) |

## Timeline

| Time | Event |
|---|---|
| Apr 5, 20:38 | System booted |
| Apr 5–10 (evenings) | Normal pattern: AnonPages reset each evening as heavy apps were closed/restarted; memory recovered 10–20% nightly |
| **Apr 11, ~01:00–02:00** | **AnonPages begin climbing without overnight recovery — something left running** |
| Apr 11, 02:38 | AnonPages at 45.5% of total RAM |
| Apr 11, 12:38 | AnonPages at 60.1% |
| Apr 11, 21:38 | AnonPages at 65.5% |
| Apr 12, 00:38 | AnonPages at 68.3%; swap already 0% free |
| Apr 12, 18:19 | RAM available drops below 5% |
| Apr 12, 18:23 | `kwin_wayland` reports input event processing lagging 50ms–1000ms behind: "your system is too slow" |
| Apr 12, 18:23:08 | iowait spikes to 50–90% across all CPU cores simultaneously |
| Apr 12, 18:24:06 | Power button pressed (first attempt) |
| Apr 12, 18:24:35 | Load1 hits 23.27 |
| Apr 12, 18:24:48 | `kwin_wayland`: "The main thread was hanging temporarily!" |
| Apr 12, 18:25:05 | Load1 hits 37.13; node-exporter data gap begins (system unresponsive) |
| Apr 12, 18:25:09 | Fifth power button press — system still unresponsive to clean shutdown |
| Apr 12, 18:25 | Force reboot |
| Apr 12, 18:26:36 | Node back online; RAM 92.5% available, swap 100% free, load1 < 1 |

## Investigation

### Journals

`journalctl -b -1` from the previous boot showed no kernel OOM killer activity and no `systemd-oomd` entries (it was not running). The smoking gun from the journal was `kwin_wayland` reporting progressively worsening input lag starting at 18:23, followed by five power button presses being ignored before the force reboot.

### Grafana / node-exporter metrics

All metrics are from the `generic-node-exporter` job scraping `192.168.1.177:9100`.

**Memory available — final minutes before crash:**

| Time | RAM Available |
|---|---|
| 18:19 | 4.96% |
| 18:23:06 | 3.35% |
| 18:23:36 | 2.85% |
| 18:24:06 | 1.65% |
| 18:25:06 | 1.58% |
| 18:26:36 | **92.50%** ← post-reboot |

**System load:**

| Time | Load1 |
|---|---|
| 18:22 | 0.9 (normal) |
| 18:24:35 | 23.27 |
| 18:25:05 | 37.13 |
| 18:26:35 | 0.27 (post-reboot) |

**iowait per CPU core at 18:24:**
All cores simultaneously hit 50–75% iowait — a clear signal the kernel was blocking on synchronous page reclaim (thrashing) across every core.

**Swap:** 0% free for the entire observation window before the crash. Swap had been exhausted well before the final minutes. After reboot: 100% free.

### 7-day AnonPages trend

Anonymous memory (process heap/stack — not file-backed, can only be paged to swap) grew steadily from Saturday morning with no overnight recovery, indicating something was left running continuously:

```
Sat Apr 11 02:38   45.5%
Sat Apr 11 06:38   54.0%
Sat Apr 11 12:38   60.1%
Sat Apr 11 21:38   65.5%
Sun Apr 12 00:38   68.3%
Sun Apr 12 11:38   68.7%   ← last sample before crash
```

On every previous day (Mon–Fri), AnonPages would reset each evening when apps were closed, recovering 10–20% of RAM. This reset did not occur after Friday Apr 10 night, indicating whatever process was leaking was never restarted over the following 33 hours.

## Root Cause

**Memory exhaustion from anonymous page growth, compounded by a fully exhausted swap partition.**

The sequence:

1. One or more long-running processes (most likely Discord and/or a browser) accumulated anonymous memory over 33 hours without being restarted, growing to occupy ~68% of total RAM.
2. Swap was already fully consumed, so there was no paging headroom.
3. As the last ~5% of free RAM was consumed, the kernel began synchronous page reclaim on every memory allocation, causing all CPU cores to block on disk I/O (iowait 50–75%).
4. This disk thrashing drove load1 to 37, starving `kwin_wayland`'s main thread of CPU time.
5. The Wayland compositor froze, rendering the system unresponsive to input including the power button's clean-shutdown handler in `systemd-logind`.
6. Hard reboot required.

No process exporter was installed, so the specific process(es) responsible cannot be confirmed from metrics alone.

## How to Better Identify This Next Time

### 1. Install process-exporter

Without per-process memory metrics, the culprit process can only be inferred. `prometheus-process-exporter` (or `process-exporter` from COPR) exposes `namedprocess_namegroup_memory_bytes` per process group, making it trivial to see which process owns the growing anonymous memory.

```sh
# Fedora
sudo dnf install golang-github-ncabatoff-process-exporter
```

Configure `/etc/process-exporter/config.yml` to group by process name, then scrape it in Prometheus. With this in place, a query like the following would show the top memory consumers over time:

```promql
topk(10, namedprocess_namegroup_memory_bytes{memtype="resident",instance="192.168.1.177:9200"})
```

### 2. Enable systemd-oomd

`systemd-oomd` monitors memory pressure and proactively kills cgroups under pressure before the kernel thrashes. It was installed but not running at the time of the incident.

```sh
sudo systemctl enable --now systemd-oomd
```

Configure thresholds in `/etc/systemd/oomd.conf`:

```ini
[OOM]
SwapUsedLimit=80%
DefaultMemoryPressureLimit=60%
DefaultMemoryPressureDurationSec=20s
```

This would have killed the leaking process (or its cgroup) when swap hit 80% used, well before the system became unresponsive.

### 3. Add a Prometheus memory pressure alert

Available memory was below 15% for hours before the crash with no alert firing. Add this to your alerting rules:

```yaml
- alert: NodeMemoryPressure
  expr: node_memory_MemAvailable_bytes{instance="192.168.1.177:9100"} / node_memory_MemTotal_bytes{instance="192.168.1.177:9100"} < 0.15
  for: 10m
  labels:
    severity: warning
  annotations:
    summary: "spud: low memory"
    description: "Available memory below 15% for 10m (current: {{ $value | humanizePercentage }})"

- alert: NodeSwapSaturated
  expr: (node_memory_SwapTotal_bytes{instance="192.168.1.177:9100"} - node_memory_SwapFree_bytes{instance="192.168.1.177:9100"}) / node_memory_SwapTotal_bytes{instance="192.168.1.177:9100"} > 0.80
  for: 5m
  labels:
    severity: warning
  annotations:
    summary: "spud: swap nearly full"
    description: "Swap usage above 80% for 5m (current: {{ $value | humanizePercentage }})"
```

## Prevention

### 1. Restart Electron apps regularly (or set memory limits)

Discord and Chromium-based browsers are the primary suspects. Both are Electron apps known to leak memory over long sessions. The simplest mitigation is a periodic restart, either manually or via a systemd timer:

```sh
# Example: restart Discord daily at 04:00
# ~/.config/systemd/user/discord-restart.timer
[Unit]
Description=Restart Discord daily

[Timer]
OnCalendar=*-*-* 04:00:00
Persistent=true

[Install]
WantedBy=timers.target
```

Alternatively, use `systemd-run --user --scope -p MemoryMax=4G flatpak run com.discordapp.Discord` to cap Discord's memory at the cgroup level.

### 2. Tune swap pressure (`vm.swappiness`)

The default `vm.swappiness=60` causes the kernel to favour evicting file-backed pages before anonymous ones. Lowering it makes anonymous pages more likely to be swapped out earlier, giving more warning time:

```sh
# More aggressive swapping of anonymous pages under pressure
echo 'vm.swappiness=10' | sudo tee -a /etc/sysctl.d/99-memory.conf
sudo sysctl -p /etc/sysctl.d/99-memory.conf
```

### 3. Ensure swap is adequately sized

With 7-day sessions and heavy Electron usage, swap should be large enough to absorb at least one major app's RSS. If the swap partition is currently small, consider supplementing with a swapfile.

### 4. Shorter reboots / suspend cycles

The system had been up 7 days. A weekly reboot (or daily suspend/resume) resets any accumulated leaks before they compound. A simple systemd timer:

```sh
sudo systemctl edit --force --full weekly-reboot.timer
```
