# kube05: Soft-Lockup on xe PCI Unbind with Hung Battlemage GT1

## 2026-04-19 — Summary

Attempting to recover a hung Arc B570 (Battlemage) by unbinding the PCI
device from the `xe` kernel driver caused an unrecoverable kernel soft-lockup
on `kube05`. The node became `NotReady`, stopped responding to SSH and ping,
and required a physical / IPMI power cycle to restore. Ingress (nginx-external
and nginx-internal live on this node), Minecraft pods, and the Plex stack's
node-local components were offline for the duration.

The underlying GPU hang was a separate problem — this incident is specifically
about the recovery attempt making things worse.

---

## Identifying the Issue

### Step 1: `guc_exec_queue_timedout_job` spam in dmesg

On the affected node, the xe driver repeatedly logging GT reset attempts is
the leading indicator that the GPU is in an unrecoverable state:

```bash
ssh ubuntu@<node>.drewburr.com 'sudo dmesg -T | grep -iE "xe 0000|guc" | tail -30'
```

```text
xe 0000:00:10.0: [drm] GT1: trying reset from guc_exec_queue_timedout_job [xe]
xe 0000:00:10.0: [drm] GT1: trying reset from guc_exec_queue_timedout_job [xe]
xe 0000:00:10.0: [drm] GT1: trying reset from guc_exec_queue_timedout_job [xe]
... (hundreds of identical lines, microseconds apart)
```

`GT1` is the media engine on Battlemage. These messages mean the GuC firmware
is not executing submitted jobs and the driver has given up trying to schedule
anything new. Any DRM ioctl against the device (including the trivial
`DRM_IOCTL_VERSION`) returns `ECANCELED` (errno 125):

```c
/* Minimal repro — returns ECANCELED when GT is hung. */
int fd = open("/dev/dri/renderD128", O_RDWR);
struct drm_version v = {0};
ioctl(fd, DRM_IOCTL_VERSION, &v);   /* -1, errno=125 */
```

### Step 2: Unbind-path deadlock

Once the driver is in this state, running

```bash
echo 0000:00:10.0 | sudo tee /sys/bus/pci/drivers/xe/unbind
```

triggers `xe`'s `.remove()` callback, which:

1. Takes the device lock.
2. Flushes pending GPU work and issues an orderly GT shutdown.
3. Waits for GuC on each GT to acknowledge the reset.

Because GT1's GuC was already hung, step 3 never completes. The kernel thread
doing the unbind blocks in `D` state (`TASK_UNINTERRUPTIBLE`) holding the
device lock. Other threads that need that lock — TTM buffer teardowns waiting
on `dma_fence`s tied to jobs on the hung GT, kworkers handling DRM minor
cleanup — pile up behind it. Eventually enough critical kernel threads are in
`D` state that the system stops making forward progress on unrelated paths
(network softirqs, kubelet heartbeat) and the node drops off the network.

From outside the cluster, this looks like:

```bash
$ kubectl get nodes
NAME     STATUS     ROLES    AGE
kube05   NotReady   <none>   311d

$ ping kube05.drewburr.com
100% packet loss
```

The kernel has not panicked — it is live-locked. There is no oops or stack
trace in the console because nothing has crashed; kernel threads are simply
blocked forever.

---

## Root Cause

The xe driver's teardown path in 6.17.0-20-generic assumes the hardware is
responsive. It does not have a timeout on the GuC acknowledgement during
`.remove()`, so a pre-hung GT turns orderly unbind into an unbounded wait.

This is a well-known class of failure on new GPU drivers — the same pattern
has shown up historically in `i915`, `amdgpu`, and `nouveau` when the GPU is
in an unrecoverable state before the driver is asked to release it. xe on
Battlemage is particularly exposed because the hardware is new (mainlined
support in 6.11+, still seeing stability fixes) and the error-injection
coverage in the teardown path is thinner than on mature platforms.

### Why GT1 hung in the first place

Repeated Plex libva init attempts against a broken ABI-shim path earlier in
the session likely submitted a malformed command to the media engine, which
wedged GT1. That's the precipitating bug, but the *lesson of this incident*
is about the recovery attempt, not the initial hang.

---

## Resolution

### Do not attempt rmmod/unbind on a hung GPU

Once `guc_exec_queue_timedout_job` messages appear in dmesg, the driver has
already given up on the hardware. Any attempt to unwind state through the
driver is a coin flip — the recovery code paths are not tolerant of
unresponsive hardware. The safe recovery is a cold power cycle.

### Correct procedure: drain + reboot

```bash
# 1. Cordon to prevent new schedules while draining.
kubectl cordon <node>

# 2. Drain. --ignore-daemonsets because DaemonSets don't evict cleanly;
#    --delete-emptydir-data because some pods use emptyDir scratch space.
kubectl drain <node> --ignore-daemonsets --delete-emptydir-data

# 3. Reboot. SSH first, or IPMI/BMC if SSH is already unresponsive.
ssh ubuntu@<node>.drewburr.com 'sudo systemctl reboot'

# 4. Wait for Ready.
kubectl get nodes -w

# 5. Uncordon.
kubectl uncordon <node>
```

After a clean boot the GPU is in a fresh state and DRM ioctls work normally:

```text
/dev/dri/renderD128: v1.1.0 name=xe desc=Intel Xe2 Graphics
```

### Emergency recovery (if the lockup has already happened)

1. Hard power-cycle the node via IPMI/BMC, or physically if no remote power
   control is available. The kernel is live-locked — there is no clean
   shutdown path.
2. On boot, confirm `kubectl get nodes` shows the node `Ready`.
3. Verify dmesg is clean of `guc_exec_queue_timedout_job` messages.
4. Scale workloads back up.

---

## Notes

- **The failing ioctl is `DRM_IOCTL_VERSION`, the most trivial DRM call.** If
  even that returns `ECANCELED`, the GPU is hard-hung and the driver is no
  longer a usable interface. No amount of libva / ffmpeg / Plex-side tweaking
  will recover it.

- **`lsof /dev/dri/renderD128` will show no userspace holders** while the
  module refcount is non-zero. The refcount is held by the PCI driver binding
  itself and by kernel-registered DRM minors — unbinding the PCI device is
  the only way to drop it, and that is exactly the step that deadlocks on a
  hung GT.

- **The Intel GPU device plugin on the node does not hold an fd on the DRM
  device** (confirmed via `fuser` / `lsof`). It enumerates via sysfs and
  advertises capacity to kubelet. Killing the plugin pod does not drop the
  xe module refcount — only plex (which has `gpu.intel.com/xe: 1` allocated)
  and the PCI binding do.

- **Which workloads are at risk on kube05:** ingress-nginx-external and
  ingress-nginx-internal live here, so a node outage takes the cluster's
  public ingress with it. Factor that into the decision to drain — if it has
  to happen during the day, consider moving the ingress controllers first.

- **Upstream status:** the Battlemage xe driver is still shaking out. Check
  `apt list --upgradable | grep linux-image` on the node before rebooting —
  a newer kernel may contain GuC scheduler fixes relevant to the initial GT
  hang.
