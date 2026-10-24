# pve01: unattended Proxmox VE 8.4 install

`pve01` is an Intel NUC (i7-8809G) with two NVMe drives. It was
installed on 2026-10-04 with no one at the keyboard: an automated-install
ISO is presented through the NanoKVM's virtual CD-ROM.

| Item       | Value                                                                                            |
| ---------- | ------------------------------------------------------------------------------------------------ |
| OS         | Proxmox VE 8.4 (`proxmox-ve_8.4-1.iso`), no-subscription repo                                    |
| Hostname   | `pve01.drewburr.com`                                                                             |
| Network    | Static `192.168.4.21/23` on `vmbr0.4`; VLAN-aware `vmbr0` (VLANs 4 and 6), MTU 9000. See [Networking](#networking). |
| OS disk    | Kingston DC1000B 480 GB, ext4 + LVM-thin (Proxmox default layout)                                |
| Other disk | Micron 7450 960 GB (PLP), LVM storage `nvme`. Holds kube01's etcd disk.                          |
| Root login | password (hash supplied at build time) and `~/.ssh/id_ed25519.pub`                               |
| Web UI     | `https://pve01.drewburr.com:8006`, user `root`, realm PAM                                         |

## Networking

The install set up DHCP on a plain `vmbr0` (see `first-boot.sh`). On
2026-10-24 that was replaced to match pve02, so the `kube01` VM's
VLAN-tagged NICs work:

```text
iface enp5s0 inet manual
	mtu 9000

auto vmbr0
iface vmbr0 inet manual
	bridge-ports enp5s0
	bridge-stp off
	bridge-fd 0
	bridge-vlan-aware yes
	bridge-vids 4 6
	bridge-pvid 4
	mtu 9000

auto vmbr0.4
iface vmbr0.4 inet static
	address 192.168.4.21/23
	gateway 192.168.4.1
	mtu 9000
```

- The switch port sends VLAN 4 untagged and VLAN 6 tagged. `bridge-pvid 4`
  maps untagged traffic to VLAN 4 inside the bridge.
- The host address must be on `vmbr0.4`, not `vmbr0`. With the address on
  `vmbr0`, host traffic goes out on VLAN 1, which the port isn't a member
  of, and the host drops off the network. That happened on the first
  attempt; a 3-minute auto-revert brought it back.
- MTU 9000 matches pve02. A 9000-byte ping with don't-fragment set gets
  from pve01 and kube01 to kube02. The `igb` NIC allows up to 9216.
- Backups on the host: `/etc/network/interfaces.bak-2026-10-23` (the
  original DHCP config) and `/etc/network/interfaces.bak-pre-mtu` (before
  MTU 9000).

This undoes the portability `first-boot.sh` set up. The host no longer
moves networks without editing `/etc/network/interfaces`. The dhclient
hook that keeps `/etc/hosts` in step with the lease doesn't run any more,
so `/etc/hosts` keeps whatever address it last wrote. Update it by hand if
`192.168.4.21` ever changes, because `pve-cluster` needs the hostname to
resolve to an address on the host.

## etcd K3s node: kube01

**Status: running since 2026-10-24.**

`pve01` hosts **kube01** (VM 100), a K3s server whose etcd data lives on
the **Micron 7450 PLP drive**. etcd is `fsync`-bound: every write must be
durably committed before it's acknowledged. A power-loss-protected drive
can acknowledge an `fsync` once data reaches its protected cache, so
latency stays low and in-flight writes stay safe. The host reports the
drive as `write through` (no volatile cache to flush).

| Item       | Value                                                                                     |
| ---------- | ----------------------------------------------------------------------------------------- |
| VM         | 100 `kube01`, 6 cores, 16 GiB                                                              |
| OS         | Ubuntu 26.04 cloud image (`resolute-server-cloudimg-amd64.img`) imported as `scsi0`        |
| OS disk    | `scsi0` on `local-lvm` (Kingston), 100G                                                    |
| etcd disk  | `scsi1` on `nvme` (Micron PLP), 32G, ext4 `noatime`, label `k3s-etcd`, mounted at `/var/lib/rancher/k3s/server/db` |
| Cloud-init | `ide0` drive: user `ubuntu`, kube02's SSH key, `ipconfig0` static, `ipconfig1` DHCP        |
| `net0`     | VLAN 4, `eth0`, `192.168.4.41/23`, gateway `192.168.4.1`                                   |
| `net1`     | VLAN 6, `eth1`, DHCP (`192.168.6.x`)                                                        |
| K3s        | `v1.35.2+k3s1`, server (etcd + control plane)                                              |

The etcd disk is a dedicated VM disk on the `nvme` storage, not a
passthrough. Its fstab entry mounts it by UUID, with
`x-systemd.before=k3s.service` so it's mounted before k3s starts.
1,000 synced 2.3 KB writes took 0.31 s on it, against 0.65 s on the OS
disk.

`/etc/rancher/k3s/config.yaml` on kube01:

```yaml
server: https://k3s.drewburr.com:6443
token-file: /etc/rancher/k3s/cluster-token
disable:
- servicelb
- traefik
- helm-controller
- metrics-server
etcd-expose-metrics: true
node-taint:
- "CriticalAddonsOnly=true:NoExecute"
kubelet-arg:
- "system-reserved=memory=2Gi"
- "kube-reserved=memory=2Gi"
```

- **Role.** kube01 is a full server, not etcd-only. kube02, kube03 and
  kube05 all use `--server https://kube01.drewburr.com:6443`, so kube01
  has to serve the API. The `CriticalAddonsOnly=true:NoExecute` taint
  keeps workloads off it. DaemonSets that tolerate every taint still run
  there (multus, `kubelet-summary-exporter`, `emergency-ro-exporter`).
- **Server URL.** The API certificate doesn't list `kube02.drewburr.com`
  or `kube03.drewburr.com`, so joining through those names fails CA
  validation. `k3s.drewburr.com` is in the certificate. It resolves only
  to kube02.
- **Redundancy.** etcd has three voting members: kube01, kube02 and kube03.
  The cluster keeps quorum with any one of them down. Before kube01
  joined, etcd had two members and couldn't lose either.
- **Snapshots.** A snapshot was taken on kube02 before the join
  (`pre-kube01-join-kube02-1792818301`). The scheduled `k3s etcd-snapshot`
  runs on every server, so kube01's snapshots land on its local etcd disk.

Open items:

- Ship etcd snapshots off pve01 (see the storage server `move-2026`
  runbook).
- `k3s.drewburr.com` points only at kube02, so anything using that name
  loses the API when kube02 is down.
- kube01's original empty 100G disk is still attached as `unused0`.

## Files

| File            | Purpose                                                                                                                                                       |
| --------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `answer.toml`   | Automated-install answer. It has placeholders for the root password hash and SSH key, which `build.sh` fills in, so nothing secret is committed.               |
| `first-boot.sh` | Runs once before networking on first boot. It switches `vmbr0` to DHCP, keeps `/etc/hosts` in step with the lease, and switches apt to the no-subscription repo. |
| `build.sh`      | Builds `pve01.iso` from the stock ISO with `proxmox-auto-install-assistant`, in a Debian container.                                                             |

The Proxmox installer copies the install-time DHCP lease into a
**static** `vmbr0` config. `first-boot.sh` undoes that. Without it, the
host would lose its network after moving to another subnet. The
`/etc/hosts` hook is needed because `pve-cluster` requires the hostname
to resolve to an address on the host. The running host no longer uses
this config; see [Networking](#networking).

## Build

```bash
mkdir -p ~/netboot-pve && cd ~/netboot-pve
curl -fsSLO https://enterprise.proxmox.com/iso/SHA256SUMS
curl -fsSLO https://enterprise.proxmox.com/iso/proxmox-ve_8.4-1.iso
cd -
ROOT_PASSWORD_HASH='<output of mkpasswd -m sha-512>' servers/pve01/build.sh ~/netboot-pve
```

Use single quotes around the hash, because it contains `$`. The ISO
contains the hash, so treat it as sensitive and delete it after use.

## Install

1. Serve `out/pve01.iso` over HTTP somewhere on the LAN. In the NanoKVM
   web UI, use **Image Downloader** (the toolbar download icon) to fetch it.
2. In **Images**, choose **CD ROM** mode and mount `pve01.iso`.
3. Reboot the NUC. Network boot is set to come last in its firmware, so
   the virtual CD boots and the automated installer starts by itself.
4. The answer file sets `reboot-mode = "reboot"`. **Unmount the image as
   soon as the install finishes**, or the next boot may run the installer
   again. The install took about 3 minutes. The answer's
   `post-installation-webhook` POSTs to the URL in `answer.toml` when the
   install is done; watch for that, or watch the console.
5. Delete the image from the NanoKVM.

## Why not PXE

The first attempt network-booted the installer: Fedora's signed
shim/GRUB, then the Proxmox kernel plus an initrd with the ISO appended
as `/proxmox.iso`, following
[this Proxmox forum approach](https://forum.proxmox.com/threads/automated-installation-pxe-boot.169009/).
The kernel loaded, but GRUB on the NUC failed on the ~1.6 GB initrd:

```text
error: ../../grub-core/kern/efi/mm.c:564:could not allocate all requested memory: 352580 pages still required after iterating EFI memory map.
```

iPXE might handle it, but it would add an unsigned bootloader and HTTP
plumbing. Virtual media through the KVM was simpler, and it worked first
try.

Firmware notes for these NUCs (Intel Visual BIOS): Secure Boot is off.
pve01 shipped with **Ethernet2 Boot** disabled under Boot → Boot
Configuration → Boot Devices, so it didn't network-boot until that was
enabled.

Answer-file reference:
[Automated Installation](https://pve.proxmox.com/wiki/Automated_Installation).
