#!/bin/bash
# Move a lake member from USB to a hot-swap SAS bay without taking down sas-pool.
# Only the Plex workloads that mount lake (plex-data, plex-alt-data) go offline.
#
#   ./lake-hotswap.sh down   stop lake's consumers, record replicas, export lake
#   (on pve05: remove the USB passthrough, shuck the drive, tape the 3.3V pins, insert into a hot-swap bay)
#   ./lake-hotswap.sh up     wait for the disk on the HBA, import lake by-id, verify, scale Plex back up
#
# Needs kubectl for the lab cluster and SSH to ubuntu@storage01.drewburr.com.
set -euo pipefail
cd "$(dirname "$0")"

STORAGE=ubuntu@storage01.drewburr.com
SERIAL=${SERIAL:-Y5KTTH5C}          # drive serial (WD140EDGZ in the ASMT 2235 enclosure, bridge serial ACAAEBBB34E0)
NS=plex
STATE=state/replicas.txt
mkdir -p state

s() { ssh -o BatchMode=yes "$STORAGE" "$@"; }

# Pods (and their owning StatefulSets) that mount a lake-backed PVC.
lake_claims() {
  kubectl get pv -o json | jq -r --arg ns "$NS" \
    '.items[] | select(.spec.storageClassName=="nfs-lake" and .spec.claimRef.namespace==$ns) | .spec.claimRef.name'
}
lake_pods() {
  local claims; claims=$(lake_claims | jq -R . | jq -sc .)
  kubectl -n "$NS" get pods -o json | jq -r --argjson c "$claims" \
    '.items[] | select(any(.spec.volumes[]?; .persistentVolumeClaim.claimName as $n | $c | index($n))) | .metadata.name'
}
lake_sts() {
  local claims; claims=$(lake_claims | jq -R . | jq -sc .)
  kubectl -n "$NS" get sts -o json | jq -r --argjson c "$claims" \
    '.items[] | select(any(.spec.template.spec.volumes[]?; .persistentVolumeClaim.claimName as $n | $c | index($n))) | .metadata.name'
}

down() {
  [ -s "$STATE" ] && { echo "$STATE exists; run '$0 up' first. Refusing to overwrite." >&2; exit 1; }

  echo "== lake health"
  s 'sudo zpool status -x lake' | tee /dev/stderr | grep -q "is healthy" \
    || { echo "lake is not healthy; not exporting." >&2; exit 1; }

  echo "== recording replicas and scaling lake consumers to 0"
  for sts in $(lake_sts); do
    r=$(kubectl -n "$NS" get sts "$sts" -o jsonpath='{.spec.replicas}')
    echo "$sts $r" >> "$STATE"
    if [ "$r" != "0" ]; then kubectl -n "$NS" scale sts "$sts" --replicas=0; fi
  done
  cat "$STATE"

  echo "== waiting for pods to terminate"
  for _ in $(seq 1 60); do
    left=$(lake_pods | wc -l | tr -d ' ')
    [ "$left" = "0" ] && break
    echo "  $left pods still mounting lake..."; sleep 5
  done
  [ "$(lake_pods | wc -l | tr -d ' ')" = "0" ] || { echo "pods still running; aborting before export" >&2; exit 1; }

  echo "== NFS clients still connected to storage01 (sas-pool zfs-nfs clients are expected here;"
  echo "   stop the workstation 'jellyfin' container if it still mounts plex-alt-data)"
  s 'ss -tn state established "( sport = :2049 )" | tail -n +2 | awk "{print \$4}" | cut -d: -f1 | sort | uniq -c' || true

  echo "== exporting lake (fails safely if a dataset is still busy)"
  if ! s 'sudo zpool export lake'; then
    # Seen 2026-11-15: the Linux nfsd "courteous server" keeps delegations for a client that has
    # already unmounted (kube05), which pins the dataset. Show which NFS clients hold state on lake.
    echo "== export failed. NFS clients holding open/deleg state on lake datasets:" >&2
    s 'devs=$(awk "\$5 ~ \"^/lake\" {split(\$3,d,\":\"); printf \"%02x:%02x|\", d[1], d[2]}" /proc/self/mountinfo); devs=${devs%|}
       for c in $(sudo ls /proc/fs/nfsd/clients/); do
         n=$(sudo grep -cE "superblock: \"($devs):" /proc/fs/nfsd/clients/$c/states)
         [ "$n" -gt 0 ] && echo "  client $c $(sudo grep -h "^name:" /proc/fs/nfsd/clients/$c/info) states=$n"
       done; true' >&2
    echo "If that host has no NFS mounts left (sudo grep -c nfs /proc/mounts on it), expire the stale client:" >&2
    echo "  ssh $STORAGE 'echo expire | sudo tee /proc/fs/nfsd/clients/<id>/ctl' && $0 down-export" >&2
    exit 1
  fi
  s 'sudo zpool list lake 2>&1 | head -1' || true
  echo
  echo "lake exported. Now on pve05: remove the USB passthrough, then move the drive into a hot-swap bay."
  echo "Then run: $0 up"
}

