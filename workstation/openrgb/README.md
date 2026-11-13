# OpenRGB lighting (workstation)

The Fedora workstation's RGB lighting is set to a dark purple theme at login by a user-level systemd unit. Nothing else (no OpenRGB server, no GUI autostart) manages lighting; the OpenRGB GUI is only used for exploring devices and picking colors.

## Files

- `openrgb-apply.service` – copy of `~/.config/systemd/user/openrgb-apply.service`. This is the source of truth; keep the two in sync.

## Devices

| Index | Device | Selected by | Color |
|---|---|---|---|
| 0 | ENE DRAM (DIMM) | index `0` | `0A0010` |
| 1 | ENE DRAM (DIMM) | index `1` | `0A0010` |
| 2 | ASRock X570 Taichi | name `"X570 Taichi"` | 24-entry per-LED list (see unit) |
| 3 | HyperX QuadCast 2 S | not set | only supports `Direct`; skipped |
| 4 | Cooler Master MM711 mouse | name `"MM711"` | `500080` |

The Taichi list is ordered by LED: RGB header 1, RGB header 2, Audio, PCH 1–10, IO Cover 1–10, Addressable header. Purple is `500080`/`180080`, teal is `005080`.

## Why the unit is written the way it is

- **USB devices are matched by name, not index.** OpenRGB numbers devices in detection order. i2c devices (the DIMMs and the motherboard) always enumerate first, but USB devices come and go. On 2026-09-19 the mic was not present at boot, the mouse shifted from index 4 to 3, and the old single-command unit failed with `Error: Empty device ID` before applying anything, leaving the RAM on its default rainbow.
- **DIMMs stay on indices 0 and 1.** Both report the same name (`ENE DRAM`), so name matching can't distinguish them. Their indices are stable because i2c detection precedes USB, as long as OpenRGB can open the i2c buses at all.
- **`ExecStartPre` waits for `/dev/i2c-*` to become writable.** The buses are `root:root 0660`; the user gets access only through logind's `uaccess` ACL, applied when the seat session starts. On 2026-11-06 the unit started at 20:04:03.0 and the ACL landed at 20:04:03.237, so OpenRGB saw no i2c devices, the mic and mouse became indices 0 and 1, and the DIMM line failed with `Mode 'static' not available for device 'HyperX QuadCast 2 S'`. The RAM stayed rainbow. The wait has no `-` prefix, so if the ACL never arrives the unit fails instead of reporting success.
- **One `ExecStart` per device, each prefixed with `-`.** A missing or misbehaving device no longer blocks the others.
- **`--noautoconnect`** skips the attempt to reach a local OpenRGB server, which was only producing a spurious "Connection attempt failed" line.

## Operating

```sh
# apply now / after editing the unit
systemctl --user daemon-reload
systemctl --user restart openrgb-apply.service
systemctl --user status openrgb-apply.service

# inspect devices, indices, and current modes
openrgb --noautoconnect --list-devices
```

## Gotchas

- **Do not test the motherboard with a single color.** Running `openrgb -d "X570 Taichi" -m static -c <one color>` replaces the per-LED layout, and the Polychrome controller renders that single value differently (the logo turned teal). Always pass the full 24-entry list, or just restart the unit.
- **The Taichi always reports mode `[Off]`** in `--list-devices`, regardless of what was applied. That is a read-back quirk of the Polychrome v2 controller, not a failure.
- **`[i2c_smbus_linux] Failed to read i2c device PCI device ID`** warnings are noise from the AMDGPU aux i2c buses and can be ignored.
- **The unit reports success even when a device line fails**, because of the `-` prefixes. Check `journalctl --user -u openrgb-apply.service -b`, not `systemctl status`. On 2026-10-24 the live unit was edited to address four DIMMs; spud has two, so `-d 2`/`-d 3` hit other devices and the RAM went rainbow until the repo copy was restored on 2026-11-01. Diff the live unit against this copy first.
- The unit has only run correctly since 2026-09-19; before that, every run since 2026-09-01 logged an error about the mic not supporting `static`, which the old combined command tolerated but which masked the index-shift failure mode.
