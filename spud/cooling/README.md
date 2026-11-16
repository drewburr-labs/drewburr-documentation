# CPU boost and cooling (spud)

How `spud`'s CPU clocks and fans are configured, and why. Set up on 2026-10-28 through 2026-10-31.

## Hardware

| Part | Detail |
|---|---|
| CPU | AMD Ryzen 7 5800X3D (8C/16T) |
| Board | ASRock X570 Taichi, BIOS P5.60 |
| Super I/O | Nuvoton NCT6798D (`nct6775` driver) |
| Cooler | be quiet! Pure Loop 2 FX 360 mm AIO. No USB and no coolant temp sensor. |
| GPU | AMD Radeon RX 9070 |

### Fan headers

| Header (`nct6798`) | Connected | Notes |
|---|---|---|
| `fan2` / `pwm2` | 7 fans: 3 radiator, 1 rear exhaust, 3 bottom | One header drives every fan. Only one tach is reported. |
| `fan3` / `pwm3` | AIO pump only | Moved to its own header on 2026-10-31. Before that it had no tach and no control. |
| `fan1`, `fan4`–`fan7` | nothing | Read 0 RPM |

Seven fans on one header may exceed its current rating. This hasn't been checked against the fan labels or the board manual yet. If it's over, move the fans to a SATA-powered PWM hub.

## Files

These are copies of the live files on `spud`. The live files are the source of truth, so keep the two in sync.

| Repo file | Live path |
|---|---|
| `cpu-epp-performance.service` | `/etc/systemd/system/cpu-epp-performance.service` |
| `cpu-epp-performance-boost.conf` | `/etc/systemd/system/cpu-epp-performance.service.d/boost.conf` |
| `nct6775.conf` | `/etc/modules-load.d/nct6775.conf` |
| `coolercontrold-priority.conf` | `/etc/systemd/system/coolercontrold.service.d/priority.conf` |
| `coolercontrol-config.toml` | `/etc/coolercontrol/config.toml` |
| `calibrations.json` | `/etc/coolercontrol/calibrations.json`. Written by the daemon; don't hand-edit. |
| `overrides.toml` | `/etc/coolercontrol/overrides.toml`. Display labels such as "Pump (Fan3)". |
| `sudoers-coolercontrold` | `/etc/sudoers.d/coolercontrold` |

## CPU boost

### Background

On the default `amd-pstate-epp` driver, the 5800X3D sat at its 3.40 GHz base clock and never boosted. The earlier fix was the kernel option `amd_pstate=passive` plus `cpu-epp-performance.service`, which sets the `performance` governor at boot.

### 2026-10-28 regression

On kernel 7.2.11 the CPU was stuck at 3.4 GHz again, even with that fix in place:

- `cpufreq/boost` (global) was `1`, but every `cpufreq/policy*/boost` (per-policy) was `0`.
- So `cpuinfo_max_freq` and `scaling_max_freq` were `3401000`, even though `amd_pstate_max_freq` reported `4552952`.
- Writing `1` directly to `policy*/boost` is silently ignored: the write succeeds, but the value stays `0` and the kernel logs no error.
- Toggling the **global** switch from `0` to `1` resets every policy to `1`. All-core clocks under load went from 3375 MHz to about 4225 MHz.

`cpu-epp-performance-boost.conf` repeats that toggle at boot as an `ExecStartPost` on the existing unit.

### Expected behavior

| Load | Clock |
|---|---|
| 1–2 threads | about 4.45–4.55 GHz |
| All 16 threads | about 4.2 GHz, held steadily. This is normal all-core boost for the chip, not throttling. |

Check:

```sh
cat /sys/devices/system/cpu/cpufreq/policy*/boost | sort | uniq -c   # expect 16 1
cat /sys/devices/system/cpu/cpufreq/policy0/cpuinfo_max_freq          # expect 4552952
```

With boost on, full load runs about 73 °C (Tctl), compared with about 50 °C when capped. Throttling starts around 90 °C.

### Curve Optimizer undervolt

**Currently −15 (All Cores, Negative)**, set 2026-10-31. Path: Advanced → AMD Overclocking (some ASRock versions put it under OC Tweaker) → Precision Boost Overdrive: Advanced → Curve Optimizer → All Cores. PBO Limits and Scalar are left on Auto, since the X3D locks them.

60 s CoolerControl stress test, all 16 threads:

| | Before (no CO, mid-test) | −15 |
|---|---|---|
| All-core clock | about 4.1 GHz | about 4.25 GHz, held |
| Tctl | 88.4 °C | 90.4 °C, flat |

The 5800X3D boosts until it reaches its 90 °C limit and holds there, so the undervolt shows up as higher clocks, not lower temps. Fan speed (36% vs 100%) didn't change the peak in a 60 s burst. In short bursts the limit is how fast heat leaves the die through the X3D cache layer, not the radiator.

#### 10-minute sustained test (−15, 2026-10-31)

CoolerControl stress test, all 16 threads, 9.9 minutes of load, sampled every 2 s. Fan floor was 20% and inputs used the 20 s averages.

