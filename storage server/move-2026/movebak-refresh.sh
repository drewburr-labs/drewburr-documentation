#!/bin/bash
# Refresh the movebak USB pool from sas-pool (syncoid, incremental) and the curated Plex tv list plus books/manual (rsync).
# Runs ON storage01. From this directory:
#   ssh storage01.drewburr.com 'mkdir -p /tmp/move-2026' && scp tv_backup_list.txt storage01.drewburr.com:/tmp/move-2026/
#   ssh storage01.drewburr.com 'bash -s' < movebak-refresh.sh
# Run after scale-down.sh so the snapshots are consistent. Logs to /var/log/movebak-refresh-<date>.log on storage01.
set -u
LIST=/tmp/move-2026/tv_backup_list.txt
[ -s "$LIST" ] || { echo "missing $LIST; scp tv_backup_list.txt first" >&2; exit 1; }
LOG=/var/log/movebak-refresh-$(date +%F-%H%M).log
exec > >(sudo tee -a "$LOG") 2>&1
echo "== start $(date)"
sudo zpool list movebak >/dev/null || { echo "movebak is not imported"; exit 1; }
sudo syncoid -r --compress=none --sendoptions=Lce sas-pool/k8s/nvmeof/dataset movebak/sas-pool
echo "== syncoid exit $? $(date)"
SRC=/lake/k8s/nvmeof/dataset/pvc-1a6ee17d-54a9-47e3-808f-b266d21d1fd9
sudo rsync -ar --info=progress2 --files-from="$LIST" "$SRC/media/tv/" /movebak/plex/tv/
echo "== tv rsync exit $? $(date)"
sudo rsync -a --info=progress2 "$SRC/books/"  /movebak/plex/books/
sudo rsync -a --info=progress2 "$SRC/manual/" /movebak/plex/manual/
echo "== done $(date)"
sudo zpool list movebak
sudo zpool status movebak | grep -E "state|errors"
sudo zfs list -t snapshot -r movebak -o name,creation -s creation | tail -1
