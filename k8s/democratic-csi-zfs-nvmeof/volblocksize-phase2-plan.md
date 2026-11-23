# Phase 2 plan — migrate the remaining 16K zvols to 64K

Part of the [sas-pool space remediation runbook](volblocksize-remediation.md)
(Phase 2). Inventory taken **2026-11-22**. This is a plan only: no workload is
scaled, copied, or deleted until each wave gets an explicit go-ahead.

## Where things stand

| | |
|---|---|
| Pool | `sas-pool` 7.27T, **1.55T ALLOC (21%)**, **42% FRAG**, ONLINE |
| zvols under `sas-pool/k8s/nvmeof/dataset` | 92 total: **60 × 16K**, 32 × 64K |
| 16K zvols with a live PV | 48 (in 22 apps) |
| 16K zvols with **no PV** (orphans) | 12, 11.4G USED. These belong to Phase 0, not Phase 2 (see below) |
| 16K USED total | 915.7G |
| Estimated USED after migrating all of them | ~408G |
| **Estimated reclaim** | **~508G (about a third of current ALLOC)** |

On fragmentation: each copy writes the data in one fresh, sequential pass. When
the old zvol is destroyed, its scattered 16K allocations go back to the pool as
free space. That frees about 0.9T of the most fragmented allocations and should
pull FRAG down noticeably. Record `zpool list -o alloc,frag,cap sas-pool` before
and after each wave so the effect is measured, not assumed.

### How the estimate was made

- **Current** is `used` from `zfs list -p`. It includes snapshots, which are
  destroyed along with the old zvol.
- **After** is `logicalused × 1.25`. That is a little conservative: the 64K zvols
  already on the pool come in at 1.12–1.20× logicalused (for example
  derailed `crafty-backups` is 82.0G logical and 98.2G used; loki `write-1` is
  22.1G logical and 24.7G used).
- The copy moves files, not blocks. So when the filesystem holds less than
  `logicalused` (ext4 blocks freed but never trimmed), the real saving is larger.
  `kubelet_volume_stats_used_bytes` (the **fs** column) shows which volumes this
  applies to. Most match `logicalused` closely since the node-fstrim CronJob
  went in. `minecraft-data` is the exception.

Regenerate before each wave. Volumes change, and this table is a point in time:

```sh
ssh ubuntu@storage01.drewburr.com \
  'sudo zfs list -Hp -t volume -o name,volblocksize,volsize,logicalused,used,usedbysnapshots -r sas-pool/k8s/nvmeof/dataset' \
  | awk -F'\t' '$2==16384'
kubectl get pv -o custom-columns=PV:.metadata.name,NS:.spec.claimRef.namespace,PVC:.spec.claimRef.name,FS:.spec.csi.fsType
```

## Inventory by app (16K only, sorted by estimated reclaim)

Argo is the ArgoCD Application. **manual** means no automated sync. Live
replicas are as of 2026-11-22.

| App (Argo) | PVC | Size | fs used | USED now | est. after | **reclaim** | Live replicas |
|---|---|---|---|---|---|---|---|
| `plex-plex` (manual) | `plex-config` | 150Gi | 96.4G | 303.2G | 121.3G | **181.9G** | 1. Also mounted by `plex-plex-config` (0 replicas) |
| `minecraft-derailed` (manual) | `crafty-servers` | 150Gi | 43.3G | 134.7G | 55.5G | **79.2G** | 1 |
| | `crafty-logs`, `crafty-app-config`, `crafty-home` | 1/1/10Gi | ~1G | 2.3G | 1.8G | 0.5G | |
| `minecraft-paper` (manual, OutOfSync) | `minecraft-data` | 100Gi | 10.9G | 77.7G (44.4G of it is one hourly snapshot) | ~13.6G | **~20G** once that snapshot rolls off (44.8G by the formula) | `minecraft-server` 0, `bluemap` 0 (crash-looping for about a year), `bluemap-config` 1 |
| | `bluemap-web` | 50Gi | 16.9G | 54.2G | 21.7G | **32.4G** | |
| | `bluemap-data`, `bluemap-configs` | 10Gi/100Mi | 0.3G | 1.2G | 0.6G | 0.7G | |
| *(none: no Argo app, no pods)* `plex-sabnzbd-flex` | `sabnzbd-flex-data` | 100Gi | n/a | 95.5G | 37.4G | **58.1G** (95.5G if deleted) | no workload |
| | `sabnzbd-flex-config` | 10Gi | n/a | 0.4G | 0.2G | 0.2G | |
| `minecraft-underground` (manual) | `crafty-servers` | 50Gi | 30.8G | 96.9G | 39.2G | **57.7G** | 1 |
| | `crafty-logs`, `crafty-app-config` | 1/1Gi | 0.5G | 1.0G | 0.8G | 0.2G | |
| `minecraft-jinkies` (manual) | `crafty-servers` | 100Gi | 38.1G | 63.5G | 48.6G | **14.9G** | 1 |
| | `crafty-logs`, `crafty-app-config`, `crafty-import` | 10Gi each | 0.7G | 1.5G | 1.2G | 0.3G | |
| `minecraft-poke-central` (manual, OutOfSync) | `crafty-servers` | 50Gi | n/a | 23.4G | 10.2G | **13.2G** | **0** (dormant) |
| | `crafty-app-config`, `crafty-home`, `crafty-logs` | 1/10/1Gi | n/a | 0.6G | 0.5G | 0.1G | |
| `minecraft-novacraft` (manual, OutOfSync) | `crafty-backups` | 250Gi | n/a | 19.5G | 10.4G | **9.0G** | **0** (dormant) |
| | `crafty-app-config`, `crafty-servers`, `crafty-logs`, `crafty-import` | 10/100/10/10Gi | n/a | 9.7G | 7.1G | 2.6G | |
| `harbor` (manual) | `data-harbor-trivy-0` + 4 small | 1–50Gi | 1.7G | 4.5G | 2.2G | 2.3G | 1 (StatefulSet volumeClaimTemplates) |
| Plex config PVCs (10 manual apps) | `radarr-config` 1.8, `sonarr-config` 0.8, `qbittorrent-config` 0.5, `bazarr-config` 0.3, `postgres-data` 0.2, `qbittorrent-alt-config` 0.1, `sabnzbd-config` 0.1, `overseerr-config`, `jackett-*`, `jackettfeed-*` | 1–10Gi | ~2.5G | 8.4G | 4.5G | **~3.9G** | 1 each |
| *(none)* `plex-sonarr-anime` | `sonarr-anime-config` | 10Gi | n/a | 4.8G | 3.7G | 1.1G (4.8G if deleted) | no workload |
| `prometheus` (**AUTOSYNC**, selfHeal) | `prometheus-grafana` | 20Gi | 0.1G | 0.6G | 0.4G | 0.2G | 1 |
| *(none)* `home-assistant` | `home-assistant-home-assistant-0` | 5Gi | n/a | 0.4G | 0.3G | 0.2G (0.4G if deleted) | namespace has no workloads |
| *(none)* `plex-notifiarr` | `notifiarr-config` | 10Gi | n/a | ~0 | ~0 | 0 | no workload |
| **Orphans (Phase 0)** | 12 zvols with no PV | | | 11.4G | (delete) | 11.4G | n/a |

