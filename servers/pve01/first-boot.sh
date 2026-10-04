#!/bin/bash
# Runs once, before networking, on pve01's first boot (embedded in the
# install ISO by build.sh). Makes the host network-portable:
#   1. vmbr0 uses DHCP instead of the static copy of the install lease.
#   2. /etc/hosts follows the DHCP address, because pve-cluster needs
#      the hostname to resolve to an address on this host.
#   3. apt uses the no-subscription repo instead of the enterprise one.
set -euo pipefail

port="$(awk '/^iface vmbr0/{f=1} f && /bridge-ports/{print $2; exit}' /etc/network/interfaces)"
[ -n "$port" ] || { echo "first-boot: no bridge-ports on vmbr0" >&2; exit 1; }
cat >/etc/network/interfaces <<IFACES
auto lo
iface lo inet loopback

iface $port inet manual

auto vmbr0
iface vmbr0 inet dhcp
	bridge-ports $port
	bridge-stp off
	bridge-fd 0

source /etc/network/interfaces.d/*
IFACES

mkdir -p /etc/dhcp/dhclient-exit-hooks.d
cat >/etc/dhcp/dhclient-exit-hooks.d/pve-hosts <<'HOOK'
# Keep "<ip> <fqdn> <short>" in /etc/hosts in step with the DHCP lease.
case "$reason" in
  BOUND|RENEW|REBIND|REBOOT)
    if [ "$interface" = vmbr0 ] && [ -n "$new_ip_address" ]; then
      fqdn="$(hostname -f 2>/dev/null || cat /etc/hostname)"
      short="${fqdn%%.*}"
      sed -i "/[[:space:]]$short\$/d" /etc/hosts
      echo "$new_ip_address $fqdn $short" >>/etc/hosts
    fi
    ;;
esac
HOOK

rm -f /etc/apt/sources.list.d/pve-enterprise.list /etc/apt/sources.list.d/ceph.list
echo "deb http://download.proxmox.com/debian/pve bookworm pve-no-subscription" \
  >/etc/apt/sources.list.d/pve-no-subscription.list
