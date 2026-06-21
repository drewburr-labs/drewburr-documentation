# kube03 — Wedged nvme-tcp Connection Blocking PVC Attach

## 2026-06-21 — `plex-jackettfeed-0` Stuck in ContainerCreating

### Summary

`plex-jackettfeed-0` would not start, stuck in `ContainerCreating` with its `jackettfeed-config` PVC (`zfs-nvmeof`, NQN `…pvc-0369346f`) failing every `NodeStageVolume` retry with `unable to attach any nvme devices`.

Root cause was **initiator-side** on `kube03`: a stale nvme-tcp controller for the NQN was wedged — the kernel still reported it `live`, but the underlying TCP socket was dead, spamming `failed to send request -32` (EPIPE). Its block device was still mounted by the previous (stuck) pod sandbox, so the new pod could not get a clean attach. The storage target and data were healthy throughout.

### Affected Pod

`plex-jackettfeed-0` on `kube03` (namespace `plex`)

### Investigation

The CSI node plugin (`democratic-csi-zfs-nvmeof-node-m68lw` on kube03) logged repeated stage failures:

```
NodeStageVolume ... nqn.2003-01.org.linux-nvme:pvc-0369346f-8ee0-44fa-81c2-a321eadb38ed
  transports: tcp://storage01.drewburr.com:4420
handler error - NodeStageVolume error: "unable to attach any nvme devices"
```

Pod events confirmed the mount failure plus a hung teardown of the prior pod sandbox:

```
Warning  FailedMount    MountVolume.MountDevice failed ... unable to attach any nvme devices
Warning  FailedKillPod  error killing pod ... KillContainerError: context deadline exceeded
```

**Target side (`storage01`) was fully healthy** and ruled out:

- `sas-pool` `ONLINE` / healthy; backing zvol `sas-pool/k8s/nvmeof/dataset/pvc-0369346f…` read fine
- subsystem exported, namespace `1` enabled, port 4420 listening, `attr_allow_any_host=1`
- TCP from kube03 to `192.168.4.31:4420` reachable; `nvme discover` worked

**Initiator side (`kube03`) held a wedged controller** for the NQN:

```
nvme-subsys11 - NQN=...pvc-0369346f-...
 +- nvme11 tcp traddr=192.168.4.31,trsvcid=4420 live
```

The controller was marked `live` with block device `/dev/nvme11n1` still mounted at both the CSI globalmount and the old pod sandbox (`pods/85aaca02-…`), but the connection was dead at the socket layer:

```
nvme nvme11: failed to send request -32
nvme nvme11: failed to send request -32   (repeating)
```

### Root Cause

A transient transport disruption to `storage01` left `kube03` with a zombie nvme-tcp controller: the socket died but the kernel never transitioned the controller out of `live` into reconnect/dead. Every I/O send failed with `-32` (EPIPE). Because the dead controller and its mount were still present, kubelet could not tear down the old pod sandbox (hung `KillPod`), and the rescheduled pod's `NodeStageVolume` could not establish a fresh attach → `unable to attach any nvme devices`.

This is purely an initiator-side stale-connection issue. No data was at risk — the pool and zvol were healthy and readable the whole time.

### Fix (applied)

#### 1. Force-delete the stuck pod

Releases kubelet's hold on the old sandbox/mount:

```sh
kubectl delete pod plex-jackettfeed-0 -n plex --force --grace-period=0
```

#### 2. Unmount lingering devices and disconnect the wedged controller on kube03

```sh
# Unmount any remaining mounts of the stale device
for m in $(findmnt -rn -S /dev/nvme11n1 -o TARGET); do
  sudo umount -f "$m" || sudo umount -l "$m"
done

# Disconnect the wedged controller by NQN
sudo nvme disconnect -n nqn.2003-01.org.linux-nvme:pvc-0369346f-8ee0-44fa-81c2-a321eadb38ed
```

The `disconnect` cleared the controller cleanly despite the broken queue (exit 0, "disconnected 1 controller(s)"). CSI then auto-re-staged a fresh controller (`nvme-subsys0`) and the new pod attached and reached `Running`.

### Notes / Recurrence

- The signature is `failed to send request -32` in `dmesg` for an nvme controller still reporting `state=live`, combined with `unable to attach any nvme devices` on the CSI node plugin. The same disconnect-and-restage sequence applies to any `zfs-nvmeof` PVC showing this pattern, substituting the relevant NQN / device.
- If `nvme disconnect` itself hangs on the dead queue, escalate to `nvme reset /dev/nvmeN`, and as a last resort reboot the node. On control-plane/etcd nodes (kube02/kube03) that is a drain-first operation.
- Related, but a distinct root cause (target-side memory pressure causing read-only remounts): [storage01 NVMe-oF I/O errors](storage01-nvmeof-readonly-oom.md).