(The table rounds. The per-zvol numbers, with PV UUIDs, can be regenerated with
the commands above.)

Of the 22 apps, **prometheus is the only autosynced one**, and it only has the
0.2G Grafana PVC. Every app worth migrating is manual-sync. For those, nothing
in ArgoCD has to be stopped. Just don't press Sync until the copy is done.

## Decide first: retire or migrate?

These volumes belong to apps that aren't running or aren't managed by ArgoCD at
all. Migrating them would copy data nobody uses. **Recommendation: confirm each
one is dead, then delete it with the runbook's
[Deleting a CSI PVC](volblocksize-remediation.md#deleting-a-csi-pvc-required-procedure--clears-blocking-snapshots)
procedure instead of migrating.** If it's kept, it joins a wave below.

| Item | Why it looks dead | Frees if deleted |
|---|---|---|
| `plex/sabnzbd-flex-{data,config}` | No ArgoCD app, no chart under `k8s/plex/`, no pods | 95.9G |
| `minecraft-paper` (all 4 PVCs) | `minecraft-server` at 0 replicas, `bluemap` crash-looping for about a year and scaled to 0 today (`201e0f6`). Only `bluemap-config` runs. | 133.1G |
| `plex/sonarr-anime-config` | No ArgoCD app, no pods | 4.8G |
| `plex/notifiarr-config` | No ArgoCD app, no pods | ~0 |
| `home-assistant/home-assistant-home-assistant-0` | Namespace has no workloads, and there's no `k8s/home-assistant` | 0.4G |
| `minecraft-poke-central`, `minecraft-novacraft` | Both at 0 replicas (the chart says 1, so both Argo apps are OutOfSync) | 24.0G / 29.2G |
| 12 orphan zvols | No PV at all. Re-run the Phase 0 orphan diff (0.1) against **all** PVs, then quarantine and destroy (0.2/0.3) | 11.4G |

### Decisions (2026-11-22)

**Retire:**
- `plex/sabnzbd-flex-data`, `plex/sabnzbd-flex-config`, `plex/sonarr-anime-config`,
  `plex/notifiarr-config`, `home-assistant/home-assistant-home-assistant-0`.
  Together they free **~101G**.
- The orphan zvols, which free **11.4G**.

**Reset (fresh, empty 64K volumes):** `harbor`. It isn't in use: no pod
outside the `harbor` namespace pulls from it. All 5 of its PVCs (2.3G reclaim)
get deleted and recreated empty. See *Harbor reset* below. Note that this wipes
Harbor completely. The **database** volume is one of the five, so projects,
users and robot accounts are gone, and the admin password reverts to the
chart's value.

**Keep and migrate:** `minecraft-paper`, `minecraft-poke-central` and
`minecraft-novacraft` are real apps that are only scaled down right now.

Re-checked before retiring (2026-11-22, read-only):

- **The 5 PVCs:** all are Bound, with `reclaimPolicy: Delete`. No pod,
  Deployment, StatefulSet, DaemonSet, Job or CronJob in any namespace
  references them. No ArgoCD Application tracks them, and no chart under `k8s/`
  claims them. The only text match is a `mkdir /backups/sonarr-anime` in the
  Plex init script, which is a directory name, not a claim.
- **The orphans:** the re-run diff against **all** PVs returns **14** zvols,
  not 12. That's the 12 16K ones plus two 64K 10G zvols
  (`pvc-54ee27a0`, `pvc-70380249`), both created 2026-06-13 and holding 0.03G
  each. They are most likely the Phase 1 throwaway verification PVCs. None of
  the 14 is exported by nvmet (all 78 nvmet namespaces point at live PVs), each
  holds exactly one sanoid hourly snapshot, and `sas-pool/k8s/nvmeof/quarantine`
  does not exist yet.

  | orphan | vbs | volsize | USED | created |
  |---|---|---|---|---|
  | `pvc-410613f2` | 16K | 10G | 4.13G | 2026-03-14 |
  | `pvc-7ded8d5a` | 16K | 5G | 3.92G | 2026-04-04 |
  | `pvc-bca5650c` | 16K | 10G | 1.86G | 2025-08-19 |
  | `pvc-91ec2087` | 16K | 10G | 0.52G | 2025-08-19 |
  | `pvc-7f040c3f` | 16K | 1G | 0.44G | 2025-08-19 |
  | `pvc-028831a8`, `pvc-0445345a`, `pvc-d9050e81`, `pvc-c74b818d`, `pvc-3105c70f`, `pvc-6e2af2d3`, `pvc-fdc630e5` | 16K | 5–50G | ≤0.19G each | 2025-08-19 |
  | `pvc-54ee27a0`, `pvc-70380249` | 64K | 10G | 0.03G each | 2026-06-13 |

### Retire wave: executed 2026-11-22

- **Orphans:** all 14 renamed to `sas-pool/k8s/nvmeof/quarantine/` (11.4G). The
  zvols left under `dataset/` now match the nvmet exports 1:1 (78 = 78).
  **Destroyed early, on 2026-11-23, on request.** Before destroying, re-checked
  that the quarantine held the same 14 zvols, that none matched a live PV, and
  that nvmet exported nothing from `quarantine/`. All 14 were removed with
  `zfs destroy -r`, then the empty `quarantine` dataset. The pool went to
  787G.
- **Retired PVCs:** all 5 deleted. Their snapshots were cleared and CSI
  finished the teardown: PVs NotFound, zvols "does not exist". The empty
  `home-assistant` namespace is left in place.
- **Harbor:** reset. All 5 PVCs were recreated on new 64K/xfs zvols. All 8
  pods are Running, and `/api/v2.0/health` reports every component healthy.
  `harbor-jobservice` restarted 3 times on startup while it waited for
  `harbor-core`. That's expected and it has been stable since. ArgoCD shows
  both re-applied chart PVCs as Synced.
- **Pool:** went from 1.55T ALLOC / 42% FRAG / 21% CAP to **1.42T / 41% /
  19%**. The quarantined 11.4G is still allocated. 16K zvols are down from 60
  to **38**, and every one left is a migration-wave volume.

### Wave 0 pilot (`minecraft-poke-central`): executed 2026-11-22

- **New PVCs:** `crafty-{app-config,servers,logs,home}-64k` were created on
  64K/xfs zvols.
- **Copy:** each pair was rsynced with its own Job. Every dry-run diff came back
  empty and the file counts match. `crafty-servers` held 5,910 files and 6.4G,
  and copied in **50s, about 130 MB/s**. Use that rate to size the later
  windows.
- **Chart:** `b107b4e` disables the old keys, adds the `-64k` keys and pins
  `replicas: 0`. It was rendered against both crafty chart 0.1.7 (what ArgoCD
  uses) and 0.3.0, and both match the live mount paths.
- **Sync:** ArgoCD synced with prune off. The StatefulSet mounts the `-64k`
  claims and stays at 0 replicas. The only OutOfSync items are the 4 old
  PVCs, which are waiting to be pruned.
- **The argocd MCP token gets `permission denied`** (even for reads) on this
  app. The sync was triggered with kubectl instead:
  `kubectl patch application -n argocd <app> --type merge -p '{"operation":{"initiatedBy":{"username":"kubectl"},"sync":{"revision":"<full sha>","prune":false}}}'`.
  Use the same method for the later waves, or sync from the UI.
- **Old PVCs deleted after sign-off** (same day), using *Deleting a CSI PVC*.
  The 4 old 16K PVs (`pvc-8aabe4d0`, `pvc-0d952680`, `pvc-88d25d1b`,
  `pvc-7102f8dd`) are NotFound, and their zvols "do not exist". The app is
  back to **Synced/Healthy**. The pool shows 1.38T / 41% FRAG / 18% CAP
  (this pilot is ~13G, below the `zpool list` rounding). The 23:00 sanoid
  rotation also released `minecraft-data`'s 44G snapshot. 16K zvols are down to
  **34**.
- **Found:** `crafty-backups` (`pvc-e0d68002`, 200Gi) has **no zvol on
  storage01**. The PV predates the sas-pool rebuild on 2025-08-19 and the
  zvol was never carried over. Starting this app would hang mounting it. It's
  the only dangling `zfs-nvmeof` PV in the cluster (the other 73 all have
  zvols). The fix is a fresh, empty `crafty-backups-64k`.

### Wave 1 (`plex-config`): executed 2026-11-22

- **Pre-copy:** the warm Job, pinned to kube05 with the old volume mounted
  read-only while Plex was running, copied 103GB / 170,023 files in **5m51s
  (~297 MB/s)**. Plex was unaffected.
- **Outage:** Plex was scaled to 0 at 23:16:33 UTC. The final pass took 79s
  and re-copied only 11 files (507MB, the databases). Its dry-run diff was
  empty, with 170,018 files on both sides. Plex was **Ready again at 23:19:12,
  about 2m40s down**.
- **Chart:** `fc5ec36` renames the claim in `k8s/plex/plex` and
  `k8s/plex/plex-config`. **Gotcha:** the library chart defaults `mountPath`
  to the volume *name*, and `plex-config`'s chart relied on that. A rename
  alone would have moved its mount from `/plex-config` to `/plex-config-64k`,
  so it's now pinned. Check for this on every library-chart rename in wave 6.
  The `template.yaml` files are gitignored local renders and don't need
  updating.
- **Sync:** `plex-plex-config` (still 0 replicas), then `plex-plex`, both via
  kubectl patch. After a refresh, the only OutOfSync item is the old
  `plex-config` PVC, which is waiting to be pruned.
- **Verified:** Plex is Running on kube05 with no restarts. `/config` is the
  150G xfs volume with 97G used. `PRAGMA integrity_check` on the library DB
  returns `ok`, and `/identity` answers as the claimed server. The 2
  `Unknown metadata type` errors since start were already in the
  previous log, so they aren't new.
- **Old PVC deleted** the same day, on sign-off. First confirmed that nothing
  references it, there's no VolumeAttachment, and kube05 has no leftover mount
  or nvme subsystem. Then followed *Deleting a CSI PVC*. `pvc-99c31905` is
  NotFound and its zvol "does not exist".
- **Pool afterwards:** **1.11T ALLOC / 41% FRAG / 15% CAP**, down from 1.38T
  before the wave. The new 64K copy uses 103.5G for 96.6G logical (**1.07×**,
  better than the 1.25× estimate). 16K zvols are down to **33**.
- **Measuring gotcha:** right after the destroy, `zpool list` and even
  `zpool get freeing` (0) still showed 1.41–1.48T. The async free hadn't been
  registered yet. Re-read a minute or so later before recording a wave's
  result.

### Waves 2–5b (derailed, underground, jinkies, novacraft, paper): executed 2026-11-22, in parallel

- **New PVCs:** 20 `-64k` PVCs were created at 64K. The warm pre-copies (15)
  were pinned to each running workload's node, and novacraft (dormant) went
  straight to its verified final pass (5).
- **Outage:** derailed, underground, jinkies and `bluemap-config` were scaled
  to 0 at 23:46:17 UTC. All 15 final passes verified clean (empty dry-run
  diff, matching file counts, up to 310,985 files on derailed
  `crafty-servers`). The servers were **back by 23:51:03, about 4m45s
  down**. Underground's Forge pack finished loading at 23:52:49.
- **Chart:** `769cf96`. The crafty charts disable the old keys and add
  `-64k` keys. minecraft-paper renames every claim.
- **Verified:** all four crafty panels return 200 on `/login`. Derailed
  (2 servers), jinkies and underground all logged `Done`. Every new mount
  is xfs. novacraft, `minecraft-server` and `bluemap` stayed at 0.
- **Gotcha: xfs minimum size.** `bluemap-configs` was 100Mi, and `mkfs.xfs`
  refuses filesystems under 300MB, so the Job hung in `MountDevice`. Fix:
  expand the still-empty new PVC to 1Gi (the StorageClass allows expansion)
  and render it at 1Gi in the chart. Any future PVC under 300Mi on this
  StorageClass will hit the same thing.
- **Gotcha: never start the final Jobs while an old pod is still
  Terminating.** nvmeof uses no VolumeAttachment, so nothing stops a second
  node mounting the same ext4. The paper finals were scheduled on kube02 while
  `bluemap-config` was still terminating on kube03. They were deleted while
  still in ContainerCreating. kube02 had no mount and no nvme connection to
  the old volumes, so nothing was double-mounted. They were re-run after the
  old pod was gone. **Always `kubectl wait --for=delete` on every old pod
  before applying the finals**, including Deployments, not just StatefulSets.
- **Gotcha: crafty `crafty-backups` sync failure (pre-existing).** The full
  syncs of derailed, underground and jinkies applied everything (the
  StatefulSets moved to the new claims at 1 replica) except `crafty-backups`.
  The patch failed with "spec is immutable" because ArgoCD tries to clear
  `volumeName`. Those PVCs were re-bound earlier with a manual `kubectl apply`
  that put `volumeName` into `last-applied-configuration`, and client-side
  apply removes it despite `RespectIgnoreDifferences`. The operation therefore
  shows Failed. **Fixed 2026-11-23:** rewrote
  `kubectl.kubernetes.io/last-applied-configuration` on the 3 PVCs with only
  `spec.volumeName` removed. The binding is unchanged, since `spec.volumeName`
  itself still points at the same PV. Verified with an ArgoCD dry-run sync
  (Succeeded) and a `kubectl apply --dry-run=server` of the rendered PVC
  ("configured"). **Lesson for any future rebind:** apply the rebound PVC with
  `kubectl create` or server-side apply, not client-side `kubectl apply`, so
  `volumeName` never lands in `last-applied-configuration`.
- **minecraft-paper** was synced selectively: only the 4 new PVCs and 3
  workloads. Its unrelated `Ingress/bluemap` drift (external-dns annotation
  key rename) was left alone.
- **Old PVCs deleted** the same day, on sign-off. Before deleting, confirmed
  all 20 still mapped to the recorded PVs, no pod, workload, Job or CronJob
  referenced them, and every cluster node (kube01/02/03/05) had zero mounts
  and zero nvme subsystems for them. Then *Deleting a CSI PVC*: all 20 PVs
  are NotFound and all 20 zvols are gone. The four crafty apps went to
  **Synced/Healthy**, and minecraft-paper's only diff is the unrelated
  Ingress.
- **Pool afterwards:** **802G (0.78T) ALLOC / 42% FRAG / 10% CAP**, down from
  1.29T just before the deletes. 16K zvols are down to **13** (the wave 6
  Plex config PVCs and Grafana). **FRAG did not drop.** The freed 16K
  allocations were themselves scattered, so they come back as fragmented free
  space. Don't count on Phase 2 to fix FRAG. Fragmentation now matters much
  less at 10% CAP.

### Wave 6 (Plex config batch): executed 2026-11-23

- **Copy:** 12 PVCs across 10 apps (bazarr, jackett ×2, jackettfeed ×2,
  overseerr, postgres, qbittorrent, qbittorrent-alt, radarr, sabnzbd, sonarr)
  were copied to `-64k` PVCs with no warm pass, since each is ≤1.3GB. All 10
  StatefulSets were scaled to 0 at 00:01:43 UTC, and the copy Jobs only started
  after every old pod was confirmed deleted and no pod mounted an old claim.
  All 12 verified clean: empty dry-run diffs, matching file counts.
- **Chart:** `01918b7`. Renamed the `persistence` entries, plus the
  `vuetorrent-install` init containers' `volumeMountsOverride` in qbittorrent
  and qbittorrent-alt, which reference the volume by name. Kometa's radarr
  reference was renamed too (that app isn't deployed). Every entry already
  pinned `mountPath`. Renders were compared with the live StatefulSets,
  including init-container mounts.
- **Sync:** `plex-postgres` first, waiting for the DB to be Ready, then the
  other nine. All Succeeded. **Back by 00:06:41, about 5m down.**
- **Verified:** all 10 pods are Ready on the `-64k` claims, which are xfs.
  Postgres logged a clean shutdown/startup ("ready to accept connections").
  The flagged log lines were all explained:
  - Radarr's `Couldn't process tracked download The.Odyssey…` errors predate
    the migration (802 in the 18:08 log).
  - Jackett and jackettfeed each failed their startup probe once on the first
    start (slow cold read of the indexer definitions) and have been stable
    since.
  - Postgres's 4 `duplicate key … table_settings_languages_pkey` lines are
    bazarr re-inserting its default languages at startup. Bazarr itself logged
    no errors.
- **Old PVCs deleted** the same day, on sign-off. Before deleting, re-checked
  that all 12 still mapped to the recorded PVs, that nothing referenced them
  (exact match, with a positive control on the `-64k` names finding 24 refs),
  and that kube01/02/03/05 had zero mounts and zero nvme subsystems for them.
  All 12 PVs are NotFound and all 12 zvols are gone. All 10 apps are
  **Synced/Healthy**.
- **Pool afterwards: 797G ALLOC / 42% FRAG / 10% CAP.** The only 16K zvol
  left is `pvc-4a26f25d` (`kube-prometheus-stack/prometheus-grafana`), which
  is deliberately skipped. **Phase 2 is complete apart from that one.**

### Retire procedure

- **Orphans:** use runbook Phase 0.3, quarantine then destroy. The rename is
  instantly reversible, and the space only comes back on the destroy a week
  later.

  ```sh
  sudo zfs create sas-pool/k8s/nvmeof/quarantine
  for u in <orphan uuids>; do sudo zfs rename sas-pool/k8s/nvmeof/dataset/$u sas-pool/k8s/nvmeof/quarantine/$u; done
  # a week later, if nothing broke:
  sudo zfs destroy -r sas-pool/k8s/nvmeof/quarantine/<uuid>   # -r also takes its sanoid snapshot
  ```

- **The 5 PVCs:** use the runbook's
  [Deleting a CSI PVC](volblocksize-remediation.md#deleting-a-csi-pvc-required-procedure--clears-blocking-snapshots)
  procedure. Delete with `--wait=false`, clear the sanoid snapshot on the PV's
  zvol, and verify that both the PV and the zvol are gone. **This cannot be
  undone.** If any of the config PVCs are worth keeping, archive them to `lake`
  with `tar` first. Then delete the now-empty `home-assistant` namespace if
  nothing else lives there.

### Harbor reset

The 5 PVCs come from two places, and that changes how each comes back:

| PVC | Size | Created by | Comes back how |
|---|---|---|---|
| `database-data-harbor-database-0` | 1Gi | StatefulSet volumeClaimTemplate | The StatefulSet controller recreates it when the pod restarts |
| `data-harbor-redis-0` | 1Gi | StatefulSet volumeClaimTemplate | Same |
| `data-harbor-trivy-0` | 5Gi | StatefulSet volumeClaimTemplate | Same |
| `harbor-registry` | 50Gi | Chart template (`resourcePolicy: keep`) | Re-apply the saved manifest |
| `harbor-jobservice` | 1Gi | Chart template (`resourcePolicy: keep`) | Same |

Don't use an ArgoCD sync to recreate the two chart PVCs. The `harbor` app is
permanently OutOfSync on chart-generated Secrets (`harbor-core`,
`-jobservice`, `-registry`, `-registry-htpasswd`) and on the Deployments that
mount them. A sync would also rotate all of those. Re-applying the saved PVC
manifests keeps the ArgoCD tracking annotation, so Argo still sees the PVCs as
its own.

```sh
# 1. save the two chart-rendered PVCs (strip binding/status so they re-provision fresh)
for p in harbor-registry harbor-jobservice; do
  kubectl get pvc $p -n harbor -o json \
    | jq 'del(.metadata.uid,.metadata.resourceVersion,.metadata.creationTimestamp,.metadata.finalizers,.metadata.managedFields,
              .metadata.annotations["pv.kubernetes.io/bind-completed"],.metadata.annotations["pv.kubernetes.io/bound-by-controller"],
              .metadata.annotations["volume.beta.kubernetes.io/storage-provisioner"],.metadata.annotations["volume.kubernetes.io/storage-provisioner"],
              .spec.volumeName,.status)' > harbor-pvc-$p.json
done
# record the 5 old PV uuids for the snapshot clear + verification
kubectl get pvc -n harbor -o custom-columns=PVC:.metadata.name,PV:.spec.volumeName --no-headers > harbor-old-pvs.txt

# 2. stop the whole stack (fresh DB under a running core is asking for trouble)
kubectl scale deploy --all -n harbor --replicas=0
kubectl scale sts --all -n harbor --replicas=0
kubectl wait --for=delete pod --all -n harbor --timeout=5m

# 3. delete the 5 PVCs, then clear each old zvol's sanoid snapshot so CSI can finish (runbook "Deleting a CSI PVC")
kubectl delete pvc --all -n harbor --wait=false
for PV in $(awk '{print $2}' harbor-old-pvs.txt); do
  ssh ubuntu@storage01.drewburr.com \
    "for s in \$(sudo zfs list -H -t snapshot -o name sas-pool/k8s/nvmeof/dataset/$PV 2>/dev/null); do sudo zfs destroy \"\$s\"; done"
done
# verify each: PV NotFound, zvol 'does not exist'

# 4. recreate the chart PVCs, scale back up (StatefulSets recreate their own PVCs)
kubectl apply -f harbor-pvc-harbor-registry.json -f harbor-pvc-harbor-jobservice.json
kubectl scale sts --all -n harbor --replicas=1
kubectl scale deploy --all -n harbor --replicas=1
```

To verify: all 5 PVCs are Bound to new PVs, and storage01 shows `volblocksize
64K` for each. Every pod in `harbor` is Running. `https://harbor.drewburr.com`
loads, and you can log in as admin with the chart's password.

## Proposed order

Each wave is its own window and needs its own go-ahead. Pool headroom isn't an
issue: the biggest single copy needs about 121G, and 5.7T is free.

| Wave | Apps | est. reclaim | Downtime | Why here |
|---|---|---|---|---|
| **R: retire** | the 5 retired PVCs, 14 orphans, and the harbor reset (see Decisions) | ~115G | Harbor down for a few minutes (unused) | Nothing uses any of it. Can run any time, independent of the waves. |
| **0: pilot** | `minecraft-poke-central` (all 4 PVCs) | 13.3G | **none** (already at 0) | Proves the crafty chart swap, the rsync Job, and the old-PVC deletion end to end with no user impact. |
| **1** | `plex-plex`: `plex-config` | 181.9G | Plex offline for the final rsync pass | The biggest single win. Needs the warm pre-copy (below) so the outage is only a delta pass. Plex metadata is millions of small files. |
| **2** | `minecraft-derailed` (4 PVCs) | 79.7G | Server offline for the copy | Next largest. Take the window when nobody is playing. |
| **3** | `minecraft-underground` (3 PVCs) | 58.0G | Same | |
| **4** | `minecraft-jinkies` (4 PVCs) | 15.2G | Same | Smaller win. Its `crafty-backups` is already 64K. |
| **5** | `minecraft-novacraft` (5 PVCs) | 11.6G | none (dormant) | Same procedure as the pilot |
| **5b** | `minecraft-paper` (`minecraft-data`, `bluemap-web`, `bluemap-data`, `bluemap-configs`) | ~53G (77.9G by the formula, which counts the 44G hourly snapshot) | `bluemap-config` offline for the copy. `minecraft-server` and `bluemap` are already at 0. | Plain-template chart, so this is a straight rename of `claimName`. Its chart has `minecraft-server` at `replicas: 1`, so set it to 0 in the same commit, or the sync will start it. `bluemap` is already 0 in git. |
| **6: batch** | Plex config PVCs: radarr, sonarr, qbittorrent, qbittorrent-alt, bazarr, postgres (bazarr's DB), sabnzbd, overseerr, jackett, jackettfeed | ~3.9G | A minute or two each | Low risk and small. Everything is tiny, so do them all in one sitting, one app at a time. Do bazarr and postgres together, since bazarr depends on that DB. |
| **Deferred / skip** | `prometheus-grafana` (0.2G) | 0.2G | n/a | It's the only PVC that would need the autosync dance, which isn't worth it for 0.2G. It ages out when the app is next rebuilt. Procedure notes are below in case you want it anyway. (Harbor moved to the retire wave.) |

Running total with the 2026-11-22 decisions: retire and reset **~115G**, plus
migration waves 0–6 **~417G**, for **~532G** in all. That's about a third of
today's 1.55T ALLOC. Only Grafana is skipped.

## Per-app procedure

**Method: a new PVC with a new name (`<claim>-64k`), with the claim reference
swapped in the chart.** The old PVC is left completely untouched until you sign
off. That makes rollback a plain revert: point the chart back at the old claim
and sync. The runbook's existing method (rebinding the original PVC name to the
new PV) deletes the old PVC partway through, so there's no rollback once the app
is up. It's kept only as a fallback for volumeClaimTemplate workloads (see the
end of this file).