| Minute | Avg clock (MHz) | Slowest core (MHz) | Tctl (°C) | Fans | Pump |
|---|---|---|---|---|---|
| 0 | 4224–4275 | 4224 | 88.8–90.4 | ramping, 574 → 2106 RPM | ramping, 4515 → 5555 RPM |
| 1 | 4225–4250 | 4225 | 90.4 | 100%, about 2115 RPM | 100%, about 5450 RPM |
| 2 | 4200–4253 | 4200 | 90.4 | 100% | 100% |
| 3 | 4225–4259 | 4225 | 90.4 | 100% | 100% |
| 4 | 4225–4266 | 4225 | 90.4 | 100% | 100% |
| 5 | 4206–4250 | 4206 | 90.4 | 100% | 100% |
| 6 | 4220–4250 | 4219 | 90.4 | 100% | 100% |
| 7 | 4200–4275 | 4200 | 90.4 | 100% | 100% |
| 8 | 4224–4257 | 4224 | 90.2–90.4 | 100% | 100% |
| 9 | 4224–4268 | 4224 | 90.4 | 100% | 100% |

- **No throttling.** No core dropped below 4200 MHz at any point, and minute 9 matched minute 0. Clocks didn't decline as the coolant warmed, so the 360 mm AIO keeps up with full all-core heat output.
- **Temperature-limited, not throttling.** Tctl reached 90 °C about 4 s into the load and held at 90.2–90.4 °C without going over. The 90 °C limit sets the top clock but never forced it lower.
- **Ramp:** fans and pump started rising about 6 s in; the pump reached 100% at about 14 s and the fans at about 16 s. Fan RPM reached about 2100 by the end of minute 0, then both held steady.
- **Case:** GPU junction stayed at 52–53 °C (GPU idle), so there was no heat buildup in the case.
- **Cool-down:** Tctl went from 90 °C to 51 °C in 16 s. Fans and pump were back at idle (about 590 and 4500 RPM) within about 28 s.

Plan: run −15 for a few days, watching for random reboots at idle or light load. Then step −20 → −25 → −30, re-running the same test each time, and back off 5 after any crash. If it won't boot, use the Clear CMOS button on the rear I/O.

### Other options

- Linux undervolt tools for the 5800X3D need the out-of-tree `ryzen_smu` module, so BIOS is the preferred route. `pbo-tuner` is not a Fedora package.

## Fan sensors

`nct6775` isn't loaded by default, so `sensors` showed no motherboard fans. Load it now with `sudo modprobe nct6775`. `nct6775.conf` loads it at boot.

## Fan control: CoolerControl

### Why

Before CoolerControl, BIOS ran `pwm2` and `pwm3` from CPU temperature (`temp_sel=9`), so they reacted immediately. With boost on, light work spikes Tctl 10–20 °C for a moment, and the fans and pump surged at low load. An AIO has plenty of thermal mass, so neither needs to follow spikes. There's no coolant sensor to use as the source instead, so the curves read a 20-second rolling average of CPU and GPU temperature.

The first version (2026-10-31) used a 20 s response delay instead of an average. Under a sudden full load, that held the fans at 36% for about 20 s while the CPU sat at 90 °C, then jumped them straight to 100%. A rolling average starts ramping as soon as load is sustained, and short spikes barely move it. Measured in the same 60 s test: the pump starts rising at about 9 s and the fans at about 11 s, the fans step up to 100% by about 19 s, and both are back to idle about 20 s after the load ends (it was about 50 s with the delay).

### Install

CoolerControl 5.1.1 from the developer's COPR repo:

```sh
sudo dnf copr enable -y codifryed/CoolerControl
sudo dnf install -y coolercontrol coolercontrold
sudo systemctl enable --now coolercontrold
```

### Daemon priority

`coolercontrold-priority.conf` keeps fan control responsive while builds or tests are using every core:

| Setting | Value | Why |
|---|---|---|
| `CPUWeight` | 1000 | 10× a normal service's CPU share under contention |
| `IOWeight` | 1000 | Same priority for disk access |
| `Nice` | -10 | Wins over other processes in the same group |
| `OOMScoreAdjust` | -900 | Among the last processes the kernel kills when memory runs out |

Real-time scheduling was left out on purpose. The daemon polls about once a second, so a high weight is enough.

### Configuration

| Entity | Type | Settings |
|---|---|---|
| `sensor1` | Custom sensor, TimeAverage | 20 s rolling average of k10temp `temp1` (Tctl) |
| `sensor2` | Custom sensor, TimeAverage | 20 s rolling average of amdgpu `temp2` (junction) |
| `Smooth (averaged input)` | Function, Standard | deviance 1 °C, response delay 1 s, `only_downward = false`. Only filters jitter; the averaging does the smoothing. |
| `CPU curve` | Graph, `sensor1` | 30 °C → 20%, 65 °C → 25%, 75 °C → 60%, 85 °C → 100% |
| `GPU curve` | Graph, `sensor2` | 40 °C → 20%, 70 °C → 25%, 80 °C → 60%, 90 °C → 100% |
| `Case + radiator` | Mix, Max of CPU curve and GPU curve | Assigned to `fan2`. The case fans follow whichever part is hotter, so GPU-heavy games still ramp them. |
| `Pump curve` | Graph, `sensor1` | 20% up to 60 °C, then 100% at 80 °C. Assigned to `fan3`. |

