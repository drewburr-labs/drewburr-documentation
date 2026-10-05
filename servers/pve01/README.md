# pve01: unattended Proxmox VE 8.4 install

`pve01` is an Intel NUC (i7-8809G) with two NVMe drives. It was
installed on 2026-10-04 with no one at the keyboard: an automated-install
ISO is presented through the NanoKVM's virtual CD-ROM.

| Item       | Value                                                                                            |
| ---------- | ------------------------------------------------------------------------------------------------ |
| OS         | Proxmox VE 8.4 (`proxmox-ve_8.4-1.iso`), no-subscription repo                                    |
| Hostname   | `pve01.drewburr.com`                                                                             |
| Network    | DHCP on `vmbr0`. Nothing about the current network is baked in, so the host can move networks. |
| OS disk    | Kingston DC1000B 480 GB, ext4 + LVM-thin (Proxmox default layout)                                |
| Other disk | Micron 7450 960 GB (PLP). The installer leaves it alone.                                          |
| Root login | password (hash supplied at build time) and `~/.ssh/id_ed25519.pub`                               |
| Web UI     | `https://<dhcp address>:8006`, user `root`, realm PAM                                             |

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
to resolve to an address on the host.

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