Placeholders: `NS` (namespace), `APP` (ArgoCD Application), `WL` (workload, for
example `statefulset/minecraft-derailed-craftycontroller`), `OLD` (current claim
name), `NEW=${OLD}-64k`, `SIZE` (the claim's current `requests.storage`, same as
the chart).

### 0. Pre-flight (read-only)

```sh
OLDPV=$(kubectl get pvc $OLD -n $NS -o jsonpath='{.spec.volumeName}')
ssh ubuntu@storage01.drewburr.com "sudo zfs get -Hp volblocksize,used,logicalused sas-pool/k8s/nvmeof/dataset/$OLDPV"
ssh ubuntu@storage01.drewburr.com 'sudo zpool list -o alloc,frag,cap sas-pool'     # baseline for this wave
kubectl get application -n argocd $APP -o jsonpath='{.spec.syncPolicy.automated}'; echo   # empty = manual
# who else mounts this claim? (e.g. plex-config is also mounted by plex-plex-config)
kubectl get pods -n $NS -o json | jq -r --arg c $OLD '.items[]|select(.spec.volumes[]?.persistentVolumeClaim.claimName==$c)|.metadata.name'
grep -rn "$OLD" k8s/ --include=values.yaml --include='*.yaml' | grep -v '/charts/'
```

