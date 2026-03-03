# Storage Server Incidents

## 2026-03-01 — NFS Outage: All NFS-backed PVCs Failed to Mount

### Summary

All pods in the `plex` namespace were stuck in `Pending` with `PodReadyToStartContainers: False`. The NFS daemon on `storage01` had crashed on Feb 28 due to memory exhaustion and never recovered, leaving NFS down for ~1.5 days.

### Timeline

| Time | Event |
|---|---|
| Feb 28, 06:06 UTC | `nfs-server.service` stopped and failed to restart: `errno 12 (Cannot allocate memory)` |
| Feb 28, 06:06 UTC | NFS remains down; no auto-restart configured |
| Mar 1, ~13:08 UTC | Pods observed stuck in `Pending` — investigation begins |
| Mar 1, 13:17 UTC | `nfs-kernel-server` manually restarted; pods recover within ~60 seconds |

### Investigation

Pods were scheduled successfully but stuck at `PodReadyToStartContainers: False` with no further events beyond scheduling. All four PVCs were `Bound`, ruling out a provisioning issue.

Checking events in the `plex` namespace showed `FailedMount` warnings on multiple pods:

```
MountVolume.MountDevice failed for volume "pvc-8171afa9..." : rpc error: code = Internal desc =
{"stderr":"/usr/local/bin/mount: illegal option -- o\nmount.nfs: Connection refused\n","timeout":true}

MountVolume.MountDevice failed for volume "pvc-1a6ee17d..." : rpc error: code = DeadlineExceeded
desc = context deadline exceeded
```

The `illegal option -- o` noise comes from the democratic-csi mount wrapper script (`/usr/local/bin/mount`), which uses `getopts` and prints warnings for every unrecognized flag. This is cosmetic — the real failure is `mount.nfs: Connection refused`.

Tested connectivity from the `democratic-csi-zfs-nfs` node pod on `kube05`:

```sh
# Port 111 (portmapper) — OPEN
bash -c 'echo > /dev/tcp/storage01.drewburr.com/111'  # success

# Port 2049 (NFS) — REFUSED
bash -c 'echo > /dev/tcp/storage01.drewburr.com/2049'  # Connection refused
```

Querying the portmapper confirmed NFS was not registered at all — only `portmapper` and `status` were listed. `nfsd` was not running.

```sh
rpcinfo -p storage01.drewburr.com
#    program vers proto   port  service
#     100000    4   tcp    111  portmapper
#     100024    1   tcp  45601  status
# (no 100003/nfs or 100005/mountd entries)
```

Checking the `nfs-server` journal on `storage01` found the original failure on Feb 28:

```
Feb 28 06:06:12 storage01 rpc.nfsd: error starting threads: errno 12 (Cannot allocate memory)
Feb 28 06:06:12 storage01 systemd[1]: nfs-server.service: Failed with result 'exit-code'.
Feb 28 06:06:12 storage01 systemd[1]: Stopped nfs-server.service - NFS server and services.
```

### Root Cause

Memory exhaustion on `storage01`. At the time NFS tried to restart, the kernel could not allocate memory for its threads.

```
$ free -h
              total   used    free   shared  buff/cache  available
Mem:           23Gi   21Gi   1.0Gi    1.8Mi       1.2Gi      1.6Gi
Swap:            0B     0B      0B
```

ZFS was consuming ~2.2 GB of kernel slab memory, dominated by:

| Slab | Size | Description |
|---|---|---|
| `zio_buf_comb_16384` | ~942 MB | ZFS I/O buffers |
| `arc_buf_hdr_t_full` | ~538 MB | ZFS ARC buffer headers |
| `abd_t` | ~161 MB | ZFS aggregate buffer descriptors |

With 21 GB of 23 GB in use and **no swap configured**, there was no fallback when NFS needed memory for its threads. Additionally, kernel logs showed active `nvmet_tcp` allocation failures at the time (`page allocation failure: order:6`), indicating NVMe-over-TCP was also under memory pressure.

### Remediation

Restarted NFS on `storage01`:

```sh
sudo systemctl restart nfs-kernel-server
```

Verified port 2049 opened and all pods recovered automatically within ~60 seconds.

### Recommendations

#### 1. Add swap

With no swap, any memory spike causes hard failures. Adding even a few GB gives the kernel room to page out cold data rather than failing allocations outright.

```sh
# Example: create a 8GB swap file
sudo fallocate -l 8G /swapfile
sudo chmod 600 /swapfile
sudo mkswap /swapfile
sudo swapon /swapfile

# Persist across reboots
echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab
```

#### 2. Cap the ZFS ARC

ZFS aggressively consumes available RAM for caching. On a 24 GB machine that also runs NFS and NVMe-oF, leaving ZFS uncapped means it will compete with the kernel for memory. A cap of ~14–16 GB leaves reasonable headroom.

```sh
# Check current ARC max (0 = uncapped)
cat /sys/module/zfs/parameters/zfs_arc_max

# Set a cap of 16GB at runtime
echo 17179869184 | sudo tee /sys/module/zfs/parameters/zfs_arc_max

# Persist across reboots
echo 'options zfs zfs_arc_max=17179869184' | sudo tee /etc/modprobe.d/zfs.conf
sudo update-initramfs -u
```

#### 3. Configure NFS to auto-restart on failure

A `Restart=on-failure` override would have recovered NFS automatically, at least for transient failures. It won't help if the system is genuinely OOM, but it handles the case where NFS fails for any other reason.

```sh
sudo systemctl edit nfs-server.service
```

Add:

```ini
[Service]
Restart=on-failure
RestartSec=10s
```

```sh
sudo systemctl daemon-reload
```

#### 4. Set up memory pressure alerting

None of this was caught until pods failed to schedule. A Prometheus alert on available memory would surface this earlier.

Example alert (add to your alerting rules):

```yaml
- alert: NodeMemoryLow
  expr: node_memory_MemAvailable_bytes / node_memory_MemTotal_bytes < 0.10
  for: 5m
  labels:
    severity: warning
  annotations:
    summary: "Low memory on {{ $labels.instance }}"
    description: "Available memory is below 10% ({{ $value | humanizePercentage }})"
```
