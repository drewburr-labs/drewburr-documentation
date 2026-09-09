# storage01 move, September 2026

Runbook and scripts for taking storage01 down for the physical move. Background on the pools and the `movebak` USB backup is in [../README.md](../README.md#move-backup-movebak). Run everything from this directory on a machine with `kubectl` access to the lab cluster and SSH to `storage01.drewburr.com`.

| File | Purpose |
|-|-|
| `workloads.txt` | Every Deployment/StatefulSet with a PVC on storage01, in scale-down order |
| `cronjobs.txt` | CronJobs whose pods mount storage01 PVCs |
| `scale-down.sh` | Suspends the CronJobs, disables ArgoCD auto-sync on `prometheus`, records replica counts to `state/replicas.txt`, scales everything to 0, waits for the pods to go |
| `scale-up.sh` | Reverse of the above from `state/replicas.txt` |
| `movebak-refresh.sh` | Incremental syncoid of sas-pool and rsync of the Plex tv list, books and manual onto movebak. Runs on storage01 |
| `tv_backup_list.txt` | The 109 shows (chosen from Tautulli watch history) that fit on movebak |

## Order of operations

1. **Validate movebak** (done 2026-09-09; see the section in the parent README). Re-import if it was exported: attach the USB enclosure to VM 105 by port, then `sudo zpool import movebak` on storage01.
2. **Scale down**: `./scale-down.sh`. Then confirm storage01 has no clients left:
   ```sh
   ssh storage01.drewburr.com 'ss -tn state established "( sport = :4420 )" | tail -n +2 | wc -l; ss -tn state established "( sport = :2049 )" | tail -n +2 | wc -l'
   ```
   Both counts should be 0 (NVMe-oF on 4420, NFS on 2049). The democratic-csi controller and node pods stay running; they hold no data. Non-cluster clients count too: on 2026-09-09 the leftover NFS connection was the `jellyfin` Docker container on Drew's Fedora workstation, whose `jellyfin_plex-alt-data` volume NFS-mounts the `plex-alt-data` PVC; `docker stop jellyfin` released it. `ss -tn state established '( sport = :2049 )'` on storage01 shows the peer address.
3. **Final backup pass**:
   ```sh
   ssh storage01.drewburr.com 'mkdir -p /tmp/move-2026' && scp tv_backup_list.txt storage01.drewburr.com:/tmp/move-2026/
   ssh storage01.drewburr.com 'bash -s' < movebak-refresh.sh
   ```
   First confirm `ssh storage01.drewburr.com 'lsusb -t'` shows the `uas` device at `5000M` (see the USB speed note in the parent README). Progress: `ssh storage01.drewburr.com 'sudo zpool iostat movebak 5 2'`; expect ~180 MB/s writes.
   Check the tail of the log it prints: syncoid and rsync exit 0, `zpool status movebak` shows 0 errors, and the latest snapshot is today's.
4. **etcd backup** (done 2026-09-09). The cluster is k3s with embedded etcd on kube02 and kube03. Take a snapshot and copy it off the cluster:
   ```sh
   ssh ubuntu@kube02.drewburr.com 'sudo k3s etcd-snapshot save --name move-2026'
   # snapshot lands in /var/lib/rancher/k3s/server/db/snapshots/move-2026-kube02-<epoch>; copy it to ~/backups/etcd-move-2026/
   ssh ubuntu@kube02.drewburr.com 'sudo cat /var/lib/rancher/k3s/server/token' > ~/backups/etcd-move-2026/k3s-server-token
   ```
   A restore (`k3s server --cluster-reset --cluster-reset-restore-path=<snapshot>`) needs the server token to decrypt the bootstrap data in the snapshot, so the token travels with it. Encrypt both with 7-Zip, then copy the archive to `/movebak/etcd/` and compare `sha256sum` on both sides:
   ```sh
   cd ~/backups/etcd-move-2026
   7z a -p -mhe=on etcd-move-2026.7z move-2026-kube02-<epoch> k3s-server-token   # prompts for the password
   7z t etcd-move-2026.7z                                                           # prompts, expect "Everything is Ok"
   ```
   **7-Zip 26 prompting rules**, learned the hard way: `7z a -p` with a bare `-p` prompts for the password. `7z t -p` / `7z x -p` with a bare `-p` does **not** prompt; it tries an empty password and fails with "Cannot open encrypted archive. Wrong password?". To be prompted on test or extract, leave `-p` off entirely; 7-Zip asks when it hits the encrypted header. Never pass `-p<password>` on the command line, it ends up in shell history.
   Copies as of 2026-09-09: `~/backups/etcd-move-2026/etcd-move-2026.7z` on Drew's Fedora workstation and `/movebak/etcd/etcd-move-2026.7z`, sha256 `d51497747c3809b42a94030d71c908ac43268c999cb59a22c87f3d8cb2cda5b0`.
5. **Export movebak** so it can travel separately: `ssh storage01.drewburr.com 'sudo zpool export movebak'`, then remove `usb0` from VM 105 on pve05 and unplug the enclosure.
6. **Shut down storage01**: `ssh storage01.drewburr.com 'sudo shutdown -h now'`. The pools are not exported on purpose; they import automatically on boot. Then shut down pve05 and pull the drives. Label each drive bay with the serial (`zpool status` shows them) so they go back in the same order, though ZFS does not require that.

## What was done on 2026-09-09

| Step | Result |
|-|-|
| Scale-down | 48 workloads to 0, 3 CronJobs suspended, applicationset controller stopped, state in `state/` |
| storage01 clients | 0 NVMe-oF, 0 NFS after stopping the workstation Jellyfin container |
| syncoid pass | 86/86 PVCs, all with a `syncoid_storage01_2026-09-09` snapshot, `written@` 0 on every source afterwards |
| Plex rsync | tv 5355/5355 files for the 109 listed shows, books 95/95, manual 114/114 |
| etcd | `/movebak/etcd/etcd-move-2026.7z`, sha256 matches the workstation copy |
| movebak | ONLINE, 0 errors, 10.4T used / 2.29T free, exported 15:30 UTC |

## Bringing it back

1. Reinstall drives, boot pve05. If VM 105 fails to start, the PCI addresses of the HBA and SATA controller have probably changed; see the parent README.
2. Boot storage01, check `zpool status` shows both pools ONLINE with 0 errors. If `lake` or `sas-pool` is missing, `sudo zpool import <name>`.
3. Confirm the nvmet config loaded (`sudo nvmetcli ls` shows the subsystems) and NFS exports exist (`sudo exportfs -v`).
4. `./scale-up.sh`, then `kubectl get pods -A | grep -vE 'Running|Completed'` until clean. Databases (harbor, bazarr-postgres, rreading-glasses-db, prometheus, loki) come up before the apps that use them because the state file is replayed in reverse.
5. Re-attach and import movebak only if it is needed; otherwise leave it on the shelf as the offline copy.

## Notes on what is and is not scaled

- Everything in `workloads.txt` mounts a storage01 PVC, or is a hard dependency of something that does (`prometheus-operator` recreates the Prometheus StatefulSet if left running, `harbor-core` and `loki-read` crash-loop without their backends, so they are included for tidiness).
- `prometheus` is the only ArgoCD Application with `automated` + `selfHeal`. It is generated by the `drewburr-apps` ApplicationSet, which re-adds that block within seconds of it being removed, so `scale-down.sh` stops the `argocd-applicationset-controller` Deployment first, then removes the block; `scale-up.sh` restores both from `state/`. All other apps are manual sync, so ArgoCD will show them OutOfSync but not act.
- StatefulSets already at 0 (`minecraft-novacraft`, `minecraft-poke-central`, `minecraft-test`, `plex-plex-config`, `plex-sonarr-alt`) are recorded as 0 and left at 0.
- PVCs with no pod at all (the three idle Minecraft namespaces, `notifiarr-config`, `sabnzbd-flex-*`, `sonarr-alt-config`, `sonarr-anime-config`) need nothing.
- Grafana and Loki going down means no dashboards or logs during the window. Alertmanager has no storage01 PVC and stays up.
