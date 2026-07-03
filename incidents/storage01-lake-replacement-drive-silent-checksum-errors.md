# storage01 — lake DEGRADED again: replacement WD 14TB throwing silent checksum errors

## 2026-07-03 — 9RG9UZEC checksum-faulted 4 days after resilver; in-place recovery attempt underway

**Status: OPEN — remediation in progress** (ZFS upgraded, reboot + clear + scrub pending).

### Summary

The WD 14TB (`9RG9UZEC`, Ultrastar DC HC530, `WUH721414ALE604`) that replaced the
dead HGST on 2026-06-16 (see
[storage01-lake-drive-failure-replacement.md](storage01-lake-drive-failure-replacement.md))
started returning **silently corrupted data within 19 hours of its resilver
completing**. ZFS caught every bad block via checksum and repaired from raidz2
parity — **zero data errors, applications unaffected** — and marked the vdev
`DEGRADED` ("too many errors") on 2026-06-21 after 67 checksum errors
(0 read, 0 write).

The failure mode is completely different from the drive it replaced: the HGST
died loudly (I/O errors → dropped off the HBA); this drive completes every
command successfully but returns wrong bytes. Its SMART is immaculate, so the
drive doesn't know it's doing it.

Decision: before buying another drive, upgrade ZFS (2.3.3 → 2.4.3, removes a
known class of post-rebuild checksum bugs) and attempt in-place recovery —
`zpool clear` + full scrub — to see whether the corruption was a one-time
resilver-write event or the drive is actively corrupting.

### Timeline

| Date (UTC) | Event |
|---|---|
| 2026-06-16 03:49 | `zpool replace` old HGST → WD 14TB `9RG9UZEC`; resilver starts. |
| 2026-06-17 03:56 | Resilver completes: 9.04T in 1d 00:06, 0 errors. |
| 2026-06-17 22:39 | **First checksum error** on the new drive — 19h after resilver. Trickle follows (2× Jun 17, 2× Jun 18, 1× Jun 19). |
| 2026-06-21 06:19–06:57 | Burst of ~61 checksum errors while a read-heavy job (started ~3 min after 06:25 `cron.daily`) traversed one dataset. ZED SERD threshold hit at 06:19 → vdev `DEGRADED`. |
| 2026-07-01 09:47 | One more checksum error — the problem is still live. |
| 2026-07-03 | Investigated (this doc). ZFS userland+DKMS upgraded 2.3.3 → 2.4.3; running kmod still 2.3.3 pending reboot. |

### Diagnosis — silent corruption inside the drive, transport exonerated

Error signature: **67 cksum / 0 read / 0 write**, all 4KiB blocks, offsets
scattered across the whole disk (200GB → 8TB), `err=0` in every ZED ereport.

What rules out everything except the drive:

- **SMART is perfect** — 0 reallocated, 0 pending, 0 offline-uncorrectable,
  short+extended self-tests pass. Not media failure.
- **UDMA_CRC_Error_Count = 0.** Every SATA transfer is CRC-protected on the
  wire; cable/backplane/slot corruption gets *detected and counted* there. Zero
  means the bytes were already wrong before they hit the link — i.e. corrupted
  inside the drive (write cache / DRAM / firmware are the classic culprits for
  exactly this pattern).
- **SAS PHY counters clean** on its port (`end_device-4:23`); no kernel/ATA
  errors at all since the 2026-05-19 boot; **all five other lake drives have
  zero errors of any kind** — an HBA/PSU/host-RAM problem would spread across
  drives, not concentrate on one.
- Errors concentrate in **objset 275**
  (`lake/k8s/nvmeof/dataset/pvc-1a6ee17d-…`, the actively-read k8s PVC), and the
  **same object (id 16645) failed on Jun 19, Jun 21, and Jul 1** — consistent
  with blocks that were *written corrupt during the resilver* and get repaired
  from parity every time they're read.
