# etcd-backup

Copies k3s etcd snapshots off kube01, the cluster's only etcd member, to a
`zfs-nfs` PVC on storage01.

- k3s on kube01 takes scheduled snapshots at 00:00 and 12:00 into
  `/var/lib/rancher/k3s/server/db/snapshots` (keeps 5) on the PLP NVMe.
- The `etcd-snapshot-copy` CronJob runs at 00:30 on kube01. It copies any
  snapshot not already on the `etcd-snapshots` PVC, then deletes copies
  older than 30 days.
- The job runs as root because k3s writes snapshots root-owned, mode 0600.
  All capabilities are dropped and the root filesystem is read-only.
- kube01 is tainted `CriticalAddonsOnly=true:NoExecute`. The job tolerates
  it, and so does the `democratic-csi-zfs-nfs` node plugin, so the PVC can
  mount there.

Restore with `k3s server --cluster-reset --cluster-reset-restore-path=<snapshot>`
on kube01, using a file copied back from the PVC.
