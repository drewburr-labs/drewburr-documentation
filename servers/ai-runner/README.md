# AI Runner - airunner01.drewburr.com

A dedicated bare metal AI/ML workstation with dual RTX 3090 GPUs, intended for local model inference and training workloads.

## Hardware

| Component | Details |
|-----------|---------|
| Motherboard | Gigabyte X99-UD5 WIFI-CF |
| CPU | Intel Xeon E5-2687W v3 @ 3.10GHz (10 cores / 20 threads, 3.5GHz turbo) |
| RAM | 128GB DDR4 (8x16GB W642GU42J7240N8, slots A1/A2/B1/B2/C1/C2/D1/D2) |
| GPU | 2x NVIDIA GeForce RTX 3090 (24GB VRAM each, 48GB total) |
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

The NVMe drive has 1.8TB of unallocated LVM space. Only 15GB is currently assigned to the root volume.

```text
nvme0n1 (2TB)
├─ nvme0n1p1   600MB   /boot/efi
├─ nvme0n1p2   2GB     /boot
└─ nvme0n1p3   1.8TB   LVM PV
   └─ fedora-root  15GB  /    ← only 15GB allocated, ~1.8TB free in VG
```

To expand or create new LVs from the free space:

```sh
# Check free space in the volume group
sudo vgs

# Extend the root logical volume (example: add 200GB)
sudo lvextend -L +200G /dev/mapper/fedora-root
sudo xfs_growfs /
```

## GPU Status

Both RTX 3090s are running on the proprietary NVIDIA driver (580.126.18) with CUDA 13.0 support. See [nvidia-driver-setup.md](./nvidia-driver-setup.md) for setup notes.

## Strengths

- **48GB combined VRAM** — can run large LLMs (70B+ models with quantization) or split workloads across both GPUs
- **128GB system RAM** — plenty of headroom for CPU offloading and large datasets
- **2TB NVMe** — fast local storage for model weights with ~1.8TB unallocated
- **20 CPU threads** — solid preprocessing and data pipeline throughput

## Limitations

- **1GbE networking** — may bottleneck high-throughput data transfers
- **Older platform** — X99/LGA2011-v3 (2014 era); limited PCIe bandwidth compared to modern platforms (both GPUs share PCIe 3.0 lanes)
- **15GB root partition** — needs expansion before installing heavy software stacks (CUDA toolkits, model weights)
