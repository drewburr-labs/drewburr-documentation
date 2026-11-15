# Moving lake drives from USB to SAS, November 2026

On 2026-11-15 the last USB-attached member of `lake` (WD `WD140EDGZ` 14TB, serial `Y5KTTH5C`, in an ASM235CM enclosure passed through from pve05) was shucked and moved into a direct-attached hot-swap bay on the SAS3224 HBA. At the same time the other lake drives were rearranged across the bays, and two spare 14TB drives were installed (see the spinner table in [../README.md](../README.md#spinners-2026-11-15)).

**Why:** at 23:05 that evening the USB disk dropped off the bus (`DID_NO_CONNECT`), re-enumerated on another port and resilvered. A raidz2 member on USB is one flaky cable away from a degraded pool.

Only Plex was down. `sas-pool` and every other PVC stayed up, and pve05 was never powered off.

| File | Purpose |
|-|-|
| `lake-hotswap.sh down` | Checks lake is healthy, records replica counts to `state/replicas.txt`, scales every `plex` StatefulSet that mounts an `nfs-lake` PVC to 0, waits for the pods to go, then `zpool export lake`. If the export fails, it lists the NFS clients still holding state on lake (see below). |
| `lake-hotswap.sh down-export` | Retries only the export after you clear what was blocking it. |
| `lake-hotswap.sh up` | Waits for serial `Y5KTTH5C` (override with `SERIAL=`) on a non-USB path, rescanning the SCSI hosts. Imports lake from only the `scsi-*-part1` by-id links, so moved members get serial-bearing names (falls back to `-d /dev/disk/by-id`), skips the import if lake is already imported, refuses to continue if any member is still a `usb-` path or fewer than 7 members are ONLINE, then restores the replica counts. |
| `pve05-usb-detach.sh` | Run on pve05 as root after the export. Lists every ASM235CM (`174c:55aa`) enclosure on the host, finds VM 105's USB entry for bridge serial `ACAAEBBB34E0` by exact port match, and removes it. |

## Procedure

1. `./lake-hotswap.sh down` (stop the `jellyfin` container on the workstation first; it NFS-mounts `plex-alt-data`).
2. On pve05: `pve05-usb-detach.sh`.
3. Pull the drives. Slide each one out about an inch and let it spin down before carrying it. Leave the 2.5" shelf alone: that is `sas-pool` and it is live.
4. Shucked WD drives: tape SATA power pins 1-3 (3.3V power disable) or they will not spin up on backplane power.
5. Put every lake drive on the HBA's direct-attach bays or on the passed-through FCH SATA ports. Bay order does not matter because ZFS finds members by label.
6. Before importing, check that every drive is visible: `ls /dev/disk/by-id/ | grep <serial>` for each one, and `sudo zpool import` should list lake with all members ONLINE.
7. `./lake-hotswap.sh up`.

## Gotcha: stale NFS delegations block the export

With every Plex pod gone and no NFS mounts left on any node, `zpool export lake` still failed:

```text
cannot unmount '/lake/k8s/nvmeof/dataset/pvc-1a6ee17d-...': pool or dataset is busy
```

`fuser` showed nothing local. The holder was nfsd: `/proc/fs/nfsd/clients/<id>/states` for kube05's NFSv4.1 client still had 37 open/delegation states on `plex-data` files, although kube05 had no NFS mounts at all (`grep -c nfs /proc/mounts` returned 0, and `/proc/fs/nfsfs/servers` was empty). Linux 5.19+ runs a "courteous" NFS server, which keeps an expired client's state until something conflicts with it, so the state does not go away on its own.

Fix: after confirming the host has no NFS mounts left, expire only that client, then export:

```sh
# on storage01; <id> from `sudo grep -l kube05 /proc/fs/nfsd/clients/*/info`
echo expire | sudo tee /proc/fs/nfsd/clients/<id>/ctl
sudo zpool export lake
```

This drops that client's state for every export, so only do it for a client that has nothing mounted. The other clients (kube02, kube03 with `sas-pool` `zfs-nfs` mounts) are not affected.

## Result

- `lake` imported ONLINE, 0 errors, no resilver. All 7 members are on the HBA or FCH SATA.
- `Y5KTTH5C` first came back as `wwn-0x5000cca28ef58b59`, because its recorded `usb-` path was gone and the by-id scan picked the WWN link. The same night lake was exported again and imported from only the `scsi-*-part1` links, which renamed it to `scsi-SATA_WDC_WD140EDGZ-11_Y5KTTH5C`. `up` now always imports this way.
- Both `nfs-lake` datasets were mounted and exported again, and all 9 Plex StatefulSets came back Running.