up() {
  [ -s "$STATE" ] || { echo "no $STATE; did '$0 down' run?" >&2; exit 1; }

  echo "== waiting for serial $SERIAL to appear on the HBA"
  dev=""
  for _ in $(seq 1 24); do
    dev=$(s "ls /dev/disk/by-id/ | grep -E '^(scsi|ata)-.*_${SERIAL}\$' | grep -v usb- | head -1" || true)
    [ -n "$dev" ] && break
    echo "  not yet (rescanning)"; s 'for h in /sys/class/scsi_host/host*/scan; do echo "- - -" | sudo tee $h >/dev/null; done' || true
    sleep 5
  done
  [ -n "$dev" ] || { echo "disk $SERIAL never showed up. Check the 3.3V pins and the bay; lake is still exported." >&2; exit 1; }
  echo "  found /dev/disk/by-id/$dev"
  s "lsblk -b -d -o NAME,SIZE,LOG-SEC,PHY-SEC,TRAN,MODEL /dev/disk/by-id/$dev"

  if s 'sudo zpool list lake' >/dev/null 2>&1; then
    echo "== lake is already imported; skipping import"
  else
    # Offer ZFS only the scsi-* partition links, so a member whose old path is gone gets its
    # serial-bearing name instead of whichever by-id link sorts first (it picked wwn- on 2026-11-15).
    echo "== importing lake from scsi-* by-id links"
    s 'args=""; for l in /dev/disk/by-id/scsi-S*-part1; do args="$args -d $l"; done
       sudo zpool import $args lake || { echo "scsi-only import failed; falling back to the whole by-id dir" >&2; sudo zpool import -d /dev/disk/by-id lake; }'
  fi
  s 'sudo zpool status lake'
  if s 'sudo zpool status -P lake' | grep -q '/dev/disk/by-id/usb-'; then
    echo "lake still references a usb- path; not scaling Plex up. Investigate." >&2; exit 1
  fi
  online=$(s 'sudo zpool status -P lake' | grep -cE '^\s+/dev/disk/by-id/\S+\s+ONLINE')
  if [ "$online" != "7" ]; then
    echo "only $online of 7 lake members are ONLINE; not scaling Plex up. Check zpool status and the missing drive's bay." >&2
    exit 1
  fi
  echo "  all 7 lake members ONLINE"

  echo "== scaling lake consumers back up"
  while read -r sts r; do
    if [ "$r" != "0" ]; then kubectl -n "$NS" scale sts "$sts" --replicas="$r"; fi
  done < "$STATE"
  mv "$STATE" "state/replicas-restored-$(date +%F-%H%M).txt"
  echo "== done. Watch: kubectl -n $NS get pods -w"
}

case "${1:-}" in
  down) down ;;
  down-export) s 'sudo zpool export lake' && echo "lake exported. Next: pve05-usb-detach.sh on pve05, swap the drive, then $0 up" ;;
  up)   up ;;
  *) echo "usage: $0 down|up" >&2; exit 2 ;;
esac
