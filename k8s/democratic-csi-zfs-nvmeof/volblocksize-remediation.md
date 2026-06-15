# sas-pool Space Remediation Runbook

Follow-up to [storage01-saspool-capacity-exhaustion-readonly](../../incidents/storage01-saspool-capacity-exhaustion-readonly.md)
(2026-06-12 pool-full outage).

Two problems, three phases:

1. **Orphaned zvols** — ~2.2T (a third of the pool) is held by 21 zvols with no
   corresponding PV in the cluster, left behind by failed CSI deletions
   (`reclaimPolicy: Delete` didn't complete). Phase 0 reclaims this.
2. **RAIDZ padding amplification** — zvols default to 16K volblocksize; on the
   20-wide raidz3 (ashift=13) every block allocates ~3-4x its logical size.
   Phase 1 fixes new volumes; Phase 2 migrates existing ones.

Expected end state: pool drops from ~6.5T ALLOC to roughly 3.5T, and future
growth runs at 1.5x logical instead of 3-4x. (As of 2026-06-15: pool at **40%**
after Phase 0 + Loki/transcode/prometheus migrations.)

> **Note on deletions:** CSI does NOT auto-destroy a zvol on PVC delete — sanoid
> snapshots block it (see §0.5). Every PVC delete in this runbook requires the
> **"Deleting a CSI PVC"** snapshot-clearing step. This is a deliberate ongoing
> manual step (2026-06-15 decision), not a bug to route around.

---

## Phase 0 — Orphaned zvol cleanup (~2.2T, no app impact)

**Executed 2026-06-13**: 21 orphans destroyed (plus 5 stale nvmet subsystems
torn down and the persisted `/etc/nvmet/config.json` regenerated). Pool went
from 89% to 54% CAP (~2.5T reclaimed). Procedure kept below for reuse.

### 0.1 Regenerate the orphan list

Don't trust a stale list — PVCs come and go. Diff live state:

```sh
kubectl get pv -o jsonpath='{range .items[*]}{.metadata.name}{"\n"}{end}' | sort > /tmp/cluster-pvs.txt
ssh ubuntu@storage01.drewburr.com \
  'sudo zfs list -o name -H -r sas-pool/k8s/nvmeof/dataset | grep -oP "pvc-[a-f0-9-]+$"' \
  | sort > /tmp/storage-zvols.txt
comm -23 /tmp/storage-zvols.txt /tmp/cluster-pvs.txt
```

**WARNING — compare against ALL PVs, never filter the PV list by CSI driver.**
The zfs-nfs driver's `datasetParentName` also points at
`sas-pool/k8s/nvmeof/dataset`, so live NFS-backed datasets (e.g.
`plex/backups`) live in the same tree as the nvmeof zvols. A driver-filtered
PV list makes those look orphaned; this nearly destroyed live Plex backup
data on 2026-06-13. (Tell: NFS volumes are datasets, `VOLSIZE -`, while
nvmeof volumes are zvols.) Consider moving the zfs-nfs parent to its own
dataset to remove this trap.

As of 2026-06-12 this returned 21 orphans. Largest:

| zvol | USED |
|---|---|
| `pvc-f3c0fc39` | 494G |
| `pvc-895b8804` | 494G |
| `pvc-1163d2d3` | 186G |
| `pvc-7b45dc64` | 160G |
| `pvc-c475a27c` | 160G |
| `pvc-906f10ed` | 160G |
| `pvc-4f88c9c9` | 160G |
| `pvc-703ed7a0` | 159G |
| `pvc-2d22c9d1` | 159G |
| (12 more, ~100G combined) | |

### 0.2 Verify each candidate is truly dead

For each orphan, confirm nothing is connected to its NVMe-oF namespace and
peek at the contents before destroying:

```sh
# On storage01: is the zvol still exported / does any initiator hold it open?
sudo nvmetcli ls | grep -A3 <pvc-uuid>

# When was it last written?
sudo zfs get creation,used,referenced sas-pool/k8s/nvmeof/dataset/<pvc-uuid>

# Optional: mount a readonly clone to see what's inside
sudo zfs snapshot sas-pool/k8s/nvmeof/dataset/<pvc-uuid>@inspect
sudo zfs clone -o readonly=on sas-pool/k8s/nvmeof/dataset/<pvc-uuid>@inspect sas-pool/inspect-tmp
sudo mount -o ro /dev/zvol/sas-pool/inspect-tmp /mnt
# ... look around, then:
sudo umount /mnt && sudo zfs destroy -R sas-pool/k8s/nvmeof/dataset/<pvc-uuid>@inspect
```

Also remove the orphan's NVMe-oF subsystem config in nvmetcli if present, or
the kernel will keep referencing a destroyed zvol.

### 0.3 Quarantine, then destroy

Rename first; destroy a week later. A rename is instantly reversible, a
destroy is not:

```sh
# Quarantine (repeat per orphan)
sudo zfs rename sas-pool/k8s/nvmeof/dataset/<pvc-uuid> sas-pool/k8s/nvmeof/quarantine/<pvc-uuid>

# After a week of nothing breaking:
sudo zfs destroy -r sas-pool/k8s/nvmeof/quarantine/<pvc-uuid>
```

(Create the parent once: `sudo zfs create sas-pool/k8s/nvmeof/quarantine`.
Renaming does not free space — only the destroy does.)

### 0.4 Why orphans accumulate — root cause found (2026-06-12)

`/root/.nvmetcli/prefs.bin` on storage01 was a 0-byte file (corrupt since
2026-05-19), which made every `nvmetcli` invocation crash on startup
(`EOFError: Ran out of input` unpickling configshell prefs). Since the CSI
driver shells out to nvmetcli for both CreateVolume and DeleteVolume, all
PVC provisioning AND deletion failed silently from May 19 onward —
deletions left orphaned zvols.

Fixed by moving the corrupt file aside (`prefs.bin.corrupt`); nvmetcli
regenerates it. Full create→delete lifecycle verified working 2026-06-12.

If orphans reappear, check `sudo nvmetcli ls /` works on storage01 first,
then democratic-csi controller logs. Consider symlinking prefs.bin to
/dev/null like history.txt/log.txt already are. Re-run the 0.1 diff
occasionally (or alert on it). Note: orphans from before May 19 predate
this bug and had some other cause.

### 0.5 Second orphan cause — sanoid snapshots block CSI delete (ONGOING)

Even with nvmetcli healthy, **every CSI PVC deletion fails on its own** because
sanoid takes an hourly autosnap of every zvol under `sas-pool/k8s/nvmeof/dataset`
(see `/etc/sanoid/sanoid.conf`: `recursive=yes`, `hourly=1`). democratic-csi's
`DeleteVolume` runs a **non-recursive** `zfs destroy`, which fails with:

```
GrpcError code=9 "filesystem has dependent snapshots"
```

The PV is then stuck `Released` and the controller retries forever — the zvol is
orphaned and its space never returns. This is what generated the bulk of the 2.2T
orphan pile, and it fires on EVERY delete (migrations, scale-downs, decommissions).

**Decision (2026-06-15): sanoid left as-is** (the hourly snap is a wanted 1-hour
rollback net). We accept that PVC deletion requires a manual snapshot-clearing
step — see the **"Deleting a CSI PVC"** procedure below. Do not skip it; skipping
silently orphans the zvol.

(Alternatives considered and rejected: disabling sanoid autosnap on this dataset
— loses the rollback net; forcing CSI recursive destroy — risks nuking
CSI-managed VolumeSnapshots. If the manual step becomes too painful, revisit.)

---

## Deleting a CSI PVC (REQUIRED procedure — clears blocking snapshots)

Any time you delete a `zfs-nvmeof` PVC (migration, decommission, cleanup), the
backing zvol will **not** be destroyed by CSI on its own — sanoid's hourly
snapshot blocks the non-recursive `zfs destroy` (see 0.5). You must clear the
snapshot so CSI's retry can complete. Two equivalent ways:

**Preferred — let CSI finish its own teardown** (also tears down the nvmet export
cleanly). Delete the PVC, then destroy only the blocking snapshot(s):

```sh
PV=$(kubectl get pvc <name> -n <ns> -o jsonpath='{.spec.volumeName}')
kubectl delete pvc <name> -n <ns> --wait=false      # PV -> Released, CSI retries (and fails on snapshot)
ssh ubuntu@storage01.drewburr.com \
  "for s in \$(sudo zfs list -H -t snapshot -o name sas-pool/k8s/nvmeof/dataset/$PV 2>/dev/null); do sudo zfs destroy \"\$s\"; done"
# within ~1 retry cycle CSI completes: nvmet unexport + zvol destroy + PV removed
```

Verify it actually went away (don't assume):

```sh
kubectl get pv $PV 2>&1 | tail -1                                            # NotFound = good
ssh ubuntu@storage01.drewburr.com "sudo zfs list sas-pool/k8s/nvmeof/dataset/$PV 2>&1 | tail -1"  # 'does not exist'
```

**Fallback — PV is `Retain`, or you already manually own cleanup.** Then CSI
won't reclaim it; do the whole teardown by hand (this is the Phase-0 sequence):
tear down the nvmet subsystem, regenerate the persisted config, `zfs destroy -r`,
delete the PV. See Phase 0.2/0.3 and the prometheus-db cleanup
(2026-06-15) for the full sequence.

> Watch for fresh snapshots: sanoid may snap again between your clear and CSI's
> retry. If the zvol lingers, re-check for snapshots and clear again.

---

## Phase 1 — Fix volblocksize for new volumes (one secret, zero risk)

The change is already in this repo: `secrets/secrets.yaml` sets
`zvolBlocksize: "64K"` (was `null` → ZFS default 16K).

Why 64K: at ashift=13 on the 20-wide raidz3, 64K = 8 data + 3 parity + 1 pad
sectors = 1.5x amplification (vs 4x at 16K), while keeping read-modify-write
amplification tolerable for the SQLite-ish workloads (Plex metadata, Crafty).
128K would be 1.25x but doubles RMW cost; revisit only if a bulk-data storage
class is ever split out.

Apply (this secret is managed manually, not by ArgoCD — it lives outside
`templates/`):

```sh
kubectl apply -f secrets/secrets.yaml
# restart the controller so it rereads the driver config
kubectl rollout restart deployment -n democratic-csi-zfs-nvmeof democratic-csi-zfs-nvmeof-controller
```

Verify with a throwaway PVC:

```sh
kubectl apply -f examples/  # or any 1Gi PVC with storageClassName: zfs-nvmeof
ssh ubuntu@storage01.drewburr.com 'sudo zfs get volblocksize sas-pool/k8s/nvmeof/dataset/<new-pvc-uuid>'
# expect: volblocksize 64K
```

Note: `secrets/bak.yaml` is a stale dump of the pre-change secret — don't
re-apply it.

---

## Phase 2 — Migrate existing in-use volumes (per-app downtime)

Existing zvols keep 16K forever; volblocksize is fixed at creation.
**`zfs send/recv` does not help — it preserves the source volblocksize.**
Data must be copied at the file level into a freshly provisioned PVC.

### Triage

Only migrate volumes where physical USED is large. List the current
offenders (run after Phase 0 so orphans don't pollute the list):

```sh
ssh ubuntu@storage01.drewburr.com \
  'sudo zfs list -o name,used,volsize -s used -r sas-pool/k8s/nvmeof/dataset | tail -15'
```

**Completed migrations (all 64K, old zvols destroyed):**

| volume | done | reclaim |
|---|---|---|
| Loki stack (7 PVCs: write/backend/minio) | 2026-06-13 | recreated empty (logs discardable) |
| `plex/transcode-large` (506G→0) | 2026-06-15 | ~580G (scratch, recreated empty) |
| `kube-prometheus-stack/prometheus-db` (382G→90G) | 2026-06-15 | ~292G (data copied, 92d history preserved) |

Pool went 97% → **40%** across Phase 0 + these. **Remaining 16K targets** (by
physical size), as of 2026-06-15:

| PVC | Namespace | Size | Physical | notes |
|---|---|---|---|---|
| `crafty-backups` | `minecraft-jinkies` | 429G | 1185G | real data copy (actual backups) |
| `plex/plex-config` | `plex` | 86G | 262G | RMW-sensitive SQLite — keep 64K |
| `crafty-servers` ×3 | underground/derailed/jinkies | 54–107G | 117–155G | data copy |

Everything else is small enough to ignore; it ages out as apps get rebuilt.

### Per-volume procedure

The swap keeps the original PVC name so GitOps manifests stay untouched.

1. **Scale the app down.** Disable ArgoCD auto-sync for the app first so it
   doesn't fight you, then scale the StatefulSet/Deployment to 0.
   - **Operator/ApplicationSet-managed apps** (e.g. `prometheus`): a `paused`
     patch or a `kubectl scale` gets reverted within seconds. The `prometheus`
     Application has `selfHeal:true` AND is generated by an ApplicationSet, so
     disabling auto-sync on the Application alone isn't enough — suspend at the
     **ApplicationSet** (or parent app) level first, then pause the operator CR.
     During the 2026-06-15 prometheus migration this reconcile un-paused the
     operator mid-flight and briefly restarted the pod on the old PVC.
   - **RWO single-replica** workloads need a true scale-to-0 (not a rolling
     restart) — the old pod holds the volume, so the new pod can't mount it.
   - **Stale mounts:** after the pod terminates, kubelet sometimes leaves the
     CSI globalmount (or dead-pod bind mounts) behind. CSI's next stage is
     idempotent and will reuse a stale mount, handing the new pod a read-only or
     wrong volume. Check `grep <pvc-uuid> /proc/mounts` on the node and
     `umount`/`umount -l` any leftovers (no VolumeAttachment = safe to unmount)
     before bringing the app back.

2. **Create a temp PVC** (gets 64K automatically post-Phase 1):

   ```yaml
   apiVersion: v1
   kind: PersistentVolumeClaim
   metadata:
     name: <orig-name>-migrate
     namespace: <ns>
   spec:
     accessModes: [ReadWriteOnce]
     storageClassName: zfs-nvmeof
     resources: { requests: { storage: <same-size> } }
   ```

3. **Copy** with a utility pod mounting both PVCs:

   ```yaml
   apiVersion: v1
   kind: Pod
   metadata: { name: pvc-migrate, namespace: <ns> }
   spec:
     restartPolicy: Never
     containers:
     - name: copy
       image: instrumentisto/rsync-ssh
       command: ["rsync", "-aHAX", "--info=progress2", "/old/", "/new/"]
       volumeMounts:
       - { name: old, mountPath: /old }
       - { name: new, mountPath: /new }
     volumes:
     - { name: old, persistentVolumeClaim: { claimName: <orig-name> } }
     - { name: new, persistentVolumeClaim: { claimName: <orig-name>-migrate } }
   ```

   Wait for `Completed`, spot-check file counts/sizes, then delete the pod.

4. **Swap the PV under the original PVC name:**

   ```sh
   NEWPV=$(kubectl get pvc <orig-name>-migrate -n <ns> -o jsonpath='{.spec.volumeName}')

   # keep the new PV when its temp PVC goes away
   kubectl patch pv $NEWPV -p '{"spec":{"persistentVolumeReclaimPolicy":"Retain"}}'
   kubectl delete pvc <orig-name>-migrate -n <ns>
   kubectl patch pv $NEWPV --type json -p '[{"op":"remove","path":"/spec/claimRef"}]'   # Released -> Available

   # delete the old PVC -- CSI will NOT destroy the old 16K zvol by itself;
   # follow the "Deleting a CSI PVC" procedure above to clear its sanoid
   # snapshot, or the old zvol orphans and you reclaim nothing.
   kubectl delete pvc <orig-name> -n <ns> --wait=false
   OLDPV=<old-pvc-uuid>
   ssh ubuntu@storage01.drewburr.com \
     "for s in \$(sudo zfs list -H -t snapshot -o name sas-pool/k8s/nvmeof/dataset/$OLDPV 2>/dev/null); do sudo zfs destroy \"\$s\"; done"

   # rebind the original name to the new PV
   cat <<EOF | kubectl apply -f -
   apiVersion: v1
   kind: PersistentVolumeClaim
   metadata: { name: <orig-name>, namespace: <ns> }
   spec:
     accessModes: [ReadWriteOnce]
     storageClassName: zfs-nvmeof
     volumeName: $NEWPV
     resources: { requests: { storage: <same-size> } }
   EOF

   kubectl patch pv $NEWPV -p '{"spec":{"persistentVolumeReclaimPolicy":"Delete"}}'
   ```

5. **Scale the app back up**, verify it's healthy and writing, re-enable
   ArgoCD auto-sync.

6. **Confirm the old zvol is gone** on storage01 (this is exactly the failed
   deletion path from Phase 0.4 — check it actually deleted):

   ```sh
   ssh ubuntu@storage01.drewburr.com 'sudo zfs list -r sas-pool/k8s/nvmeof/dataset | grep <old-pvc-uuid>'
   # expect: no output
   ```

---

## Verification / exit criteria

- `zpool list sas-pool` CAP at or below ~50% after Phases 0+2. ✅ (40% as of 2026-06-15)
- New PVCs show `volblocksize 64K` on storage01. ✅
- Orphan diff (0.1) returns empty.
- ✅ Pool-capacity alert is live: Grafana `ZfsPoolCapacityHigh` (folder Spud,
  group `storage.zfs`), fed by a `zpool list` textfile collector on storage01
  (`/usr/local/bin/zpool-textfile-collector.sh` + systemd timer) emitting
  `zpool_capacity_ratio`. Warns >80% → drewburr-labs Discord. Covers all pools
  (also catches `lake` DEGRADED at 86%).