The curves and the custom sensors use the `smooth` function. Custom sensors live on the "Custom Sensors" device (UID `19e098e3…`), and a Graph points at one with `temp_source = { temp_name = "sensor1", device_uid = "<Custom Sensors uid>" }`. In `config.toml` they're `[[custom_sensors]]` entries, each with `[[custom_sensors.sources]]` (`weight`, `temp_source`). The window must be 1–300 s.

At idle (CPU about 42–45 °C) the 7 fans run about 570 RPM and the pump about 4500 RPM at 20%. The fan floor was lowered from 30% to 20% on 2026-10-31; idle had been about 740 RPM. With calibration loaded, the PWM actually written (about 27% at idle) is a little higher than the curve's value, because CoolerControl maps curve percentages through the calibration.

### Pump PWM response

The Pure Loop 2 FX pump barely responds to PWM and enforces its own minimum speed. Each step below was held about 15 s at idle on 2026-10-31:

| PWM | RPM |
|---|---|
| 100% | 5509 |
| 90% | 5371 |
| 80% | 5308 |
| 70% | 5219 |
| 60% | 5129 |
| 50% | 4963 |
| 40% | 4838 |
| 30% | 4663 |
| 20% | 4545 |

So a low floor is safe, because flow stays high, but even the full range only lowers the pump about 18%.

### Calibration

CoolerControl calibration was run for both headers on 2026-10-31. It took about 5.5 minutes for `fan2` and about 4 minutes for `fan3`. The results are in `calibrations.json`.

| | `fan2` (7 fans) | `fan3` (pump) |
|---|---|---|
| Max RPM | 1997 | 5532 |
| RPM at 0% duty | about 265. The fans never stop. | about 4300 |
| Lowest stable duty | 6% | 0% |
| Highest useful duty | 100% | 80%. Nothing above that adds speed. |
| Curve kind | Smooth | Stepped |
| Warnings | none | "limited RPM range (1219 RPM); mapping resolution is coarse". This is expected, matching the pump test above. |

Selected `fan2` points (rising duty): 10% → 266, 20% → 378, 30% → 592, 40% → 790, 50% → 1026, 60% → 1201, 70% → 1386, 80% → 1527, 90% → 1687, 100% → 1875 RPM.

Implications:

- The fans can't stop (about 265 RPM at 0%), so a low floor is safe. The floor is now 20%, which gives about 570 RPM at idle through the calibration mapping.
- The pump curve's 100% top behaves the same as 80%.

## Editing the CoolerControl config

`/etc/coolercontrol/config.toml` can be edited by hand (by a person or an agent) without a password:

- `drewburr` has an ACL granting `rw` on that **one file**, not the folder: `/etc/coolercontrol/` also holds `.passwd`, `.tokens` and the TLS key.

  ```sh
  sudo setfacl -m u:drewburr:rw /etc/coolercontrol/config.toml
  ```

- `sudoers-coolercontrold` allows passwordless `systemctl stop|start|restart coolercontrold`, and nothing else. Install it with `visudo` so a syntax error can't break `sudo`:

  ```sh
  sudo env EDITOR=tee visudo -f /etc/sudoers.d/coolercontrold < sudoers-coolercontrold
  ```

Workflow. The daemon reads the config only at startup and may rewrite it while running, so stop it first:

```sh
cp /etc/coolercontrol/config.toml ~/.local/share/coolercontrol-backups/config.toml.$(date +%F-%H%M%S)
sudo systemctl stop coolercontrold
# edit /etc/coolercontrol/config.toml
sudo systemctl start coolercontrold
journalctl -u coolercontrold --since -1min | grep 'Successfully applied'
```

Schema reference: `coolercontrold/daemon/src/setting.rs` in [gitlab.com/coolercontrol/coolercontrol](https://gitlab.com/coolercontrol/coolercontrol) (`Profile`, `ProfileKind`, `Function`, `FunctionKind`). Device settings take the form `[device-settings.<device uid>]` with `<channel> = { profile_uid = "..." }` or `{ speed_fixed = N }`.

Backups are in `~/.local/share/coolercontrol-backups/`. The oldest one, `config.toml.2026-10-31-114838`, is the original config from before any profiles were added.

## Open items

- Confirm −15 Curve Optimizer is stable over a few days of normal use, then try −20.
- Check the current draw of the 7 fans on `fan2` against the header rating.
- `power-profiles-daemon` reported `power-saver` as active on 2026-10-31. Check whether that's intended on this desktop.
- Right after the 2026-10-31 restart, the pump and fans briefly rose (49% and 40%) at a 47 °C Tctl, then settled. The cause wasn't confirmed.
