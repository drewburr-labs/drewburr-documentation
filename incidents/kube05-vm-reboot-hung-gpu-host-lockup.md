# kube05: In-Guest Reboot With a Hung Passed-Through GPU Locks Up the Hypervisor Host

## 2026-05-18 — Summary

During planned remediation of the recurring Battlemage GT1 hang
([`kube05-xe-gt1-hang-maul-transcode.md`](./kube05-xe-gt1-hang-maul-transcode.md)),
the documented runbook step `ssh ubuntu@192.168.4.45 'sudo systemctl reboot'`
was executed **while the passed-through Arc GPU was still hard-hung**
(`guc_exec_queue_timedout_job` loop active).

kube05 is a **virtual machine** with the Arc B-series GPU **PCI-passed-through
(VFIO)** from a physical hypervisor host. The in-guest reboot triggered a
device teardown + PCI reset of the wedged GPU. Because the card was in an
unrecoverable state, the reset never completed — and this time the stuck
reset was on the **host** side of the passthrough. **The entire physical
hypervisor went down, taking every VM on it with it**, not just kube05.
Recovery required a physical / IPMI-BMC cold power cycle of the hypervisor
host.

This is a **distinct incident** from
[`kube05-xe-unbind-lockup.md`](./kube05-xe-unbind-lockup.md) (which is about
the in-guest driver *unbind* deadlocking the *node*), but it is the **same
root hazard** — any code path that asks unresponsive Battlemage hardware to
reset/release will block forever — reached through a **different door (guest
reboot)** and with a **larger blast radius (the whole hypervisor)**.

---

## Topology (why this is possible at all)

```
physical hypervisor host
└── VFIO PCI passthrough of Arc B-series GPU  (host vfio-pci  ⇄  guest)
    └── kube05  (VM, 192.168.4.45, k3s node)
        └── xe driver → /dev/dri/renderD128 → Plex HW transcode
```

A "reboot" of kube05 is not a bare-metal reboot. On guest shutdown:

1. The guest `xe` driver tears down and releases the PCI device.
2. The guest exit / QEMU triggers a **function-level reset (FLR)** of the
   passed-through GPU on the **host** `vfio-pci` driver before the device can
   be reused or the VM restarted.
3. Host `vfio-pci` waits for the Battlemage card to acknowledge the reset.

Steps 1–3 all assume the GPU is responsive. When GT1's GuC is already wedged,
**every one of them can block on unresponsive hardware** — and step 3 blocks
the *host*, not the guest.

---

## Identifying the Issue

### Preconditions that made this dangerous

The GPU was **confirmed hung before the reboot was issued**:

```text
xe 0000:00:10.0: [drm] GT1: trying reset from guc_exec_queue_timedout_job [xe]
... (dmesg ring buffer 100% saturated; DRM_IOCTL_VERSION → ECANCELED)
```

This is the exact state in which the
[unbind-lockup incident](./kube05-xe-unbind-lockup.md) established that the
driver "has already given up on the hardware" and **no orderly
release/reset path is safe**. A guest reboot is an orderly release + reset
path. The hazard was therefore already documented in principle — it was not
recognized that an in-guest `reboot` is in the same hazard class as `unbind`.

### Symptoms after the reboot was issued

- kube05 → `NotReady` (expected for a reboot) **and never returned**.
- `192.168.4.45` unreachable by SSH **and ICMP** — not just the k8s node
  down, the host network gone.
- Every other VM on the same hypervisor also unreachable (full host outage).
- No clean shutdown / no panic on host console — the host is **live-locked**
  in the vfio-pci reset wait, same signature class as the unbind deadlock
  (kernel threads in `D` / `TASK_UNINTERRUPTIBLE`, no oops).

---

## Root Cause

Battlemage `xe` support (kernel ≤ 6.17.x at time of incident) does not bound
its GPU reset / GuC-acknowledge waits with a timeout that tolerates dead
hardware. Under PCI passthrough this defect is **inherited by the host**:
the host `vfio-pci` FLR of a wedged Battlemage card during guest
shutdown/reboot never completes, and the host stops making forward progress.

Contributing/process cause: the remediation runbooks in **both** prior kube05
incidents prescribe an **in-guest reboot** as the recovery step, without a
guard checking GPU state first. But the situation that triggers the
remediation *is, by definition, a hung GPU* — so following the runbook
literally walked straight into this lockup. The runbooks were written as if
kube05 were bare metal; they did not account for the GPU being a
host-passed-through device whose reset can hang the hypervisor.

---

## Resolution

### Emergency recovery (host is already locked)

