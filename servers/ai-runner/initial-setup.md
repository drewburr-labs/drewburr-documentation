# Initial Setup

Steps to complete before running AI workloads.

> **Note:** All commands must be run on the `ai-runner` machine. SSH in first:
> ```sh
> ssh airunner01.drewburr.com
> ```

## 1. Expand Root Partition

The LVM volume group has ~1.8TB unallocated. The root LV needs to be expanded before installing large software stacks and model weights.

```sh
# Check current state
sudo vgs
sudo lvs

# Extend root LV, leaving ~200GB free in the VG as emergency reserve
sudo lvextend -L +1600G /dev/fedora/root

# Grow the filesystem to match
sudo xfs_growfs /

# Verify
df -h /
```

## 2. Install CUDA Toolkit

The NVIDIA driver (580.126.18) is installed, but the full CUDA toolkit is needed for compiling and running CUDA-based software.

The NVIDIA CUDA repo is not enabled by default on Fedora — add it first:

```sh
# Add the NVIDIA CUDA repo (use the closest available Fedora version)
sudo curl -o /etc/yum.repos.d/cuda-fedora41.repo \
  https://developer.download.nvidia.com/compute/cuda/repos/fedora41/x86_64/cuda-fedora41.repo

sudo dnf install -y cuda-toolkit

# Add CUDA binaries to PATH if not already present
echo 'export PATH=/usr/local/cuda/bin:$PATH' >> ~/.bashrc
echo 'export LD_LIBRARY_PATH=/usr/local/cuda/lib64:$LD_LIBRARY_PATH' >> ~/.bashrc
source ~/.bashrc

# Verify the install
nvcc --version
```
