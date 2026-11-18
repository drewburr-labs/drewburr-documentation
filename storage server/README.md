# Storage Server Documentation

The storage server is `storage01` (Ubuntu 24.04), a VM on `pve05` that provides centralized storage for Kubernetes PVCs. Both the SAS HBA and the motherboard SATA controller are passed through to the VM with PCI passthrough, so the VM sees the raw disks. Storage is provided using ZFS and the democratic-csi operator over NVMe-oF (block, `zfs-nvmeof` storage class) and NFS (`zfs-nfs` and `nfs-lake` storage classes).

> Hostnames in this documentation are under the `drewburr.com` domain unless otherwise stated. Short names may not resolve from every machine; use the FQDN, e.g. `storage01.drewburr.com`.

## Current layout (as of November 2026)

### Controllers seen by the VM

| PCI address | Device | Drives |
|-|-|-|
| `00:10.0` | Broadcom / LSI SAS3224 (Fusion-MPT SAS-3) | Behind the expander (HBA phys 8-11, the 24-bay 2.5" shelf): 24x NetApp X438 SAS SSD. Direct-attached 3.5" hot-swap bays (HBA phys 17-23): 7x spinners. |
| `00:11.0` | AMD FCH SATA (AHCI) | 2x spinners on `ata5`/`ata6`. `ata3`/`ata4` are free. |

No pool member is on USB any more. On 2026-11-15 the last USB member of `lake` was shucked and moved into a hot-swap bay; see [`usb-to-sas/`](usb-to-sas/).

Of the 24 SSDs, 20 are `sas-pool`. The other 4 (`S182NEAG610807`, `610064`, `610784`, `610040`) still have NetApp's 520-byte sectors, so they show up as 0B disks; they need an `sg_format --format --size=512` before ZFS can use them.

### Pools

| Pool | Layout | Raw | Notes |
|-|-|-|-|
| `sas-pool` | 20x NetApp X438 SAS SSD (373GB usable each), raidz3 | 7.3T | All Kubernetes PVCs except Plex media. `zfs-nvmeof` zvols and `zfs-nfs` datasets under `sas-pool/k8s/nvmeof/dataset`. |
| `lake` | 8-wide raidz2 spinners: 5x HGST 12TB (3 SATA `HUH721212ALE601`, 2 SAS `HUH721212AL4205`) + 3x WD 14TB (2x `WUH721414AL` and a shucked `WD140EDGZ`). Expanded with raidz expansion from 5 to 6 wide in January 2026 (completed Jan 28 2026), from 6 to 7 wide in November 2026 (attached 2026-11-01, finished 2026-11-04), and from 7 to 8 wide (`9RGGE14C` attached 2026-11-16 00:02, copied 62.7T in 2 days 4h 40m, finished 2026-11-18 04:42). See [Expanding to 9 wide and rewriting](#planned-expanding-to-9-wide-and-rewriting-lake). | 87.3T | Plex media over NFS (`nfs-lake`). Datasets under `lake/k8s/nvmeof/dataset`. Data written before each expansion keeps the older parity ratio, so `zpool list` allocation is higher than `zfs list` usage. The 14TB drives only contribute 12TB each until every member is at least 14TB. |

Both pools reference disks by `/dev/disk/by-id/` names. Identify a physical drive by serial number (see below).

#### Spinners (2026-11-15)

| Serial | Model | Pool | Attached via | Pool device name |
|-|-|-|-|-|
| `9RG9UZEC` | WD `WUH721414AL` 14TB | `lake` | HBA | `scsi-SATA_WDC_WUH721414AL_9RG9UZEC` |
| `Y5KTTH5C` | WD `WD140EDGZ` 14TB (shucked, 3.3V pins taped) | `lake` | HBA | `scsi-SATA_WDC_WD140EDGZ-11_Y5KTTH5C` |
| `8DJPRNEY` | HGST `HUH721212ALE601` 12TB | `lake` | HBA | `scsi-SATA_HUH721212ALE601_8DJPRNEY` |
| `5QJPHE0B` | HGST `HUH721212AL4205` 12TB | `lake` | HBA | `scsi-SHGST_HUH721212AL4205_5QJPHE0B` |
| `5QJN3BUB` | HGST `HUH721212AL4205` 12TB | `lake` | HBA | `scsi-SHGST_HUH721212AL4205_5QJN3BUB` |
| `8DJK4ZMY` | HGST `HUH721212ALE601` 12TB | `lake` | FCH SATA `ata6` | `scsi-SATA_HUH721212ALE601_8DJK4ZMY` |
| `8HKXR98H` | HGST `HUH721212ALE601` 12TB | `lake` | FCH SATA `ata5` | `scsi-SATA_HUH721212ALE601_8HKXR98H` |
| `9RGGE14C` | WD `WUH721414AL` 14TB | `lake` (since 2026-11-18) | HBA | `scsi-SATA_WDC_WUH721414AL_9RGGE14C` |
| `Y5KTG63C` | WD `WD140EDGZ` 14TB (shucked) | none (planned 9th `lake` member, see below) | HBA | Installed 2026-11-15, blank, SMART clean, 32.6k power-on hours (used drive) |

When a member's recorded path no longer exists (for example after moving off USB), `zpool import -d /dev/disk/by-id` records whichever by-id link it finds first. That was `wwn-0x5000cca28ef58b59` for `Y5KTTH5C`, which hides the serial in `zpool status`. To keep serial-bearing names, give the import only the `scsi-*` partition links; ZFS 2.4 accepts devices for `-d`:

```sh
args=""; for l in /dev/disk/by-id/scsi-S*-part1; do args="$args -d $l"; done
sudo zpool import $args          # preview the names, then:
sudo zpool import $args lake
```

Members whose recorded path still exists keep it; only the ones that moved get renamed. [`usb-to-sas/lake-hotswap.sh up`](usb-to-sas/lake-hotswap.sh) imports this way.

#### Planned: expanding to 9 wide and rewriting lake

**Why:** raidz expansion does not re-stripe existing blocks. Only new writes use the wider layout. As of 2026-11-18, `lake` holds 36.5T of data (`logicalused`, compression ratio 1.00x) in 62.7T raw. That is about 58% efficiency, roughly what 5-wide raidz2 gives with 128K records, so nearly everything is still at the original parity ratio. ZFS 2.4's `zfs rewrite` writes files back in place, and the new blocks use the current width.

**Why expand first:** every expansion copies all allocated data, and rewrite is the expensive pass, so do the rewrite only once, at the final width. Rewriting at 8 wide and then adding the 9th drive would leave data at the 8-wide ratio and need a second rewrite. With 128K records and 4K sectors (ashift 12), a block uses about 71% of its raw space at 8 wide and about 76% at 9 wide, because of raidz padding.

Estimates (not measured): after the 9-wide expansion, raw size is about 98T. Rewriting 36.5T at 9 wide should take about 48T raw, down from 62.7T, which frees roughly 15T raw.

`lake` has no snapshots, so rewritten blocks free the old ones right away. With snapshots, the old blocks stay referenced and pool usage goes **up**. Check with `zfs list -t snapshot -r lake` before rewriting.

Steps, on storage01:

1. Let the post-expansion scrub from 2026-11-18 finish, and confirm 0 errors in `zpool status lake`. Attaching a device can cancel a running scrub, and this scrub is the first check of the 8-wide copy.
2. Attach the 9th drive. This starts the expansion; Plex stays up but is slower. The last expansion took about 2.2 days for 62.7T, and a pool-wide scrub (about 20+ hours) runs automatically afterwards.

   ```sh
   sudo zpool attach lake raidz2-0 /dev/disk/by-id/scsi-SATA_WDC_WD140EDGZ-11_Y5KTG63C
   ```

3. After the expansion and its scrub finish, enable the new pool features. **This cannot be undone**: a ZFS older than 2.4 can no longer import `lake`. This enables `physical_rewrite` and `block_cloning_endian`. `dynamic_gang_header` is not enabled by `upgrade`, and this pool does not need it.

   ```sh
   sudo zpool upgrade lake
   ```

4. Rewrite the Plex media dataset in the background. `-P` keeps logical birth times so the blocks do not look modified to incremental sends. `-x` stays inside this dataset. Run it in `tmux` so it survives an SSH disconnect. Progress shows as `ALLOC` falling in `zpool list lake`.

   ```sh
   tmux new -s rewrite
   sudo zfs rewrite -P -r -x /lake/k8s/nvmeof/dataset/pvc-1a6ee17d-54a9-47e3-808f-b266d21d1fd9
   ```

   The small `pvc-05ac5179-...` dataset (about 43G) can be rewritten the same way afterwards.

Notes:

- `zfs list` keeps under-reporting `AVAIL` and `USED` after the rewrite. The vdev's space accounting stays at the original 5-wide ratio, so `zpool list` is the number to trust.
- Rewrite keeps each file's existing record size. Changing `recordsize` (for example to 1M for media) only takes effect by copying files into a new dataset. That is not worth doing for about 4% more efficiency.
- The 14TB members still only contribute 12TB each until every member is at least 14TB.

### Snapshots and backups

- `sanoid` runs on a systemd timer and takes hourly snapshots of `sas-pool/k8s/nvmeof/dataset` (recursive, keep 1). See `/etc/sanoid/sanoid.conf`.
- `lake` has no snapshot policy.
- There is **no replication**. `zbackup` was the former backup target and is decommissioned; one of its drives was absorbed into `lake`.
- The only copy of anything off the pools is the `movebak` USB pool described in [Move backup (movebak)](#move-backup-movebak).
- Scrubs run monthly via the `zfsutils-linux` cron in `/etc/cron.d`. A `lake` scrub takes roughly 20 hours, `sas-pool` under 30 minutes.

### Move backup (movebak)

Created September 2026 for the physical move of the server (runbook and scripts in [`move-2026/`](move-2026/)). It is a **single-disk ZFS pool on a USB drive**, so it has no redundancy of its own; it exists so the data survives if the server or a pool does not survive the move. Nothing else backs up these pools.

| | |
|-|-|
| Pool | `movebak`, 12.7T raw, single vdev |
| Disk | WD `WUH721414ALE604` 14TB, serial `9RG0E9MC`, in an ASMedia ASM235CM (ASMT 2235) USB enclosure. ZFS sees it as `/dev/disk/by-id/usb-ASMT_2235_ACAAEBBB34DE-0:0`. |
| Created with | `zpool create -o ashift=12 -O compression=lz4 -O atime=off -O mountpoint=/movebak movebak /dev/disk/by-id/usb-ASMT_2235_ACAAEBBB34DE-0:0` |
| Attached to | The enclosure is plugged into **pve05** and USB-passed-through to VM 105 (`usb0`). It shows up in the VM as a `2235` USB disk. |
| Status (2026-11-15) | **Not attached to storage01.** `movebak` is not imported, and `9RG0E9MC` is not among the drives on the HBA or SATA controller. If it comes back, import it with `zpool import -d /dev/disk/by-id movebak`. |

#### What is on it

| Dataset | Source | Method | Notes |
|-|-|-|-|
| `movebak/sas-pool/<pvc-uuid>` | every dataset and zvol under `sas-pool/k8s/nvmeof/dataset` (86 PVCs, ~1.5T on disk) | `syncoid` recursive replication | Full ZFS copies with a `syncoid_storage01_<date>` snapshot on both sides, so later runs are incremental. Includes all configs, databases, Minecraft servers and `crafty-backups`, Plex config, Prometheus. |
| `movebak/plex/tv` | `lake/.../pvc-1a6ee17d-.../media/tv` (the `plex-data` PVC) | `rsync` of a curated show list | 109 of 278 shows, about 8.4T. The library is 16T so it does not fit; the list was chosen from Tautulli watch history. The list is saved in this repo as [`move-2026/tv_backup_list.txt`](move-2026/tv_backup_list.txt). |
| `/movebak/etcd/etcd-move-2026.7z` | k3s etcd snapshot from kube02 plus the k3s server token | `k3s etcd-snapshot save`, 7-Zip AES with encrypted headers | Password-protected; see the runbook in `move-2026/` for the 7-Zip prompting quirk. |
| `movebak/plex/books`, `movebak/plex/manual` | `books/` and `manual/` from the same PVC | `rsync` | Complete copies (~130G). |

**Not backed up**, by decision, because it does not fit: `media/movies` (9.5T), the other 169 TV shows, `downloads/` (11T of seedbox/usenet intake), and the `plex-alt-data` PVC on lake (31G). A ranked list of movies by size from that analysis is at `/tmp/movies.txt` on storage01. If space is left after the final sas-pool pass, a Tautulli-ranked subset of movies is the next thing to add.

#### Refreshing the backup

Both steps are safe to re-run; syncoid is incremental and rsync only copies changed files. Run them on storage01 as `ubuntu` with sudo, or use [`move-2026/movebak-refresh.sh`](move-2026/movebak-refresh.sh), which does exactly this and logs to `/var/log/movebak-refresh-<date>.log` on storage01. The sas-pool step needs the previous `syncoid_storage01_*` snapshots to still exist on the source (they do as of 2026-09-09; sanoid does not prune them because they are not its snapshots).

```sh
# 1. sas-pool: all PVCs, incremental. Takes ~15 min for a small delta, longer if crafty-backups grew.
sudo syncoid -r --compress=none --sendoptions=Lce \
  sas-pool/k8s/nvmeof/dataset movebak/sas-pool > /var/log/syncoid-movebak-$(date +%F).log 2>&1

# 2. Plex tv (curated list), books, manual
SRC=/lake/k8s/nvmeof/dataset/pvc-1a6ee17d-54a9-47e3-808f-b266d21d1fd9
sudo rsync -ar --info=progress2 --files-from=/tmp/move-2026/tv_backup_list.txt "$SRC/media/tv/" /movebak/plex/tv/
sudo rsync -a  --info=progress2 "$SRC/books/"  /movebak/plex/books/
sudo rsync -a  --info=progress2 "$SRC/manual/" /movebak/plex/manual/
```

Before the final pass, scale down the workloads that write to sas-pool (Minecraft, databases, Plex) so the snapshot is consistent. `zfs get written@<snapshot>` on a source dataset shows how much changed since the last copy.

#### Validating

```sh
sudo zpool status movebak                  # expect ONLINE, 0 errors
sudo zfs list -r movebak | grep -c pvc-    # expect same count as sas-pool/k8s/nvmeof/dataset
sudo zfs list -t snapshot -r movebak -o name,creation -s creation | tail -3   # latest syncoid date
```

For the syncoid datasets, `zfs receive` verifies checksums on the way in, so a clean `zpool status` is sufficient. For the rsync data, compare file counts (`find ... -type f | wc -l`) per top-level directory and spot-check a few files with `md5sum` on both sides. A full `zpool scrub movebak` reads the whole 10T over USB and takes most of a day; it was not run before the move.

#### Detaching for transport and re-attaching

```sh
# On storage01, before unplugging
sudo zpool export movebak
```

Then on pve05 remove the `usb0` entry from VM 105 (Hardware tab, or `qm set 105 --delete usb0`) and unplug the enclosure. Because the pool is exported cleanly it can be imported on any machine with ZFS.

To re-attach: plug the enclosure into pve05, then pass it through **by USB port, not by vendor/device ID**. There are several ASM235CM enclosures on this host with the identical ID `174c:55aa`, so the ID form is ambiguous. Find the port with:

```sh
# on pve05
lsblk -d -o NAME,SIZE,MODEL,SERIAL,TRAN | grep usb          # movebak is the 12.7T WUH721414ALE604
for d in /sys/block/sd*; do echo "$(basename $d) $(udevadm info -q path -p $d | grep -oE '[0-9]+-[0-9.]+' | tail -1)"; done
qm set 105 --usb0 host=<port>,usb3=1                       # hot-plugs into the running VM
```

The enclosure has an internal hub, so the disk's bridge is one level deeper than the port the enclosure is plugged into (on 2026-09-09 it was `1-6.1.4.1`; the `1-6.1.4.5` sibling is the enclosure's USB Billboard device, not the disk). Then on storage01:

```sh
sudo zpool import movebak
```

The port path changes whenever the enclosure is plugged into a different USB socket, so expect to redo this after the move.

**Check the link speed before starting a transfer.** On 2026-09-09 the enclosure was first plugged in behind a USB 2.0 hub (port `1-6.1.4.1`; bus 1 on pve05 is the 480 Mbps tree) and movebak wrote at ~37 MB/s. Moved to a USB 3 hub (`4-4.4.1`, bus 3/4 on pve05) it did ~180 MB/s. Inside the VM, `lsusb -t` must show the `uas` mass-storage device at `5000M`, not `480M`. The Proxmox "Speed" column in the USB device picker shows the same thing. If it is wrong, stop the transfer, `zpool export movebak`, re-plug, re-pass-through, re-import; syncoid resumes an interrupted send from the receive_resume_token.

### Proxmox VM (pve05)

`storage01` is VM **105** on `pve05` (8 cores, 24GB RAM, 100G boot disk on `local-lvm`, `onboot: 1`, startup order 1 so it comes up before `kube05`). The relevant `qm config 105` lines:

```text
hostpci0: 0000:0f:00,rombar=0   # LSI SAS3224 HBA
hostpci1: 0000:09:00            # AMD FCH SATA controller (ports 5 and 6)
scsi0: local-lvm:vm-105-disk-0,size=100G
net0: virtio=BC:24:11:00:EE:9E,bridge=vmbr0,firewall=1,mtu=1,tag=4
ipconfig0: gw=192.168.4.1,ip=192.168.4.31/23
startup: order=1,up=30
```

> **The host-side PCI addresses have shifted before.** The VM description still says SAS at `0b:00` and SATA at `08:00`, but the live config uses `0f:00` and `09:00`. Any hardware change on pve05 (adding a card, moving the HBA to a different slot, a rebuild after transport) can renumber them again. If the VM fails to start after hardware work, check `lspci -nn | grep -iE "sas|sata"` on pve05 and update `hostpci0`/`hostpci1` with `qm set 105 --hostpci0 <addr>,rombar=0 --hostpci1 <addr>`. Because the pools use `/dev/disk/by-id/`, ZFS does not care which controller or port a drive lands on.

`kube05` (VM 104) on the same host also has a passthrough device at `0000:0d:00`.

There is no scheduled Proxmox backup of VM 105 as far as is documented here. The VM's boot disk holds only the OS, nvmet config (`/etc/nvmet/config.json`), and sanoid config; the data lives entirely on the passed-through pools, so a rebuilt VM with `zfsutils-linux` and democratic-csi prerequisites can `zpool import` both pools.

## ZFS setup

Following the somedudesays [ZFS overview](https://somedudesays.com/2021/08/the-basic-guide-to-working-with-zfs/). Always create pools with `/dev/disk/by-id/` paths, never `/dev/sdX`.

```sh
# Install ZFS
sudo apt install zfsutils-linux

# Example (the original 12-disk pool; it has since grown to 20)
sudo zpool create sas-pool raidz3 /dev/disk/by-id/scsi-SNETAPP_X438_1625400MCSG_S182NEAG609573 ...
```

### Helpful commands

View all PCI devices:
`lspci`

Get all block devices
`ls -l /sys/block/`

View block device metadata
`sg_format /dev/<name>`

#### Adding a new PCI device to the storage VM

The motherboard SATA controller is also passed through. To identify which block devices sit on it:

```sh
# Show PCI devices to identify SATA controller
$ lspci
00:11.0 SATA controller: Advanced Micro Devices, Inc. [AMD] FCH SATA Controller [AHCI mode] (rev 51)

# Get block devices, filter for SATA controller's PCI address
$ ls -l /sys/block/ | grep 00:11.0
lrwxrwxrwx 1 root root 0 Dec  7 21:28 sdn -> ../devices/pci0000:00/0000:00:11.0/ata5/host6/target6:0:0/6:0:0:0/block/sdn
lrwxrwxrwx 1 root root 0 Dec  7 21:28 sdo -> ../devices/pci0000:00/0000:00:11.0/ata6/host7/target7:0:0/7:0:0:0/block/sdo

# Show devices in lsblk
$ lsblk | grep -e sdn -e sdo
sdn       8:208  1  10.9T  0 disk
sdo       8:224  1  10.9T  0 disk

# Show device in sg_format
$ sudo sg_format /dev/sdn
 ...
Mode Sense (block descriptor) data, prior to changes:
  Number of blocks=0 [0x0]
  Block size=512 [0x200]
Read Capacity (16) results:
   Protection: prot_en=0, p_type=0, p_i_exponent=0
   Logical block provisioning: lbpme=0, lbprz=0
   Logical blocks per physical block exponent=3
   Lowest aligned logical block address=0
   Number of logical blocks=23437770752
   Logical block size=512 bytes
```

#### Removing and readding a disk to ZFS

While disks attached to the SAS controller are physically ordered top-to-bottom, where device 0 is physically located at the top and device 24 at the bottom, this is not actually honored when reviewing PCI addresses. The best way to identify a drive is by its serial number. I am passing the PCI device directly to my storage server, providing transparency required to get this information.

Start by reviewing the label on the device intended to be removed. If using a JBOD, this may not be possible and the pool will need to be placed offline. It is reccommended to ensure all drives have safely visible serial numbers, or are labeled with the last 4 or 5 letters of the serial number to ensure it's identifiable. In this example, the last 5 of my serial is `10740`.

In the case where your ZFS pool is created using `/dev/disk/by-id/*` instead of `/dev/*`, you will be able to identify the drive directly using `zpool status`. Both pools now use disk ids, so `zpool status` shows the serial directly. If you ever need to translate a serial to a device name:

```sh
$ lsblk -o NAME,SERIAL | grep 10740
sdi     .........10740
```

```sh
# Validate health of ZFS pool
$ zpool status
  pool: sas-pool
 state: ONLINE
```

```sh
# Offline the disk
$ sudo zpool offline sas-pool sdi
```

```sh
# Validate disk is offline
$ zpool status
  pool: sas-pool
 state: DEGRADED
 ...
config:

        NAME        STATE     READ WRITE CKSUM
        sas-pool    DEGRADED     0     0     0
          raidz3-0  DEGRADED     0     0     0
            sdi     OFFLINE      0     0     0
            ...
```

In this state, the disk is safe to phsically disconnect from the system. Continue once reattached

```sh
# Online the disk
$ sudo zpool online sas-pool sdi
```

```sh
# Validate health of ZFS pool
$ zpool status
  pool: sas-pool
 state: ONLINE
```

## nvmeof setup

### Client

```sh
# not required but likely helpful (tools are included in the democratic images
# so not needed on the host)
apt install -y nvme-cli

# get the nvme fabric modules
apt install linux-generic

# ensure the nvmeof modules get loaded at boot
cat <<EOF > /etc/modules-load.d/nvme.conf
nvme
nvme-tcp
nvme-fc
nvme-rdma
EOF

# load the modules immediately
modprobe nvme
modprobe nvme-tcp
modprobe nvme-fc
modprobe nvme-rdma

## DID NOT DO THE BELOW ##

# nvme has native multipath or can use DM multipath
# democratic-csi will gracefully handle either configuration
# RedHat recommends DM multipath (nvme_core.multipath=N)
cat /sys/module/nvme_core/parameters/multipath

# kernel arg to enable/disable native multipath
nvme_core.multipath=N
```

### Migrating to /dev/disk/by-id/*

When setting up a ZFS pool, it is best to add disks to the pool by their ID instead of the by the device name (`/dev/sdx`). This is because the Linux kernel does not always provide consistent PCI addresses, especially when new devices are added to the system or when the drive is moved to a different physical connector/port. To gurantee a consistent device name is used, `/dev/disk/by-id/` is should be referenced instead. In my case, I was not aware of this when originally setting up my ZFS pool. Below is how I handled this migration with no downtime.

#### Get drive details

Use `zpool status` to the the unique storage identifier (WWN) of a drive that needs to be migrated. While we're here, double check that the pool state is ONLINE and all looks normal.

```sh
$ zpool status sas-pool
  pool: sas-pool
 state: ONLINE
config:
        NAME                                              STATE     READ WRITE CKSUM
        sas-pool                                          ONLINE       0     0     0
          raidz3-0                                        ONLINE       0     0     0
            scsi-35002538455664500                        ONLINE       0     0     0
            ...
```

In this case, the WWN would be `5002538455664500`, by omitting the `3`. Use `lsblk` to translate this into a serial number. Here, we my serial number for `/dev/sdm`.

```sh
$ lsblk -o NAME,SERIAL,WWN | grep 5002538455662740
sdm     S182NEAG609573       0x5002538455662740
├─sdm1                       0x5002538455662740
└─sdm9                       0x5002538455662740
```

Using this serial number, we will identify the device path under `/dev/disk/by-id/`

```sh
$ ls /dev/disk/by-id/ | grep 'S182NEAG609573'
scsi-SNETAPP_X438_1625400MCSG_S182NEAG609573 # This one!
scsi-SNETAPP_X438_1625400MCSG_S182NEAG609573-part1
scsi-SNETAPP_X438_1625400MCSG_S182NEAG609573-part9
```

#### Swap the drive locations

Here we will offline the old drive, then replace with the new one. We can expect at least one error about the drive already being in a pool which we will get past using `zpool labelclear -f`

```sh
# Offline the drive with zpool
$  zpool offline sas-pool csi-35002538455662740

# Attempt to replace the drive
$ zpool replace sas-pool scsi-35002538455662740 /dev/disk/by-id/scsi-SNETAPP_X438_1625400MCSG_S182NEAG609573
/dev/disk/by-id/scsi-SNETAPP_X438_1625400MCSG_S182NEAG609573-part1 is part of active pool 'sas-pool'

# Clear the label and attempt another replace. Do again if another error appears
$ zpool labelclear -f /dev/disk/by-id/scsi-SNETAPP_X438_1625400MCSG_S182NEAG609573-part1
$ zpool replace sas-pool scsi-35002538455662740 /dev/disk/by-id/scsi-SNETAPP_X438_1625400MCSG_S182NEAG609573
```

#### Wait for resliver to complete

Once thre replace is run, zfs will initiate a resliver to ensure the new drive is ready for use. Wait for this to complete.

When the resliver is complete, the previous drive reference will automatically be removed. Repeat for all remaining drives.

```sh
$ zpool status sas-pool
  pool: sas-pool
 state: DEGRADED
status: One or more devices is currently being resilvered.  The pool will
        continue to function, possibly in a degraded state.
action: Wait for the resilver to complete.
  scan: resilver in progress since Sat Aug 16 17:04:48 2025
        1.97T scanned at 9.79G/s, 1.55T issued at 7.71G/s, 3.62T total
        30.9G resilvered, 42.85% done, 00:04:34 to go
config:

        NAME                                                STATE     READ WRITE CKSUM
        sas-pool                                            DEGRADED     0     0     0
          raidz3-0                                          DEGRADED     0     0     0
            replacing-6                                     DEGRADED     0     0     0
              scsi-35002538455662740                        OFFLINE      0     0     0
              scsi-SNETAPP_X438_1625400MCSG_S182NEAG609573  ONLINE       0     0     0  (resilvering)
```

### Server

Followed democratic-csi [installation steps](https://github.com/democratic-csi/democratic-csi?tab=readme-ov-file#zol-zfs-generic-nfs-zfs-generic-iscsi-zfs-generic-smb-zfs-generic-nvmeof)

```sh
sudo -i
apt install nvme-cli -y

# get the nvme fabric modules
apt install linux-generic -y

# ensure nvmeof target modules are loaded at startup
cat <<EOF > /etc/modules-load.d/nvmet.conf
nvmet
nvmet-tcp
nvmet-fc
nvmet-rdma
EOF

# load the modules immediately
modprobe nvmet
modprobe nvmet-tcp
modprobe nvmet-fc
modprobe nvmet-rdma

# install nvmetcli and systemd services
git clone git://git.infradead.org/users/hch/nvmetcli.git
cd nvmetcli

## install globally
python3 setup.py install --prefix=/usr
apt install python3-pip -y
pip install configshell_fb

## install to root home dir
python3 setup.py install --user
pip install configshell_fb --user

# prevent log files from filling up disk
mkdir ~/.nvmetcli
ln -sf /dev/null ~/.nvmetcli/log.txt
ln -sf /dev/null ~/.nvmetcli/history.txt

# install systemd unit and enable/start
## optionally to ensure the config file is loaded before we start
## reading/writing to it add an ExecStartPost= to the unit file
##
## ExecStartPost=/usr/bin/touch /var/run/nvmet-config-loaded
##
## in your dirver config set nvmeof.shareStrategyNvmetCli.configIsImportedFilePath=/var/run/nvmet-config-loaded
## which will prevent the driver from making any changes until the configured
## file is present
vi nvmet.service

# install, start, and enable service
cp nvmet.service /etc/systemd/system/
mkdir -p /etc/nvmet
systemctl daemon-reload
systemctl enable --now nvmet.service
systemctl status nvmet.service

# create the port(s) configuration manually
echo "
cd /
ls
" | nvmetcli

# do this multiple times altering as appropriate if you have/want multipath
# change the port to 2, 3.. each additional path
# the below example creates a tcp port listening on all IPs on port 4420
echo "
cd /ports
create 1
cd 1
set addr adrfam=ipv4 trtype=tcp traddr=0.0.0.0 trsvcid=4420

saveconfig /etc/nvmet/config.json
" | nvmetcli
```

## SSH key generation

The client/server pair will use an SSH key for authentication. We will create a dedicated key for this purpose:

```sh
ssh server_hostname

# Generate key pair and add to authorized keys
ssh-keygen -f /home/ubuntu/.ssh/id_rsa_zfs_nvmeof -N ''
cat ~/.ssh/id_rsa_zfs_nvmeof.pub >> ~/.ssh/authorized_keys

# Get the public key and create a secret containing its value
```
