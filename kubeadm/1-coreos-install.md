# CoreOS Install

Fedora CoreOS was chosen for its auto-update and restart-with-lockfile features. This is my first experience with CoreOS, however, I have experience with Fedora and RHEL, making this a comforatable personal choice.

## Provisioning

GCP-based provisioning [(docs)](https://docs.fedoraproject.org/en-US/fedora-coreos/provisioning-gcp/) was chosen for testing since I'm familiar with the UI and provisioning is natively supported.

For SSH access, `enable-oslogin: TRUE` metadata must be set, and SSH keys must be added before provisioning the VM. For simplicity, I added a SSH key for the `core` user.

## OS Setup

The following is my thoughts and research into OS configuration, based on the kubeadm installation documentation [(docs)](https://kubernetes.io/docs/setup/production-environment/tools/kubeadm/install-kubeadm/). Steps are specific to Kubernetes v1.28.

Cluster size: 1 node
VM sizing: n2d-standard-2 (2 vCPU w/ 8GB memory)

Ports are not considered because this is a one node cluster

CoreOS has swap disabled by default.

Containerd and podman are installed on CoreOS by default, but neither are enabled. Preference is to use containerd alone.

```shell
sudo systemctl enable --now containerd
```

## Installation

Includes a mix of instrcutions due to CoreOS missing package manager instructions

Allow containers to access the host filesystem (Red Hat-based)

```shell
# Set SELinux in permissive mode (effectively disabling it)
sudo setenforce 0
sudo sed -i 's/^SELINUX=enforcing$/SELINUX=permissive/' /etc/selinux/config
```

Remaining are instructions from "without a package manager"

Install CNI plugins (required for most pod network):

```shell
# https://github.com/containernetworking/plugins/releases
CNI_PLUGINS_VERSION="v1.3.0"
ARCH="amd64"
DEST="/opt/cni/bin"
sudo mkdir -p "$DEST"
curl -L "https://github.com/containernetworking/plugins/releases/download/${CNI_PLUGINS_VERSION}/cni-plugins-linux-${ARCH}-${CNI_PLUGINS_VERSION}.tgz" | sudo tar -C "$DEST" -xz
```

Define the directory to download command files:

> Note: The DOWNLOAD_DIR variable must be set to a writable directory. If you are running Flatcar Container Linux, set DOWNLOAD_DIR="/opt/bin".

```shell
DOWNLOAD_DIR="/usr/local/bin"
sudo mkdir -p "$DOWNLOAD_DIR"
```

Install crictl (required for kubeadm / Kubelet Container Runtime Interface (CRI)):

```shell
# https://github.com/kubernetes-sigs/cri-tools/releases
CRICTL_VERSION="v1.28.0"
ARCH="amd64"
curl -L "https://github.com/kubernetes-sigs/cri-tools/releases/download/${CRICTL_VERSION}/crictl-${CRICTL_VERSION}-linux-${ARCH}.tar.gz" | sudo tar -C $DOWNLOAD_DIR -xz
```

Install kubeadm, kubelet, kubectl and add a kubelet systemd service:

```shell
# https://kubernetes.io/releases/
RELEASE="v1.28.4"
ARCH="amd64"
cd $DOWNLOAD_DIR
sudo curl -L --remote-name-all https://dl.k8s.io/release/${RELEASE}/bin/linux/${ARCH}/{kubeadm,kubelet,kubectl}
sudo chmod +x {kubeadm,kubelet,kubectl}
```

```shell
# https://github.com/kubernetes/release/releases
RELEASE_VERSION="v0.16.4"
curl -sSL "https://raw.githubusercontent.com/kubernetes/release/${RELEASE_VERSION}/cmd/krel/templates/latest/kubelet/kubelet.service" | sed "s:/usr/bin:${DOWNLOAD_DIR}:g" | sudo tee /etc/systemd/system/kubelet.service
sudo mkdir -p /etc/systemd/system/kubelet.service.d
curl -sSL "https://raw.githubusercontent.com/kubernetes/release/${RELEASE_VERSION}/cmd/krel/templates/latest/kubeadm/10-kubeadm.conf" | sed "s:/usr/bin:${DOWNLOAD_DIR}:g" | sudo tee /etc/systemd/system/kubelet.service.d/10-kubeadm.conf
```

> Note: Please refer to the note in the [Before you begin](https://kubernetes.io/docs/setup/production-environment/tools/kubeadm/install-kubeadm/#before-you-begin) section for Linux distributions that do not include glibc by default.
> (CoreOS) Check if glibc is installed: `rpm -q glibc`

Install kubectl by following the instructions on Install Tools page.

Backfilled fixes:

```shell
# Enable ipv4-forwarding
sudo modprobe br_netfilter
sudo echo '1' > /proc/sys/net/ipv4/ip_forward

# Setting systemd cgroup, by applying default config and restarting
# https://github.com/kubernetes/kubernetes/issues/110177
sudo containerd config default > /etc/containerd/config.toml
sudo sed -i 's/SystemdCgroup = false/SystemdCgroup = true/' /etc/containerd/config.toml
sudo systemctl restart containerd
```

Enable and start kubelet:

```shell
systemctl enable --now kubelet
```
