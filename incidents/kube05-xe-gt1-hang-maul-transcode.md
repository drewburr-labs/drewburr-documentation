# kube05: Battlemage GT1 Hang Recurrence (Plex HW Transcode Dead)

## 2026-05-18 — Summary

The Arc B570 (Battlemage) on `kube05` is hard-hung again — same failure mode
as [`kube05-xe-unbind-lockup.md`](./kube05-xe-unbind-lockup.md) (2026-04-19),
roughly one month later. GT1's GuC firmware queue is wedged and the `xe`
driver is stuck in an unrecoverable `guc_exec_queue_timedout_job` reset loop.
All Plex hardware transcoding is dead; `DRM_IOCTL_VERSION` returns
`ECANCELED`.

Unlike the April incident, the node has **not** been touched with an
unbind/rmmod, so it is still `Ready` and on the network — but degraded
(`load average ~27`, kernel log flooded). This incident documents the
recurrence and its trigger; recovery is the known drain+reboot procedure.

### Trigger

User attempted to play **"Maul"** (4K HDR HEVC) through Plex. The original
quality stream required a GPU transcode + HDR tone-map; that workload wedged
GT1. Playback only succeeded after manually forcing 1080p, which avoided the
(now-dead) hardware transcode path. The GT hang persisted after playback
stopped.

---

## Identifying the Issue

### Step 1: Plex container log is pure DRM failure spam

```bash
kubectl logs plex-plex-0 | tail
```

```text
DRM_IOCTL_VERSION failed: Operation canceled
DRM_IOCTL_VERSION failed: Operation canceled
... (continuous)
```

PMS's own transcode-session logs live in `/config/.../Logs/` inside the pod,
not on container stdout — not needed here, the stdout signature is conclusive.

### Step 2: Cluster-side config is healthy — rules out regression

- `plex-plex-0` (on `kube05`): `gpu.intel.com/xe=1` allocated,
  `appArmorProfile: Unconfined` confirmed applied to the live container.
- `intel-gpu-plugin-default-*` on kube05: healthy, advertising
  `/dev/dri/card1` + `renderD128` (PCI `0000:00:10.0`),
  `gpu.intel.com/xe: 10` allocatable.

So the `values.yaml` AppArmor fix is deployed and working — this is **not**
the cri-containerd AppArmor problem. The failure is below the container.

### Step 3: Node confirms a hung GT

```bash
ssh ubuntu@192.168.4.45 'uptime; lsmod | grep ^xe; ls -l /dev/dri/; \
  sudo dmesg | grep -iE "xe 0000:00:10" | tail'
```

```text
00:38:50 up 29 days, load average: 26.91, 26.32, 26.41
xe                   3874816  4
crw-rw---- 1 root render 226, 128 ... /dev/dri/renderD128
xe 0000:00:10.0: [drm] GT1: trying reset from guc_exec_queue_timedout_job [xe]
... (ring buffer 100% overwritten by this line, microseconds apart)
```

Driver loaded, device nodes present, plumbing fine — the GPU itself is
wedged. `dmesg` and the persistent journal are entirely flooded by the reset
spam, so the original triggering error is no longer recoverable from logs.
Sustained `load average ~27` on an otherwise idle node is the log-flood +
blocked GPU kworkers.

---

## Root Cause

Same underlying bug as the April incident: a Plex media transcode submitted
work that wedged GT1 (the Battlemage media engine), and the `xe` driver's GT
reset / GuC recovery path on `6.17.0-20-generic` cannot recover an
unresponsive GuC. The driver gives up and loops on
`guc_exec_queue_timedout_job` forever. Any DRM ioctl against the device
returns `ECANCELED`.

This is now a **recurring** failure (~30 days apart), not a one-off — a 4K
HDR transcode is a reliable reproducer. Treat the Battlemage HW transcode
path as unstable on this kernel until an upstream GuC scheduler fix lands.

---

## Resolution

The only safe recovery is a cold reboot. **Do not unbind/rmmod the hung
device** — the April incident proved that deadlocks the node and forces an
IPMI power cycle. See [`kube05-xe-unbind-lockup.md`](./kube05-xe-unbind-lockup.md).

```bash
kubectl cordon kube05
kubectl drain kube05 --ignore-daemonsets --delete-emptydir-data
ssh ubuntu@192.168.4.45 'sudo systemctl reboot'
kubectl get nodes -w          # wait for Ready
kubectl uncordon kube05
```

Post-reboot verification:

```bash
ssh ubuntu@192.168.4.45 'sudo dmesg | grep -i guc_exec_queue_timedout_job'  # expect empty
```

Then confirm a HW transcode succeeds in Plex.

---

## Single Point of Failure

**kube05 is the only node advertising `gpu.intel.com/xe`.** Consequences:

- There is no HW transcode anywhere else in the cluster. While kube05 is
  drained/rebooting, `plex-plex-0` cannot reschedule onto another GPU node —
  Plex HW transcode is fully unavailable cluster-wide for the duration, not
  just "briefly degraded."