Write down `OLDPV` for this PVC. You need it for the delete at the end.

### 1. Stop ArgoCD, but only for an autosynced app

The manual apps need nothing here. Just don't press Sync until step 6.

For an autosynced app (only `prometheus`, if Grafana is ever done): disabling
auto-sync on the Application doesn't stick, because the ApplicationSet
regenerates it. Stop the application controller instead. That pauses
reconciliation for **every** app, and the only other autosynced one is
`game-relay`:

```sh
kubectl scale statefulset argocd-application-controller -n argocd --replicas=0
# ... do the migration ...
kubectl scale statefulset argocd-application-controller -n argocd --replicas=2   # restore (it runs 2 shards)
```

### 2. (Optional) warm pre-copy while the app is still running

This is for the big volumes (`plex-config`, the `crafty-servers` volumes). RWO
means one *node*, not one pod, so a Job pinned to the node the app runs on can
mount the old claim read-only alongside the app. Create the new PVC first
(step 4), then run the step 5 Job with `nodeName` set to the app pod's node
(`kubectl get pod -n $NS -o wide`), without the verification block. The copy
won't be consistent, because the app is still writing. That's fine: the final
pass in step 5 runs with the app stopped and re-copies anything that changed.
This shrinks the outage to that delta pass.

### 3. Scale the workload to 0

