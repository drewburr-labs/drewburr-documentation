#!/bin/bash
# Run on pve05 as root, AFTER `./lake-hotswap.sh down` has exported lake.
# Finds the USB passthrough entry on VM 105 for the ASM235CM bridge holding the lake disk,
# removes it (hot-unplug from the running VM), and lists every other ASM235CM enclosure on the host.
set -euo pipefail
VMID=105
BRIDGE_SERIAL=${BRIDGE_SERIAL:-ACAAEBBB34E0}   # USB bridge serial of the lake member (drive Y5KTTH5C)

echo "== ASM235CM (174c:55aa) enclosures on this host"
printf '%-12s %-14s %-6s %s\n' PORT BRIDGE_SERIAL SPEED HOST_DISK
for d in /sys/bus/usb/devices/*; do
  [ "$(cat "$d/idVendor" 2>/dev/null)" = 174c ] && [ "$(cat "$d/idProduct" 2>/dev/null)" = 55aa ] || continue
  disk=$(ls -d "$d"/*/host*/target*/*/block/* 2>/dev/null | xargs -r -n1 basename | head -1)
  info="(passed through / no host disk)"
  [ -n "$disk" ] && info="$disk $(lsblk -dno SIZE,MODEL,SERIAL /dev/$disk 2>/dev/null)"
  printf '%-12s %-14s %-6s %s\n' "$(basename "$d")" "$(cat "$d/serial" 2>/dev/null)" "$(cat "$d/speed")" "$info"
done

echo
echo "== USB entries on VM $VMID"
qm config $VMID | grep -E '^usb[0-9]+:' || echo "(none)"

port=""
for d in /sys/bus/usb/devices/*; do
  [ "$(cat "$d/serial" 2>/dev/null)" = "$BRIDGE_SERIAL" ] && port=$(basename "$d") && break
done
[ -n "$port" ] || { echo "Bridge $BRIDGE_SERIAL not found on this host. Already unplugged?"; exit 0; }
echo
echo "== lake disk bridge $BRIDGE_SERIAL is on host port $port"

entry=$(qm config $VMID | awk -v p="$port" -F': ' '$1 ~ /^usb[0-9]+$/ { n=split($2,a,","); for(i=1;i<=n;i++) if (a[i]=="host="p) print $1 }')
if [ -z "$entry" ]; then
  # Fall back to a vendor:product entry, but only if it is unambiguous.
  ids=$(qm config $VMID | awk -F': ' '$1 ~ /^usb[0-9]+$/ && $2 ~ /host=174c:55aa(,|$)/ {print $1}')
  if [ "$(echo "$ids" | grep -c .)" = 1 ]; then entry=$ids
  else echo "No USB entry on VM $VMID matches port $port (and no single 174c:55aa entry). Nothing removed."; exit 1; fi
fi

echo "== removing $entry from VM $VMID"
qm set $VMID --delete "$entry"
qm config $VMID | grep -E '^usb[0-9]+:' || echo "(no USB entries left on VM $VMID)"
echo
echo "Done. Unplug the enclosure on port $port, shuck the drive (serial Y5KTTH5C),"
echo "tape SATA power pins 1-3 (3.3V PWDIS), and slide it into a hot-swap bay."