1. **Cold power-cycle the entire hypervisor host** via IPMI/BMC, or physically
   if no remote power control. The host is live-locked in a vfio reset wait;
   there is no clean shutdown path and SSH/ACPI will not work.
2. On host boot, let the kube05 VM autostart (or start it). It boots the
   already-installed `6.17.0-29` kernel + updated `linux-firmware`.
3. Verify kube05 `Ready`, `uname -r` = the new kernel, and
   `sudo dmesg | grep -i guc_exec_queue_timedout_job` is **empty**.
4. Confirm Intel GPU plugin healthy and a Plex HW transcode succeeds.
5. Uncordon kube05 first; once workloads are confirmed healthy, uncordon the
   rest of the cluster.

### THE RULE — never do this again

> **Never `reboot`, `shutdown`, `poweroff`, or otherwise gracefully cycle the
> kube05 *guest* while the passed-through GPU is hung. Never `virsh reboot`
> /`virsh shutdown` it from the host either. When the GPU is wedged, the only
> safe recovery is a cold power cycle of the physical hypervisor host.**

Decision gate to apply **before any kube05 reboot**, automated or manual:

```bash
# Run ON kube05. If this prints ANYTHING, the GPU is hung.
ssh ubuntu@192.168.4.45 'sudo dmesg | grep -m1 guc_exec_queue_timedout_job'
```

| dmesg check result | GPU state | ONLY safe action |
|--------------------|-----------|------------------|
| empty | healthy | In-guest `sudo systemctl reboot` is safe (normal maintenance). |
| any match | **hung** | **Do NOT touch the guest or VM lifecycle. Cordon/drain via kubectl, then cold power-cycle the physical hypervisor host (IPMI/BMC). Accept that every VM on that host bounces.** |

There is **no** safe in-guest or host-side `virsh`-graceful path to recover a
hung passed-through Battlemage GPU. Forced VM stop (`virsh destroy`) still
triggers a host-side device reset and is **not** proven safe — treat a cold
host power cycle as the only sanctioned recovery until proven otherwise.

---

## Prevention

1. **Amended runbooks (done):** the recovery sections of
   [`kube05-xe-gt1-hang-maul-transcode.md`](./kube05-xe-gt1-hang-maul-transcode.md)
   and [`kube05-xe-unbind-lockup.md`](./kube05-xe-unbind-lockup.md) now carry
   a prominent warning and link here, replacing the bare "in-guest reboot"
   step with the decision gate above.
2. **Pre-reboot guard:** any automation that reboots kube05 (manual runbook,
   cron, ansible, Claude-driven ops) MUST run the dmesg decision gate first
   and refuse the in-guest reboot on a match. A hung GPU is precisely when a
   reboot is most tempting and most catastrophic.
3. **Detection ties in:** the GT-hang alert proposed in the gt1-hang incident
   ("Detection & Alerting") should explicitly route to *"do NOT reboot the
   guest — host power cycle only"* runbook text, not a generic "reboot the
   node" action.
4. **Blast-radius documentation:** record which other VMs share the
   hypervisor with kube05 so the cost of the mandatory host power cycle is
   known up front. *(TODO: enumerate co-resident VMs and the hypervisor
   platform / IPMI address — left blank deliberately rather than guessed.)*
5. **Long-term:** a GPU reset that tolerates dead hardware is an upstream
   `xe`/`vfio-pci` concern; track Battlemage FLR/GuC-timeout fixes when
   bumping the host kernel too (the *host's* vfio-pci + kernel matter here,
   not only the guest's).

---

## Cross-References

- [`kube05-xe-gt1-hang-maul-transcode.md`](./kube05-xe-gt1-hang-maul-transcode.md)
  — the underlying recurring GPU hang whose remediation triggered this.
- [`kube05-xe-unbind-lockup.md`](./kube05-xe-unbind-lockup.md) — same root
  hazard (unresponsive Battlemage + a reset/release path) via driver unbind;
  node-scoped blast radius. This incident is the hypervisor-scoped sibling.

## Timeline / Recurrence Tracking

| Date | Trigger | Blast radius | Recovery |
|------|---------|--------------|----------|
| 2026-04-19 | in-guest `xe` PCI unbind on hung GT | kube05 node live-lock | physical/IPMI power cycle of node |
| 2026-05-18 | in-guest `systemctl reboot` on hung GT (passthrough) | **entire hypervisor host + all its VMs** | physical/IPMI power cycle of host |

Pattern: each attempt to recover a hung Battlemage card *through any
reset/release path* has escalated the outage. The only non-escalating
recovery is a cold power cycle of the lowest responsive layer that owns the
physical device — here, the hypervisor host.