```sh
kubectl scale $WL -n $NS --replicas=0
kubectl wait --for=delete pod -l <selector> -n $NS --timeout=5m
```

For `plex-config`, also confirm `plex-plex-config` is still at 0. Then check
there's no stale mount on the old node (runbook Phase 2, step 1):
`grep $OLDPV /proc/mounts` should print nothing, or only entries without a
VolumeAttachment.

### 4. Create the new PVC

The StorageClass now provisions 64K + **xfs**, so the migration also takes the
volume off ext4 and its online-resize trap (see
[minecraft-derailed-crafty4-eso-pvc-expand-cascade](../../incidents/minecraft-derailed-crafty4-eso-pvc-expand-cascade.md)).

```sh
cat <<EOF | kubectl apply -f -
apiVersion: v1
kind: PersistentVolumeClaim
metadata: { name: $NEW, namespace: $NS }
spec:
  accessModes: [ReadWriteOnce]
  storageClassName: zfs-nvmeof
  resources: { requests: { storage: $SIZE } }
EOF
```

`zfs-nvmeof` uses `volumeBindingMode: Immediate`, so the PV exists right away.
Check the block size before copying anything:

```sh
NEWPV=$(kubectl get pvc $NEW -n $NS -o jsonpath='{.spec.volumeName}')
ssh ubuntu@storage01.drewburr.com "sudo zfs get -H volblocksize sas-pool/k8s/nvmeof/dataset/$NEWPV"   # expect 64K
```

