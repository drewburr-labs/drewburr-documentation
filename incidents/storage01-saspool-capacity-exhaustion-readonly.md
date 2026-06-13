# storage01 — sas-pool Capacity Exhaustion Causing EXT4 Read-Only Remounts

## 2026-06-12 — RAIDZ Padding Amplification Filled the Pool

### Summary

Six pods on `kube05` had PVCs go read-only simultaneously. `sas-pool` on `storage01` (which backs the `zfs-nvmeof` storage class) hit 97% capacity, causing the NVMe-oF target to reject writes with **Capacity Exceeded** (`sc 0x81`). EXT4 on the initiator side aborted its journal on each affected volume and remounted read-only (`emergency_ro`).

The pool filled not because of data growth or snapshots, but because of **RAIDZ padding amplification**: zvols on this pool consume ~3x their logical size, so the 7.27T pool effectively holds only ~2.4T of data.

Symptom is identical to the [April 2026 nvmet_tcp OOM incident](storage01-nvmeof-readonly-oom.md), but the root cause is different — that one was `sc 0x6` (internal error, memory allocation); this one is `sc 0x81` (capacity exceeded, pool full).

### Affected Pods

All on `kube05`:

| Pod | Volumes affected |
|---|---|
| `minecraft-derailed/minecraft-derailed-craftycontroller-0` | `/crafty/servers` |
| `minecraft-jinkies/minecraft-jinkies-craftycontroller-0` | 4 volumes |
| `minecraft-underground/minecraft-underground-craftycontroller-0` | 2 volumes |
| `plex/plex-plex-0` | 1 volume |
| `plex/plex-qbittorrent-0` | 1 volume |
| `loki/loki-write-1` | 1 volume |

### Timeline

| Time (UTC) | Event |
|---|---|
| Jun 12, 12:04 | Write failures begin on kube05: `I/O Cmd(0x1) ... I/O Error (sct 0x0 / sc 0x81) MORE DNR`, kernel logs `critical space allocation error` |
| Jun 12, 12:08 | EXT4 warnings: `failed to convert unwritten extents to written extents -- potential data loss!` across nvme0, nvme2, nvme12 |
| Jun 12, 12:13 | EXT4 `Detected aborted journal` → `Remounting filesystem read-only` on multiple volumes |
| Jun 12, 12:15 | qbittorrent volume (nvme3) follows |
| Jun 12, ~12:45 | Investigation begins; `sas-pool` found at 97% CAP, 167G free, all datasets showing ~5.5G AVAIL |
| Jun 12, ~13:30 | crafty-derailed pod restarted to clear `emergency_ro`; backups downloaded |
| Jun 12, ~14:30 | Backup data deleted in-pod (83G → 38G), `fstrim` run from kube05 (158G trimmed) — **pool freed nothing**, blocks pinned by sanoid hourly autosnap |
| Jun 12, ~14:45 | `zfs destroy` of the pinning snapshot freed 478G; pool 97% → 89% |
| Jun 12, ~15:00 | Remaining five pods restarted; zero `emergency_ro` mounts on kube05; all pods Ready |

### Investigation

Pods were `1/1 Running` with PVCs `Bound` and no Kubernetes-level errors — probes are HTTP-based and reads still worked. Inside the pod, writes failed (`touch: Read-only file system`) while `df` showed the volume only 57% full. `/proc/mounts` had the tell:

```
/dev/nvme16n1 /crafty/servers ext4 rw,relatime,stripe=8192,emergency_ro 0 0
```

`kube05` dmesg showed the same NVMe-oF → EXT4 cascade as the April incident, but with a different status code:

```
nvme16c16n1: I/O Cmd(0x1) @ LBA 54525960, 8 blocks, I/O Error (sct 0x0 / sc 0x81) MORE DNR
critical space allocation error, dev nvme16c16n1, sector 54525960 op 0x1:(WRITE)
EXT4-fs error (device nvme2n1): ext4_journal_check_start:87: comm python3: Detected aborted journal
EXT4-fs (nvme2n1): Remounting filesystem read-only
```

`sc 0x81` is NVMe **Capacity Exceeded**, and the block layer logs it as `critical space allocation error` (`BLK_STS_NOSPC`) — the target ran out of backing space. On `storage01`:

```
NAME       SIZE  ALLOC   FREE  CKPOINT  EXPANDSZ   FRAG    CAP  DEDUP    HEALTH  ALTROOT
sas-pool  7.27T  7.10T   167G        -         -    72%    97%  1.00x    ONLINE  -
```

Ruled out before finding the cause:

- **Snapshots**: 17,309 snapshots existed (sanoid autosnaps + syncoid), but `usedbysnapshots` was near zero across the pool.
- **Data growth**: individual zvols' filesystems were far from full.

The anomaly was zvols consuming ~3x their volsize:

| zvol (PVC) | volsize | USED |
|---|---|---|
| `pvc-1a52cb52` (crafty-backups, 83G of data) | 200G | 599G |
| `pvc-2d22c9d1` | 50G | 148G |
| `pvc-4f88c9c9` | 50G | 149G |

### Root Cause

`sas-pool` is a **20-disk raidz3 with ashift=13** (8K sectors), and democratic-csi creates zvols with the default **16K volblocksize**. Each 16K block is 2 data sectors + 3 parity sectors, padded up to a multiple of (parity+1)=4 sectors — up to 8 sectors (64K) allocated per 16K of logical data. Net effect: ~3x space amplification on every PVC.

The pool's thin-provisioned volsizes looked safely undercommitted, but actual consumption was 3x logical usage. Allocation hit the pool ceiling, the NVMe-oF target started returning Capacity Exceeded, and EXT4 on the initiators protectively went read-only.

### Recovery Notes

Two non-obvious steps were required to actually reclaim space:

1. **Deleting files inside the ext4 filesystem freed nothing at the pool level.** The zvol needs a discard pass. `fstrim` inside the pod fails (`FITRIM ioctl: Operation not permitted` — unprivileged container); it must be run from the node against the CSI globalmount:

   ```sh
   mp=$(grep <nvme-dev> /proc/mounts | grep -m1 kubelet | awk '{print $2}')
   sudo fstrim -v "$mp"
   ```

2. **Even after trim, the pool freed nothing** — the trimmed blocks were pinned by the sanoid hourly autosnap taken just before the deletion (`usedbysnapshots` jumped from ~0 to 478G). Destroying that one snapshot returned the space.

`emergency_ro` does not self-heal after a journal abort; each affected pod required a restart so the CSI driver could run a full unmount/fsck/remount cycle. No data loss observed — the read-only remount is protective.

### Fix

#### Done (2026-06-12)

- Old backups deleted from crafty-backups, fstrim'd, pinning snapshot destroyed → pool at 89% with 765G free.
- All six affected pods restarted and verified writable.

#### Outstanding

Remediation is written up in the
[sas-pool space remediation runbook](../k8s/democratic-csi-zfs-nvmeof/volblocksize-remediation.md).

1. ~~orphaned zvols~~ **Done 2026-06-13**: 21 orphaned zvols (~2.5T incl. snapshots) destroyed, 5 stale nvmet subsystems torn down, persisted nvmet config regenerated. Pool dropped from 89% to **54% CAP**. The deletion-failure root cause — a corrupt 0-byte `/root/.nvmetcli/prefs.bin` crashing every nvmetcli invocation since May 19 — was fixed 2026-06-12; see runbook 0.4. Note the near-miss recorded in runbook 0.1: zfs-nfs driver datasets share the nvmeof dataset parent and must not be mistaken for orphans. Also: `minecraft-poke-central/crafty-backups` PVC/PV still dangle over a zvol manually destroyed 2026-02-08 — delete them before reviving that namespace.
2. ~~volblocksize fix~~ **Done 2026-06-12**: `zvolBlocksize: "64K"` applied to the driver config secret, controller restarted, verified end-to-end (new zvol provisioned at 64K, delete path destroys the zvol cleanly). Affects new PVCs only; existing large volumes still need file-level migration (zvols cannot be re-blocked in place, and `zfs send` preserves volblocksize). Runbook Phase 2.
3. **No alerting fired** — pods stayed Running/Ready throughout. Add a Prometheus alert on `sas-pool` capacity.
4. (Unrelated, observed during investigation) **`lake` pool is DEGRADED** — `scsi-SATA_HUH721212ALE601_8DGT7DMH` is in REMOVED state and needs `zpool online` or replacement.
