# storage01 — NVMe-oF I/O Errors Causing EXT4 Read-Only Remounts

## 2026-04-17 — Recurring: nvmet_tcp Memory Allocation Failures

### Summary

Multiple pods across the cluster have had their PVCs go read-only over the past few weeks. Each time, the root cause is `nvmet_tcp` on `storage01` failing to allocate kernel memory for I/O mapping, causing NVMe-oF write errors on the initiator side (kube nodes), which triggers EXT4 to remount the filesystem read-only to prevent corruption.

This is the same root cause as the [March 2026 NFS outage](storage01-nfs-outage-oom.md) — ZFS ARC is uncapped on a 24 GB machine with no swap, leaving insufficient memory for kernel subsystems under load.

### Affected Pod (most recent instance)

`minecraft-underground-craftycontroller-0` on `kube05`

### Timeline

| Time (UTC) | Event |
|---|---|
| Apr 17, 00:22 | Write failures begin on `nvme10n1` (kube05): `I/O Error (sct 0x0 / sc 0x6)` |
| Apr 17, 00:22 | EXT4 on `nvme10n1` remounts read-only: `failed to convert unwritten extents -- potential data loss!` |
| Apr 17, 01:18 | `storage01` logs: `nvmet_tcp: queue 662: failed to map data` |
| Apr 17, 02:23 | `storage01` logs: `warn_alloc` + `nvmet_tcp: queue 123: failed to map data` |
| Apr 17, 02:53 | `storage01` logs: `nvmet_tcp: queue 663: failed to map data` |
| Apr 17, 02:59 | `storage01` logs: `nvmet_tcp: queue 667: failed to map data` |

### Investigation

Pod was `2/2 Running` with no Kubernetes-level errors. All PVC volume mounts showed `ReadOnly: false` in the pod spec. The issue was at the filesystem layer inside the container, not the Kubernetes PVC definition.

`kube05` syslog confirmed the sequence — NVMe-oF I/O errors followed immediately by EXT4 remounting read-only:

```
Apr 17 00:22:48 kube05 kernel: nvme10c10n1: I/O Cmd(0x1) @ LBA 273325664, 30472 blocks, I/O Error (sct 0x0 / sc 0x6)
Apr 17 00:22:48 kube05 kernel: I/O error, dev nvme10c10n1, sector 273325664 op 0x1:(WRITE)
Apr 17 00:22:48 kube05 kernel: EXT4-fs warning (device nvme10n1): ext4_end_bio:368: I/O error 10 writing to inode 8519709
Apr 17 00:22:42 kube05 kernel: EXT4-fs (nvme10n1): failed to convert unwritten extents to written extents -- potential data loss!
```

On `storage01`, the NVMe-oF target was failing to allocate memory for incoming I/O:

```
Apr 17 01:18:56 storage01 kernel: nvmet_tcp: queue 662: failed to map data
Apr 17 02:23:33 storage01 kernel: warn_alloc: 1 callbacks suppressed
Apr 17 02:23:33 storage01 kernel:  nvmet_tcp_map_data+0x72/0x110 [nvmet_tcp]
Apr 17 02:23:33 storage01 kernel: nvmet_tcp: queue 123: failed to map data
```

Memory state on `storage01` at time of investigation:

```
              total   used    free   shared  buff/cache  available
Mem:           23Gi   21Gi   1.4Gi    1.8Mi       586Mi      1.6Gi
Swap:            0B     0B      0B
```

ZFS ARC configuration:

| Parameter | Value |
|---|---|
| `zfs_arc_max` | 0 (uncapped) |
| `zfs_arc_min` | 0 |
| ARC `c_max` (effective) | 22.5 GB |
| ARC current size | ~20.5 GB |

### Root Cause

ZFS ARC is uncapped and consuming up to 22.5 GB of the 24 GB available. With no swap, the ~1.5 GB of remaining free memory is insufficient for `nvmet_tcp` to allocate kernel pages for I/O mapping under any load spike. The `warn_alloc` kernel warning confirms page allocation is failing after retries.

The failures are not strictly tied to sanoid snapshot runs — memory is chronically tight and any I/O burst on any of the 70+ NVMe-oF namespaces can trigger an allocation failure. The result on the initiator side is an NVMe internal error (`sc 0x6`) which EXT4 treats as a hard I/O error, triggering a protective read-only remount.

This is the **same root cause** as the March 2026 NFS outage. The recommendations from that incident (cap ARC, add swap) were not implemented.

### Remediation (pending)

Pod requires a restart to remount the filesystem read-write after the storage issue is resolved. No data loss is expected — EXT4's read-only remount is a protective measure.

### Fix

#### 1. Cap ZFS ARC at 16 GB

Frees ~6.5 GB of headroom for kernel and nvmet_tcp. Apply at runtime (no reboot needed) and persist:

```sh
# Apply immediately
echo 17179869184 | sudo tee /sys/module/zfs/parameters/zfs_arc_max

# Persist across reboots
echo 'options zfs zfs_arc_max=17179869184' | sudo tee /etc/modprobe.d/zfs.conf
sudo update-initramfs -u
```

#### 2. Add 8 GB swap file

`/dev/sda1` has 42 GB free. Swap provides a safety net so allocation failures degrade to slowness rather than errors:

```sh
sudo fallocate -l 8G /swapfile
sudo chmod 600 /swapfile
sudo mkswap /swapfile
sudo swapon /swapfile
echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab
```

#### 3. Set vm.swappiness = 10

The current value is 60, which is inappropriate for a storage server — it will aggressively swap out kernel data even under light pressure. Setting it low ensures swap is only used as a last resort:

```sh
echo 'vm.swappiness=10' | sudo tee /etc/sysctl.d/99-swap.conf
sudo sysctl -p /etc/sysctl.d/99-swap.conf
```
