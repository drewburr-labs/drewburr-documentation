# Metrics Setup

Configuration and runbook for `spud`, a Fedora workstation running KDE Plasma / Wayland.

> **Status (October 2026): exporters are down.** `spud` has moved to a
> completely different network and no longer reachable at `192.168.1.177`
> (its current LAN address is `10.73.10.177`). The Prometheus scrape targets
> in the cluster still point at the old `192.168.1.177:9256` endpoint, so
> `up{job="spud-process-exporter"}` is `0`. Restoring metrics is **pending a
> site-to-site VPN** between spud's network and the cluster; once that link is
> up, re-point the scrape targets at spud's reachable address and the queries
> below (which still reference `192.168.1.177:9256`) will need the instance
> updated to match.

## process-exporter

Exposes per-process memory and CPU metrics to Prometheus (port 9256).

### Install

```sh
sudo dnf install golang-github-ncabatoff-process-exporter
```

### Configure

`/etc/process-exporter/config.yml`:

```yaml
process_names:
  - name: "{{.Comm}}"
    cmdline:
      - '.+'
```

### Enable

```sh
sudo systemctl enable --now process-exporter
```

Prometheus scraping is wired up via the `spud-process-exporter` entry in `k8s/pve-node-exporters/values.yaml`.

Useful query to identify top memory consumers:

```promql
topk(10, namedprocess_namegroup_memory_bytes{memtype="resident", instance="192.168.1.177:9256"})
```

---

## systemd-oomd

Proactively kills cgroups under memory pressure before the kernel starts thrashing.
Was installed but not running during the [2026-04-12 memory exhaustion incident](incidents/2026-04-12-memory-exhaustion-system-freeze.md).

### Configure

`/etc/systemd/oomd.conf`:

```ini
[OOM]
SwapUsedLimit=80%
DefaultMemoryPressureLimit=60%
DefaultMemoryPressureDurationSec=20s
```

### Enable

```sh
sudo systemctl enable --now systemd-oomd
```

---

## vm.swappiness

Lower swappiness encourages the kernel to swap anonymous pages out earlier, giving more headroom before exhaustion.

`/etc/sysctl.d/99-memory.conf`:

```
vm.swappiness=10
```

Apply immediately (also takes effect on next boot):

```sh
sudo sysctl -p /etc/sysctl.d/99-memory.conf
```