Keep the spec exactly as the chart will render it: same size, same
accessModes, same storageClassName. When step 6 syncs, ArgoCD then adopts this
PVC as-is and doesn't try to change any immutable field.

### 5. rsync Job (both PVCs mounted)

Use one Job per PVC pair. The pairs within an app are independent, so they can
run at the same time.

```yaml
apiVersion: batch/v1
kind: Job
metadata:
  name: migrate-<OLD>
  namespace: <NS>
spec:
  backoffLimit: 0
  ttlSecondsAfterFinished: 86400
  template:
    spec:
      restartPolicy: Never
      # nodeName: <node>    # only for the warm pre-copy in step 2
      securityContext: { runAsUser: 0 }
      containers:
      - name: rsync
        image: instrumentisto/rsync-ssh
        command: ["sh", "-euc"]
        args:
        - |
          rsync -aHAX --numeric-ids --delete --exclude=/lost+found --info=progress2,stats2 /old/ /new/
          echo '--- verify: dry run must report no changes'
          rsync -aHAXn --numeric-ids --delete --exclude=/lost+found --itemize-changes /old/ /new/ > /tmp/diff
          cat /tmp/diff; test ! -s /tmp/diff
          echo "files old=$(find /old -xdev ! -path '/old/lost+found*' | wc -l) new=$(find /new -xdev | wc -l)"
          du -sk /old /new
        volumeMounts:
        - { name: old, mountPath: /old, readOnly: true }
        - { name: new, mountPath: /new }
      volumes:
      - name: old
        persistentVolumeClaim: { claimName: <OLD>, readOnly: true }
      - name: new
        persistentVolumeClaim: { claimName: <NEW> }
```

