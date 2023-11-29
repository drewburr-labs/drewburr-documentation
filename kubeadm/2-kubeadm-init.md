# Kubeadm Init

[Creating a cluster with kubeadm](https://kubernetes.io/docs/setup/production-environment/tools/kubeadm/create-cluster-kubeadm/)

## Network setup

```shell
$ ip route show # Look for a line starting with "default via"
default via 10.128.0.1 dev ens4 proto dhcp src 10.128.0.3 metric 100
```

No custom configuration required

## Preparing the required container images

No special steps required.

## Initializing your control-plane node

1. No HA is expected for this POC, therefore, `--control-plane-endpoint` will not be set.
2. For CNI, Cilium was chosen becuase it's the one I'm most interested in. `--skip-phases=addon/kube-proxy` to be passed to `kubeadm` to use Cilium instead.
3. None required. Should auto-detect containerd

Initialize the cluster using Kubeadm

```shell
kubeadm init --skip-phases=addon/kube-proxy
```

## Troubleshooting kubeadm init

```shell
# kubeadm init --skip-phases=addon/kube-proxy
[init] Using Kubernetes version: v1.28.4
[preflight] Running pre-flight checks
error execution phase preflight: [preflight] Some fatal errors occurred:
    [ERROR FileExisting-conntrack]: conntrack not found in system path
    [ERROR FileContent--proc-sys-net-bridge-bridge-nf-call-iptables]: /proc/sys/net/bridge/bridge-nf-call-iptables does not exist
    [ERROR FileContent--proc-sys-net-ipv4-ip_forward]: /proc/sys/net/ipv4/ip_forward contents are not set to 1
[preflight] If you know what you are doing, you can make a check non-fatal with `--ignore-preflight-errors=...`
To see the stack trace of this error execute with --v=5 or higher
```

Findings when troubleshooting these errors:

- \[preflight] Running pre-flight checks
  - Appears to be ignorable via [kubernetes/kubernetes#89628](https://github.com/kubernetes/kubernetes/issues/89628#issuecomment-662631123)
  - Adding flag `--ignore-preflight-errors=FileExisting-conntrack`
- [ERROR FileContent--proc-sys-net-bridge-bridge-nf-call-iptables]: /proc/sys/net/bridge/bridge-nf-call-iptables does not exist
  - [kubernetes/kubeadm#1062](https://github.com/kubernetes/kubeadm/issues/1062) describes this is an undocumented, manual step
  - `modprobe br_netfilter`
- [ERROR FileContent--proc-sys-net-ipv4-ip_forward]: /proc/sys/net/ipv4/ip_forward contents are not set to 1
  - Same notes as above
  - `echo '1' > /proc/sys/net/ipv4/ip_forward`

Later findings:

- Fedora Coreos is R/O at `/usr/libexec/`
  - Define files as described in [ubernetes/kubeadm#2031](https://github.com/kubernetes/kubeadm/issues/2031#issuecomment-586742198)
  - v1beta2 has been replcaed by [v1beta3](https://pkg.go.dev/k8s.io/kubernetes/cmd/kubeadm/app/apis/kubeadm/v1beta3)

Defining configuration files:

```shell
echo '---
apiVersion: kubeadm.k8s.io/v1beta3
kind: ClusterConfiguration
controllerManager:
  extraArgs:
    flex-volume-plugin-dir: "/opt/libexec/kubernetes/kubelet-plugins/volume/exec/"
---
apiVersion: kubeadm.k8s.io/v1beta3
kind: InitConfiguration
nodeRegistration:
  kubeletExtraArgs:
    volume-plugin-dir: "/opt/libexec/kubernetes/kubelet-plugins/volume/exec/"' > init-configuration.yaml
```

Re-running initialization script

```shell
# kubeadm init --skip-phases=addon/kube-proxy --ignore-preflight-errors=FileExisting-conntrack --config init-configuration.yaml
[init] Using Kubernetes version: v1.28.4
[preflight] Running pre-flight checks
    [WARNING FileExisting-conntrack]: conntrack not found in system path
[preflight] Pulling images required for setting up a Kubernetes cluster
[preflight] This might take a minute or two, depending on the speed of your internet connection
[preflight] You can also perform this action in beforehand using 'kubeadm config images pull'
W1124 21:03:52.593817    7880 checks.go:835] detected that the sandbox image "registry.k8s.io/pause:3.6" of the container runtime is inconsistent with that used by kubeadm. It is recommended that using "registry.k8s.io/pause:3.9" as the CRI sandbox image.
[certs] Using certificateDir folder "/etc/kubernetes/pki"
[certs] Generating "ca" certificate and key
[certs] Generating "apiserver" certificate and key
[certs] apiserver serving cert is signed for DNS names [instance-1.us-central1-a.c.dulcet-bliss-374214.internal kubernetes kubernetes.default kubernetes.default.svc kubernetes.default.svc.cluster.local] and IPs [10.96.0.1 10.128.0.3]
[certs] Generating "apiserver-kubelet-client" certificate and key
[certs] Generating "front-proxy-ca" certificate and key
[certs] Generating "front-proxy-client" certificate and key
[certs] Generating "etcd/ca" certificate and key
[certs] Generating "etcd/server" certificate and key
[certs] etcd/server serving cert is signed for DNS names [instance-1.us-central1-a.c.dulcet-bliss-374214.internal localhost] and IPs [10.128.0.3 127.0.0.1 ::1]
[certs] Generating "etcd/peer" certificate and key
[certs] etcd/peer serving cert is signed for DNS names [instance-1.us-central1-a.c.dulcet-bliss-374214.internal localhost] and IPs [10.128.0.3 127.0.0.1 ::1]
[certs] Generating "etcd/healthcheck-client" certificate and key
[certs] Generating "apiserver-etcd-client" certificate and key
[certs] Generating "sa" key and public key
[kubeconfig] Using kubeconfig folder "/etc/kubernetes"
[kubeconfig] Writing "admin.conf" kubeconfig file
[kubeconfig] Writing "kubelet.conf" kubeconfig file
[kubeconfig] Writing "controller-manager.conf" kubeconfig file
[kubeconfig] Writing "scheduler.conf" kubeconfig file
[etcd] Creating static Pod manifest for local etcd in "/etc/kubernetes/manifests"
[control-plane] Using manifest folder "/etc/kubernetes/manifests"
[control-plane] Creating static Pod manifest for "kube-apiserver"
[control-plane] Creating static Pod manifest for "kube-controller-manager"
[control-plane] Creating static Pod manifest for "kube-scheduler"
[kubelet-start] Writing kubelet environment file with flags to file "/var/lib/kubelet/kubeadm-flags.env"
[kubelet-start] Writing kubelet configuration to file "/var/lib/kubelet/config.yaml"
[kubelet-start] Starting the kubelet
[wait-control-plane] Waiting for the kubelet to boot up the control plane as static Pods from directory "/etc/kubernetes/manifests". This can take up to 4m0s
[apiclient] All control plane components are healthy after 6.002979 seconds
[upload-config] Storing the configuration used in ConfigMap "kubeadm-config" in the "kube-system" Namespace
[kubelet] Creating a ConfigMap "kubelet-config" in namespace kube-system with the configuration for the kubelets in the cluster
[upload-certs] Skipping phase. Please see --upload-certs
[mark-control-plane] Marking the node instance-1.us-central1-a.c.dulcet-bliss-374214.internal as control-plane by adding the labels: [node-role.kubernetes.io/control-plane node.kubernetes.io/exclude-from-external-load-balancers]
[mark-control-plane] Marking the node instance-1.us-central1-a.c.dulcet-bliss-374214.internal as control-plane by adding the taints [node-role.kubernetes.io/control-plane:NoSchedule]
[bootstrap-token] Using token: ppeu2b.63es7gc80bxk9rvk
[bootstrap-token] Configuring bootstrap tokens, cluster-info ConfigMap, RBAC Roles
[bootstrap-token] Configured RBAC rules to allow Node Bootstrap tokens to get nodes
[bootstrap-token] Configured RBAC rules to allow Node Bootstrap tokens to post CSRs in order for nodes to get long term certificate credentials
[bootstrap-token] Configured RBAC rules to allow the csrapprover controller automatically approve CSRs from a Node Bootstrap Token
[bootstrap-token] Configured RBAC rules to allow certificate rotation for all node client certificates in the cluster
[bootstrap-token] Creating the "cluster-info" ConfigMap in the "kube-public" namespace
[kubelet-finalize] Updating "/etc/kubernetes/kubelet.conf" to point to a rotatable kubelet client certificate and key
[addons] Applied essential addon: CoreDNS

Your Kubernetes control-plane has initialized successfully!

To start using your cluster, you need to run the following as a regular user:

  mkdir -p $HOME/.kube
  sudo cp -i /etc/kubernetes/admin.conf $HOME/.kube/config
  sudo chown $(id -u):$(id -g) $HOME/.kube/config

Alternatively, if you are the root user, you can run:

  export KUBECONFIG=/etc/kubernetes/admin.conf

You should now deploy a pod network to the cluster.
Run "kubectl apply -f [podnetwork].yaml" with one of the options listed at:
  https://kubernetes.io/docs/concepts/cluster-administration/addons/

Then you can join any number of worker nodes by running the following on each as root:

kubeadm join 10.128.0.3:6443 --token abcdefghijklmnopqrstuvw \
    --discovery-token-ca-cert-hash sha256:ABCDEF1234567890ABCDEF1234567890ABCDEF1234567890ABCDEF1234567890
```

Setting up kube config using `core` user:

```shell
mkdir -p $HOME/.kube
sudo cp -i /etc/kubernetes/admin.conf $HOME/.kube/config
sudo chown $(id -u):$(id -g) $HOME/.kube/config
```
