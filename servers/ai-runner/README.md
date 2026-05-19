# AI Runner - airunner01.drewburr.com

A dedicated bare metal AI/ML workstation with dual RTX 3090 GPUs, intended for local model inference and training workloads.

## Hardware

| Component | Details |
|-----------|---------|
| Motherboard | Gigabyte X99-UD5 WIFI-CF |
| CPU | Intel Xeon E5-2687W v3 @ 3.10GHz (10 cores / 20 threads, 3.5GHz turbo) |
| RAM | 128GB DDR4 (8x16GB W642GU42J7240N8, slots A1/A2/B1/B2/C1/C2/D1/D2) |
| GPU | 2x NVIDIA GeForce RTX 3090 (24GB VRAM each, 48GB total) |
| GPU Interconnect | NVLink bridge (4 links @ 14.062 GB/s each, ~112 GB/s aggregate bidirectional) |
| Cooling | Custom open-loop watercooling (see [Watercooling Loop](#watercooling-loop)) |
| Storage | 2TB NVMe SSD (Crucial CT2000P5PSSD8) |
| Network | 1GbE (enp6s0) at 192.168.4.56/23 |

### PCIe Slot Layout (top to bottom)

| Position | Slot   | Physical Size | Electrical Speed | Notes                            |
| -------- | ------ | ------------- | ---------------- | -------------------------------- |
| 1st      | PCIE_5 | x1            | x1               |                                  |
| 2nd      | PCIE_1 | x16           | x16              | GPU 1                            |
| 3rd      | PCIE_4 | x16           | x8               | Shares bandwidth with PCIE_1     |
| 4th      | PCIE_6 | x1            | x1               |                                  |
| 5th      | PCIE_2 | x16           | x16              | GPU 2                            |
| 6th      | PCIE_7 | x1            | x1               |                                  |
| 7th      | PCIE_3 | x16           | x8               | Best slot for a third PCIe device |

> PCIE_1 and PCIE_2 run at x16/x16 with the Xeon E5-2687W v3 (40 PCIe lanes). Populating PCIE_4 drops PCIE_1 to x8.

#### GPU UUID Assignments

| Slot   | PCI Bus     | nvidia-smi index | GPU UUID                                       |
| ------ | ----------- | ---------------- | ---------------------------------------------- |
| PCIE_1 | 0000:02:00.0 | 0                | `GPU-ad10d3f1-0772-e0c4-a110-f609437e435b`     |
| PCIE_2 | 0000:03:00.0 | 1                | `GPU-a00e528f-9606-f0aa-b8b5-274c47ad1502`     |

> The two cards were swapped between PCIE_1 and PCIE_2 to test whether the open-loop watercooling thermal asymmetry follows the slot/loop position or the card itself. Verify with `nvidia-smi --query-gpu=index,uuid,pci.bus_id --format=csv`.

### Watercooling Loop

Open loop, soft tubing throughout (13/19mm ID/OD).

Flow path:

```
D5 pump
  → 360mm radiator (vertically mounted)
  → 360mm radiator (top mounted)
  → GPU 1 ∥ GPU 2  (parallel, via fixed waterblock bridge — split is non-configurable)
  → D5 pump
```

Pump: **EK-Quantum Kinetic FLT 120 D5 PWM D-RGB**. Powered via SATA from the PSU; the 4-pin cable to the motherboard carries only PWM signal in, tach out, and GND.

Notes:
- The two GPU blocks are joined by a fixed bridge that splits coolant in parallel, so both blocks see the same inlet temperature. Asymmetric die temps in this topology indicate asymmetric **flow** between the two blocks (e.g., trapped air, restriction, or contact issue), not loop ordering.
- Total radiator area is 720mm of 360mm-class rad before the GPUs, which is comfortable for ~700W of GPU heat under reasonable fan curves.
- No coolant temperature sensor installed yet; planned (see `notes.txt` parts list — temp sensor, T fitting, ball valve for fill/drain).

#### Cold plate defect — resolved 2026-05-02

**Original issue (2026-05-01).** Under a 20-min sustained vLLM inference load (gemma4-31b, both GPUs at ~340W tensor-parallel), the GPUs throttled continuously due to **GPU die hot-spot temperatures sustained at 103-105°C**, while the core/edge temperature stayed at 69-70°C — a ~35°C core-to-hotspot delta on both GPUs (healthy spec is 10-15°C). Effects: `nvidia_smi_clocks_event_reasons_sw_thermal_slowdown` continuously active, power capped at 299-308W per GPU instead of the 420W limit, throughput throttled by ~23%.

**Root cause.** At least one cold plate had a visible manufacturing defect — a fingernail-catchable machining ridge running across the die contact surface, leaving an air gap (~50-100µm) that thermal paste cannot bridge.

**Resolution.** Both GPU waterblocks were disassembled, the cold plates were lapped flat (progressive 400-2500 grit silicon carbide on float glass, with a small abrasive block to work inside the recessed die zone surrounded by the taller VRAM contact pads). PTM7950 phase-change pad was used in place of paste on both die surfaces. VRAM/VRM thermal pads were also replaced with correct-thickness stock to maintain proper mounting pressure after the lap.

**Post-fix measurements** (same 20-min sustained load):

| Metric | Pre-fix | Post-fix |
| --- | --- | --- |
| Junction (GPU 0 / ad10) | 103-104°C | 90-91°C |
| Junction (GPU 1 / a00e) | 104-105°C | 57-58°C |
| Junction−core delta (GPU 0) | 35°C | 20°C |
| Junction−core delta (GPU 1) | 35°C | 10-11°C |
| Power per GPU | 299-308W (throttled) | 356-400W (unthrottled) |
| sw_thermal_slowdown | continuous | 0 |
| Throughput | ~380 tok/s | ~393 tok/s |

GPU 1 lands cleanly in healthy spec (10-11°C delta). GPU 0 is improved and unthrottled but its delta is still ~5°C above ideal — its lap or pad seating was less complete than GPU 1's, or its underlying defect was deeper. Functional but with less margin; reseating PTM7950 on GPU 0 (or another light lap pass) would close the gap if it ever comes out for other work. An interim `nvidia-smi -i 0 -pl 380` would provide a safety buffer on warmer days, costing ~3% throughput.

VRAM temps rose 6-8°C (70°C → 76-78°C) post-fix because the loop now actually receives the full ~140W of GPU heat that was previously being throttled away. Still well within GDDR6X safe range.

NVLink remained healthy across the disassembly — all 4 links per GPU at 14.062 GB/s, zero error counters under sustained tensor-parallel load.

#### Motherboard fan header status

Verified empirically on 2026-05-01 by swapping a known-good PWM fan and the EK pump between headers and watching the it8792 channel response in `/sys/class/hwmon/`:

| Motherboard header | it8792 channel | Tach | PWM control |
| ------------------ | -------------- | ---- | ----------- |
| SYS_FAN1           | fan1 / pwm1    | Working — accurate readback | Working — verified RPM tracked pwm sweep 559 → 747 → 1115 at duty 64 → 128 → 255 |
| SYS_FAN2           | fan2 / pwm2    | **Dead** — reads 0 RPM with a fan known to be physically spinning, and with a SATA-powered pump connected | Not separately confirmed (no tach feedback to test against) |
| SYS_FAN3           | fan3 / pwm3    | **Dead** — reads a phantom ~1467-1473 RPM regardless of what is connected (including nothing) | Not separately confirmed by audible test; software pwm sweeps cannot be evaluated because the tach is lying |

Tach lines on SYS_FAN2 and SYS_FAN3 are non-functional — confirmed by physical observation that connected fans spin at speeds the readback does not match. PWM control on those headers may or may not work; without tach feedback we can't verify it from software alone, and we did not run an audible-speed test.

Only SYS_FAN1 should be relied upon for any fan/pump that needs tach monitoring. The pump is currently driven by an external PWM controller rather than any motherboard header.

#### GPU-based fan control — gpu-fan-control.service

SYS_FAN1 (it8792 `pwm1`) is controlled by a systemd service that sets PWM based on the hottest GPU sensor reading. The service is enabled at boot.

**Temperature sources** (polled every 10 seconds, max taken across all values):
- `nvidia-smi` — instant GPU core temp for both cards
- `node_exporter` at `localhost:9100/metrics` — `nvidia_gddr6_core_temp_celsius`, `nvidia_gddr6_junction_temp_celsius`, `nvidia_gddr6_vram_temp_celsius` for both cards (up to ~10s lag, updated by `gpu-extra-temps.timer`)

Using both sources together means fast core-temp changes are caught immediately, while junction and VRAM temps (which run 10–15°C hotter than core at load) are covered with a short lag.

**Fan curve** (linear interpolation between points):

| Max temp | PWM duty | Fan speed |
| -------- | -------- | --------- |
| ≤ 40°C   | 64/255   | ~25%      |
| 50°C     | 128/255  | ~50%      |
| 60°C     | 191/255  | ~75%      |
| ≥ 70°C   | 255/255  | 100%      |

The it8792 hwmon path is resolved dynamically by name at startup, so the path is stable across reboots even if hwmon numbering shifts.

On service stop or crash, the `EXIT` trap releases `pwm1_enable` back to `0` (full speed / hardware default) as a failsafe.

Script: `/usr/local/bin/gpu-fan-control`

To inspect or adjust:

```sh
systemctl status gpu-fan-control
# Current PWM value (0-255):
cat /sys/class/hwmon/hwmon2/pwm1
# Current fan RPM:
cat /sys/class/hwmon/hwmon2/fan1_input
```

#### Fan header pin layout gotcha

The Gigabyte X99-UD5 WIFI manual (page 28 / `x99_manual.md`) claims a **non-standard pin layout** on its system fan headers, with pins 2 and 4 swapped relative to CPU_FAN:

| Pin | CPU_FAN | SYS_FAN1/2/3 and CPU_OPT (per manual) |
| --- | ------- | ------------------------------------- |
| 1   | GND     | GND                                   |
| 2   | +12V    | Speed Control (PWM)                   |
| 3   | Sense   | Sense                                 |
| 4   | Speed Control (PWM) | VCC (+12V)                |

Empirical testing on SYS_FAN1 (the working header) was consistent with the **standard** Intel layout (PWM on pin 4, +12V on pin 2), not the manual. The manual page may be incorrect for this board revision; treat with skepticism. Trust the multimeter, not the manual.

EK pump cable wiring note: this specific cable had wires populated only at connector positions 3 and 4, and **the PWM wire is on position 3, Tach on position 4** — reversed from standard convention. Verify with a multimeter (PWM pin reads ~5V steady from internal pull-up; Tach reads a low DC average from the running pulse train) before relying on assumed colors.

## Software

| Component | Details |
|-----------|---------|
| OS | Fedora Linux 43 (Server Edition) |
| Kernel | 6.19.10-200.fc43.x86_64 |
| GPU Driver | NVIDIA 580.126.18 (CUDA 13.0) |
| Web UI | Cockpit (port 9090) |

## Storage Layout

```text
nvme0n1 (1.8T)
├─ nvme0n1p1   600M   /boot/efi
├─ nvme0n1p2   2G     /boot
└─ nvme0n1p3   1.8T   LVM PV (VG: fedora)
   └─ fedora-root  1.6T  /    (~245G free in VG)
```

To extend root from the remaining VG free space:

```sh
sudo vgs
sudo lvextend -L +100G /dev/mapper/fedora-root
sudo xfs_growfs /
```

## GPU Status

Both RTX 3090s are running on the proprietary NVIDIA driver (580.126.18) with CUDA 13.0 support. See [nvidia-driver-setup.md](./nvidia-driver-setup.md) for setup notes.

The two cards are connected via an NVLink bridge. Verify with:

```sh
nvidia-smi nvlink --status   # 4 links @ 14.062 GB/s per GPU
nvidia-smi topo -m           # GPU0/GPU1 should show NV4
```

## Strengths

- **48GB combined VRAM** — can run large LLMs (70B+ models with quantization) or split workloads across both GPUs
- **NVLink between GPUs** — high-bandwidth peer-to-peer transfers for tensor/pipeline parallelism
- **128GB system RAM** — plenty of headroom for CPU offloading and large datasets
- **2TB NVMe** — fast local storage for model weights and datasets
- **20 CPU threads** — solid preprocessing and data pipeline throughput

## Limitations

- **1GbE networking** — may bottleneck high-throughput data transfers
- **Older platform** — X99/LGA2011-v3 (2014 era); PCIe 3.0 only
