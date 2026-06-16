# storage01 — lake DEGRADED: HGST 12TB Drive Failure & Replacement

## 2026-06-15 — Ultrastar 8DGT7DMH dead, replaced with WD 14TB

### Summary

A 12TB HGST drive (`8DGT7DMH`, Ultrastar DC HC520, model `HUH721212ALE601`) in
the `lake` raidz2-0 vdev dropped out of the array and went `REMOVED`, leaving the
pool `DEGRADED`. It had been degraded for **~4 weeks** before being noticed
(there was no pool-health alert until 2026-06-16 — see Follow-ups). The drive was
diagnosed as **dead** and replaced with a 14TB WD (`9RG9UZEC`); the pool is
resilvering.

`lake` is raidz2 (tolerates 2 failures); with one drive gone it was down to a
single parity drive — functional but one failure away from data loss on ~65T.

### Timeline

| Date | Event |
|---|---|
| ~2026-05-19 | `8DGT7DMH` drops off the HBA (coincides with the storage01 reboot at 02:01; same maintenance window as the nvmetcli `prefs.bin` corruption). Pool goes DEGRADED. |
| 2026-06-15 | Noticed during broader sas-pool remediation work. Diagnosed as a dead drive. |
| 2026-06-15 | Replaced with WD 14TB `9RG9UZEC`; resilver started (ETA ~1 day). |
| 2026-06-16 | Added `ZfsPoolNotOnline` Grafana alert so this can't go unnoticed again. |

### Diagnosis

`lake` config — raidz2-0, 6 drives. The dead one:

```
replacing-0                           DEGRADED
  scsi-SATA_HUH721212ALE601_8DGT7DMH  REMOVED       <- dead
  scsi-SATA_WDC_WUH721414AL_9RG9UZEC  ONLINE        <- replacement, resilvering
```

**Key facts establishing it was the disk, not the host/config:**

- **storage01 is a VM.** The disks hang off an **LSI SAS3224 HBA that is
  PCIe-passed-through** to the storage01 VM (`mpt3sas`). So the disks are NOT
  visible on the Proxmox host (`pve05`) — checking the hypervisor showed zero
  HGST drives, which is expected for HBA passthrough, not a sign of failure.
- The drive was **absent from the OS entirely** — no `/dev/disk/by-id` node — and
  did not return after a SCSI rescan (both inside the VM and at the HBA level).
- SAS topology (sysfs): `phy-4:21` showed **`Unknown` link rate with bay 21
  empty** and `invalid_dword_count=0`, `phy_reset_problem_count=0`. Zero errors +
  no link = the drive fell completely off the expander rather than failing with
  errors. `8DGT7DMH` is a SATA drive tunneled through the SAS expander (STP);
  SATA-behind-SAS-expander affiliation drops are a known mode and *sometimes*
  recover on reseat — so that was tested next.
- **Definitive test:** the drive was moved to a known-good **powered 6-bay USB
  dock**. It would not spin up or enumerate. A *different* 3.5" drive in the same
  dock enumerated instantly — proving dock/power/bridge were fine. The drive is
  **dead** (no spin / no response to IDENTIFY), not a power or affiliation issue.

### Resolution

Replaced with a spare WD 14TB (`WDC WUH721414ALE604`, serial `9RG9UZEC`).

> **Gotcha:** the "spare" was NOT blank — `zpool replace` refused it because
> partition 1 held a **FAULTED ZFS pool named `backup`** with
> `hostname: 'raspberrypi'` (an old syncoid backup target — ties to the
> `syncoid_raspberrypi` snapshots seen on the nvmeof dataset). `zdb -l` on the
> *whole disk* had shown no label because the label lives on the *partition*;
> `zpool replace` checks partitions and caught it. Confirmed expendable with the
> operator, then wiped (`zpool labelclear -f …-part1`, `sgdisk --zap-all`,
> `wipefs -a`) before replacing. **Lesson: check `zpool import` / partition
> labels, not just whole-disk `zdb -l`, before reusing a drive.**

```sh
sudo zpool replace lake scsi-SATA_HUH721212ALE601_8DGT7DMH \
  /dev/disk/by-id/scsi-SATA_WDC_WUH721414AL_9RG9UZEC
```

The new drive is 14TB but the vdev uses only ~12TB (raidz2 sizes to the smallest
member); the extra ~2TB is unused until every member is ≥14TB. Pool stays
DEGRADED until the resilver completes (~1 day at 86% full), then returns to
ONLINE and the `ZfsPoolNotOnline` alert self-clears.

### Drive health snapshot (2026-06-15, SMART, no self-tests)

All 25 physical drives pass SMART. Notable points:

| group | drives | health | notes |
|---|---|---|---|
| sas-pool (NetApp X438, SAS 12TB) | 20× | OK | grown-defect-list 0 on all **except `sdg`** |
| lake (HGST `ALE601` SATA) | sdv/sdy/sdz | PASSED | realloc/pending/offline-unc/CRC all 0 |
| lake (HGST `AL4205` SAS) | sdw/sdx | OK | 0 defects |
| lake replacement (WD 14TB) | sdaa `9RG9UZEC` | PASSED | new, all 0 |

**Watch item — `sdg` (NetApp `S182NEAG610044`, sas-pool):**
- 3 elements in grown defect list (only drive on the system with any).
- BUT **0 uncorrected errors**, 0 ECC corrections across 169 TB read / 186 TB
  written; 42°C; **37,768 power-on hours (~4.3 yr)**. The 3 sectors were remapped
  cleanly long ago and it's been stable since — healthy, not failing. It's simply
  the natural next-to-watch: if that defect count climbs, plan its replacement.

These are recertified used enterprise drives (~4+ years power-on), so a low,
stable grown-defect count is expected and not alarming.

### Follow-ups

1. **RMA the dead `8DGT7DMH`** — purchased from ServerPartDeals.com on
   2024-12-05. Recertified drives carry a multi-year warranty, so at ~18 months
   it is very likely still covered (a warranty RMA — no restocking fee — not a
   30-day return). Need the order number (proof of purchase) + serial `8DGT7DMH`
   + the defect description above. Confirm the warranty end date with the vendor.
2. **Let the resilver finish** before any storage01 reboot/maintenance — you are
   on the last parity drive until it completes.
3. **`sdg`** — watch the grown-defect count over the coming weeks.
4. The **2026-05-19 reboot** keeps recurring across incidents (this drive drop,
   the nvmetcli corruption, the OOM window). Worth understanding what happened in
   that maintenance before the next storage01 reboot.