- The drive is **well-used stock**: 39,721 power-on hours (~4.5 yr), 22 power
  cycles, prior self-tests logged at 15.7k/32.7k hours. This is the ex-`backup`
  raspberrypi spare from the previous incident — it started corrupting within a
  day of entering service. Likely bad on arrival.

**Software caveat (why we're upgrading ZFS before condemning the drive):** the
pool went through **raidz expansion on 2026-01-28** and runs ZFS **2.3.3**;
later releases carry "fix rare cksum errors after rebuild"-type fixes
(openzfs 2.3.7/2.3.8/2.4.x; see also openzfs/zfs#14734 for
lookalike reports). Those fixes mostly target sequential rebuilds/dRAID, not
lake's healing resilver, so the drive remains the prime suspect — but a 2.4.3
upgrade cheaply removes the software variable before the scrub test.

### Contributing finds

- **Monthly scrubs silently stopped 2026-04-30.** Ubuntu's
  `/etc/cron.d/zfsutils-linux` scrub job only scrubs *healthy* pools; `lake`
  has been continuously DEGRADED since the HGST faulted, so the May 10 and
  Jun 14 scrubs never ran. **Last completed scrub: 2026-04-12.** A degraded
  pool never scrubs itself back to visibility — latent errors on the aged
  drives go undetected exactly when redundancy is reduced.
- **Timeline correction to the previous incident doc:** the journal (persistent
  back to January) shows the old HGST `8DGT7DMH` threw **I/O + delay errors and
  FAULTED on 2026-04-30**, went `REMOVED` 2026-05-05 — it did *not* drop during
  the 2026-05-19 reboot as previously assumed. The pool was degraded ~6.5 weeks
  before being noticed, not ~4.
- Fleet context: remaining SATA HGSTs are at 40–48k power-on hours (4.6–5.5 yr,
  all SMART-clean); the two SAS HGSTs are young (~4.2k h). Temps peaked
  51–57 °C (limit 60 °C). `lake` is at 85% capacity.

### Remediation plan (stepwise, in progress)

| # | Step | Status |
|---|---|---|
| 1 | Re-enable arter97 PPA (was disabled by the noble dist-upgrade), `apt update` | ✅ 2026-07-03 |
| 2 | Upgrade `zfsutils-linux`/`zfs-dkms` → **2.4.3**; DKMS built for both kernels (6.8.0-111 running, 6.8.0-134 pending). **No `zpool upgrade`** — feature flags untouched so 2.3.3 rollback stays possible. | ✅ 2026-07-03 |
| 3 | Reboot storage01 (loads 2.4.3 kmod + pending -134 kernel). NFS to k8s stalls briefly; hard mounts recover. | ⬜ pending |
| 4 | Post-boot verify: `zfs version` 2.4.3 both lines, both pools imported, vdevs present | ⬜ |
| 5 | `zpool clear lake` — reset counters, vdev back to ONLINE | ⬜ |
| 6 | `zpool scrub lake` — full read + raidz2 repair of anything corrupt on the WD (55.7T alloc; ≳1 day) | ⬜ |
| 7 | Verdict: scrub repairs a bounded set and pool **stays clean afterwards** → resilver-time corruption, drive provisionally reprieved (keep on short leash). New cksum errors during/after scrub → drive is actively corrupting; **replace it**. | ⬜ |

### Follow-ups

1. **If the drive is condemned**: it was an on-hand spare, not a fresh purchase —
   no RMA path. Source a replacement (ServerPartDeals recert has worked for the
   fleet) and **burn it in before trusting it**: full-surface write + read-back
   + long SMART self-test. This incident is the argument for that procedure.
2. **After the pool returns to ONLINE**: confirm the monthly cron scrub actually
   fires on the second Sunday (next: 2026-07-12). Consider alerting on
   "time since last scrub" — the existing `ZfsPoolNotOnline` alert can't catch
   a scrub that silently skips.
3. RAIDZ2 absorbed ~67 corrupt blocks without data loss — worth remembering
   *why* we pay for two parity drives when sizing future vdevs.