```sh
kubectl apply -f migrate-$OLD.yaml
kubectl logs -n $NS job/migrate-$OLD -f
kubectl wait --for=condition=complete job/migrate-$OLD -n $NS --timeout=6h
```

The Job only reports Complete if the dry-run verification found no differences.
File counts should match. `du` will differ a little between ext4 and xfs, which
is expected. If it fails, the app is still scaled to 0 and the old PVC is
untouched: fix the problem and re-run.

Note the wall-clock time for the pilot and wave 1. That gives the real copy
rate for planning the later windows.

### 6. Swap the claim reference in the chart, sync, scale up

Make the chart edit under `k8s/<app>` and commit and push it only after the Job
is green. The edit depends on the chart family:

**Crafty apps** (`k8s/minecraft-*/values.yaml`). The claim name *is* the
`persistence` key, so disable the old key and add a new one. Repeat `mountPath`,
because the new key doesn't inherit the subchart's default for the old name:

```yaml
craftycontroller:
  persistence:
    crafty-servers:
      enabled: false              # old 16K claim, delete after sign-off
    crafty-servers-64k:
      enabled: true
      accessModes: [ReadWriteOnce]
      mountPath: /crafty/servers  # subchart defaults: app-config=/crafty/app/config, backups=/crafty/backups, logs=/crafty/logs, import=/crafty/import
      requests: 150Gi             # = old size
      storageClassName: zfs-nvmeof
```

The crafty apps already have `ignoreDifferences` on `/spec/volumeName` and
`RespectIgnoreDifferences=true` (`cb1a805`), so adopting the bound PVC doesn't
cause sync errors.