- This changes the drain calculus: the question is not "can Plex move?" (it
  can't) but "is a window of zero HW transcode + ingress-down acceptable
  now?" Plan the reboot accordingly.
- Longer term, a second `gpu.intel.com/xe` node would remove both this SPOF
  and the ingress-coupling problem below.

## Detection & Alerting (currently none — gap)

This incident was found only because a user hit a playback failure. There is
no monitoring that catches a hung GT. Recommended additions:

- **dmesg watchdog → metric:** a node-exporter textfile-collector script (or
  small systemd timer) that greps `dmesg`/`journalctl -k` for
  `guc_exec_queue_timedout_job` and emits a metric (e.g.
  `node_gpu_gt_hung{device="0000:00:10.0"} 1`). Alert on `== 1`.
- **Load proxy:** alert on sustained high `node_load1` with low CPU
  utilization on kube05 — the log-flood + blocked GPU kworkers drive
  `load ~27` on an otherwise idle node, which is a strong secondary signal.
- **Synthetic:** periodic `DRM_IOCTL_VERSION` probe against
  `/dev/dri/renderD128` (the trivial ioctl that returns `ECANCELED` when the
  GT is hung) reported as a metric.

## Auto-Mitigation (open idea)

A node watchdog that, on first detection of `guc_exec_queue_timedout_job`,
automatically `kubectl cordon`s kube05 and alerts. This stops new transcode
jobs from piling onto an already-dead GPU and dragging the node to
`load ~27`, buying time for a controlled drain+reboot instead of an
emergency one. (Do **not** have it auto-unbind/rmmod — that path deadlocks
the node, see the April incident.)

## Data To Capture BEFORE Rebooting

The dmesg ring buffer and persistent journal get **100% overwritten** by the
reset spam within minutes, and a full `journalctl -k` scan times out. Grab
these first, tightly scoped, before the evidence is gone:

```bash
# First hang timestamp — scope by time, do NOT full-scan.
ssh ubuntu@192.168.4.45 'sudo journalctl -k --since "today" --no-pager \
  | grep -m1 guc_exec_queue_timedout_job'
# GuC/HuC firmware versions loaded for this device.
ssh ubuntu@192.168.4.45 'sudo journalctl -k -b --no-pager \
  | grep -iE "xe 0000:00:10|GuC|HuC|firmware" \
  | grep -v guc_exec_queue_timedout_job'
# Pending kernel — a newer image may carry Battlemage GuC fixes.
ssh ubuntu@192.168.4.45 'uname -r; apt list --upgradable 2>/dev/null \
  | grep linux-image'
```

## Reproduction Scope (unconfirmed)

"4K HDR HEVC wedges GT1" is **inferred from a single title** ("Maul"). It is
not yet established whether the trigger is:

- any HW transcode at all,
- any 4K transcode,
- 4K **HDR** specifically (HDR tone-mapping on the media engine), or
- something content-specific to that file.

Deliberately reproducing it is destructive (it wedges the node to
`load ~27` and requires a reboot), so narrowing this down should be
**opportunistic** — record source codec/resolution/HDR and client transcode
decision each time it recurs rather than triggering it on purpose.

## Upstream / Recurrence Tracking

Log the following on **every** recurrence so the cadence and whether kernel
bumps help is trackable over time:

| Date | Kernel | GuC/HuC fw | Trigger (codec/res/HDR) | Notes |
|------|--------|-----------|-------------------------|-------|
| 2026-04-19 | 6.17.0-20-generic | (not captured) | (not captured) | recovery unbind → node lockup |
| 2026-05-18 | 6.17.0-20-generic | (not captured) | 4K HDR HEVC ("Maul") | node stayed Ready; HW transcode dead |

~30-day recurrence so far. Battlemage `xe` support mainlined in 6.11+ and
still receiving GuC scheduler stability fixes — check release notes / Intel
`xe` driver bug tracker for GT-reset and GuC-timeout fixes when bumping the
kernel, and record the upstream reference here.

## Notes / Follow-ups

- **Ingress impact:** ingress-nginx-external and ingress-nginx-internal run
  on kube05 — draining/rebooting takes public ingress down. Move the ingress
  controllers first if this must happen during the day. (Compounds with the
  GPU SPOF above — kube05 is doubly load-bearing.)
- **Recurrence mitigation (open):** until the kernel/GuC fix lands, options to
  stop this from recurring on every 4K HDR title:
  - Check `apt list --upgradable | grep linux-image` on the node before
    reboot — a newer kernel may carry Battlemage GuC scheduler fixes.
  - Consider capping Plex's transcode (e.g. disable HW HDR tone-mapping, or
    cap max transcode resolution) so a single 4K HDR stream can't wedge GT1.
  - Pre-transcode / keep 1080p SDR versions of 4K HDR HEVC content.
- **`values.yaml` comment:** the comment at `k8s/plex/plex/values.yaml:32`
  attributes `DRM_IOCTL_VERSION` failures to the cri-containerd AppArmor
  profile. That fix is live and correct, but the comment now reads as if
  AppArmor is the *only* cause of this error. Worth a note that the identical
  symptom also appears on a hung GT (see this incident) so future debugging
  doesn't chase AppArmor when the real issue is a wedged GPU.
