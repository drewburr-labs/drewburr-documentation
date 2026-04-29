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
| Cooling | Custom open-loop watercooling (CPU + both GPUs) |
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