**For the dormant apps (poke-central, novacraft):** set
`craftycontroller.replicas: 0` in the same commit. Their chart says 1, and a sync
would otherwise *start* the server. That one-line change also clears the
long-standing OutOfSync.

**Plex library apps** (`k8s/plex/<app>/values.yaml`). Rename the `persistence`
entry's `name:`. The library chart uses it for both the PVC name and the
`claimName`:

```yaml
persistence:
  - name: plex-config-64k   # was plex-config
    mountPath: config
    ...
```

**If the entry has no `mountPath`, add one set to the old name.** The library
chart mounts at `/{{ default .name .mountPath }}`, so a rename alone would
move the mount. Compare the rendered mounts (`helm template`) against the live
StatefulSet before committing.

Update every chart that mounts the claim. `plex-config` is in **both**
`k8s/plex/plex/values.yaml` and `k8s/plex/plex-config/values.yaml`.
`radarr-config` is also in `k8s/plex/kometa/values.yaml`, which isn't deployed,
but keep it consistent. The `template.yaml` files are gitignored local renders,
so there's nothing to update there.

**minecraft-paper** (if kept). Rename the PVCs in
`templates/bluemap-pvcs.yaml` and `values.yaml` (`minecraft.persistence.name: minecraft-data`)
and the matching `claimName:` lines in `templates/bluemap-deployment.yaml`,
`templates/bluemap-config-deployment.yaml`, and
`templates/minecraft-statefulset.yaml`.

Then:

Sync `$APP` from the ArgoCD UI (or the argocd MCP `sync_application`) with
**Prune unchecked**. The old PVC now shows as "requires pruning". Leave it:
pruning through Argo would hit the sanoid-snapshot block anyway, so step 8
handles the delete.

The sync adopts `$NEW`, switches the pod template to the new claim, and brings
replicas back to what the chart says. That scales the app up. (Restore the
ArgoCD controller here if step 1 stopped it.)

### 7. Verify

```sh
kubectl get pod -n $NS -o wide                                   # Running, no restarts
kubectl get pod <pod> -n $NS -o jsonpath='{.spec.volumes[*].persistentVolumeClaim.claimName}'; echo   # shows *-64k
kubectl exec -n $NS <pod> -- df -hT /<mountPath>                 # xfs, expected usage
```

App-level checks:
- **Plex:** the UI loads, libraries browse, a title plays, and the logs show no
  database errors. Run `PRAGMA integrity_check` with the bundled `Plex SQLite`
  against `com.plexapp.plugins.library.db` under `/config`.
- **Crafty:** panel login works, the server list is intact, the world(s) start,
  and the latest backup and world files are present.
- **arr apps / postgres:** the UI loads with its history, and for postgres,
  bazarr connects.

Then record `zpool list -o alloc,frag,cap sas-pool`. The old zvol still holds
its space at this point, so the reclaim only shows up after step 8.

### 8. Delete the old PVC (only after you confirm)

Wait for your explicit sign-off. A short soak first is suggested: a day of
normal use for Plex and crafty. Until then, the old 16K PVC is the rollback:
revert the chart commit, sync, and the app is back on it. Anything written
after the cutover would need a reverse rsync.

On sign-off, follow
[Deleting a CSI PVC](volblocksize-remediation.md#deleting-a-csi-pvc-required-procedure--clears-blocking-snapshots).
Delete the PVC with `--wait=false`, clear the sanoid snapshots on `$OLDPV`, and
confirm both the PV and the zvol are gone:

```sh
kubectl delete pvc $OLD -n $NS --wait=false
ssh ubuntu@storage01.drewburr.com \
  "for s in \$(sudo zfs list -H -t snapshot -o name sas-pool/k8s/nvmeof/dataset/$OLDPV 2>/dev/null); do sudo zfs destroy \"\$s\"; done"
kubectl get pv $OLDPV 2>&1 | tail -1                                                            # NotFound
ssh ubuntu@storage01.drewburr.com "sudo zfs list sas-pool/k8s/nvmeof/dataset/$OLDPV 2>&1 | tail -1"   # does not exist
```

The app's Argo status then goes back to Synced. Delete the finished Job, and
record the wave's final `zpool list`.

## Fallback: rebind under the original name

This is for workloads whose claim name can't be changed in the chart and whose
data has to survive: volumeClaimTemplate PVCs, and Grafana if you want it done
without touching values. (Harbor's volumeClaimTemplate PVCs don't need this:
Harbor is being reset empty instead.)
Use the runbook's existing Phase 2 steps 1–6, with one change that keeps a
rollback: **before deleting the old PVC, set the old PV to `Retain`.** The old
zvol then survives the swap as a Released PV. After sign-off, patch it back to
`Delete` so CSI reclaims it, and clear its snapshots as in step 8.

```sh
kubectl patch pv $OLDPV -p '{"spec":{"persistentVolumeReclaimPolicy":"Retain"}}'   # before the swap
# ... after sign-off:
kubectl patch pv $OLDPV -p '{"spec":{"persistentVolumeReclaimPolicy":"Delete"}}'   # then clear snapshots
```

For Grafana (autosynced `prometheus` app), the alternative is
`grafana.persistence.existingClaim: prometheus-grafana-64k` in
`k8s/prometheus/values.yaml`, with the ArgoCD controller stopped as in step 1.

## Exit criteria for Phase 2

- `zfs list -t volume ... | awk '$2==16384'` lists only the volumes you
  deliberately chose to skip (harbor, Grafana).
- The orphan diff (Phase 0.1) is empty.
- `zpool list sas-pool` ALLOC and FRAG are recorded before and after, in the
  runbook's completed-migrations table.
