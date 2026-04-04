# NVIDIA Driver Setup

The RTX 3090s are currently running on the nouveau driver. This page covers switching to the proprietary NVIDIA driver and installing CUDA.

## Disable Nouveau

Nouveau must be blacklisted before installing the NVIDIA driver.

```sh
sudo bash -c 'echo "blacklist nouveau" > /etc/modprobe.d/blacklist-nouveau.conf'
sudo bash -c 'echo "options nouveau modeset=0" >> /etc/modprobe.d/blacklist-nouveau.conf'
sudo dracut --force
sudo reboot
```

After reboot, verify nouveau is no longer loaded:

```sh
lsmod | grep nouveau  # should return nothing
```

## Install NVIDIA Driver (via RPM Fusion)

```sh
# Enable RPM Fusion repos
sudo dnf install -y \
  https://download1.rpmfusion.org/free/fedora/rpmfusion-free-release-$(rpm -E %fedora).noarch.rpm \
  https://download1.rpmfusion.org/nonfree/fedora/rpmfusion-nonfree-release-$(rpm -E %fedora).noarch.rpm

# Install NVIDIA driver and CUDA
sudo dnf install -y akmod-nvidia xorg-x11-drv-nvidia-cuda

# Wait for the kernel module to build (can take a few minutes)
sudo akmods --force

sudo reboot
```

After reboot, verify the driver is loaded:

```sh
nvidia-smi
```

Expected output should show both GPUs listed with their 24GB VRAM.

## Install CUDA Toolkit (optional, for development)

```sh
sudo dnf install -y cuda
```
