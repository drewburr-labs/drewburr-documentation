# Flannel → Cilium Migration

**Cluster:** k3s.drewburr.com
**Date written:** 2026-04-12
**K3s version:** v1.35.2+k3s1
**Current CNI:** Flannel (VXLAN, VNI=1)
**Target CNI:** Cilium (VXLAN mode, replacing Flannel; Multus retained)

---

## Rebuild vs In-Place — Decision

**Recommendation: in-place migration.**

A cluster rebuild was considered but ruled out for this cluster. The decisive blocker is storage:

| Storage class | PVs | Reclaim policy |
|---------------|-----|----------------|
| `zfs-nvmeof`  | 64  | **Delete**     |
| `zfs-nfs`     | 3   | Retain         |
| `nfs-lake`    | 2   | Retain         |
| `local-path`  | 1   | Delete         |

The 64 `zfs-nvmeof` PVs carry the cluster's primary stateful data (databases, media, game servers). Because `democratic-csi` implements the `Delete` policy by destroying the underlying ZFS dataset on the storage server, **deleting or recreating the cluster without first patching those PVs to `Retain` would permanently destroy all data**. Coordinating that patch across 64 PVs before a rebuild adds significant risk that the in-place migration simply does not have.

A rebuild would be preferable only if starting fresh from scratch. The in-place migration achieves the same outcome (Cilium, NetworkPolicy enforcement) with less risk.

---

## Architecture Notes

- **Pod CIDR:** `10.42.0.0/16` (each node gets a `/24`)
- **Service CIDR:** `10.43.0.0/16`
- **DNS:** `10.43.0.10`
- **Multus** is active: `vpn-secure` (macvlan on `ens19`, DHCP) used by `plex/plex-qbittorrent-0` and `plex/plex-qbittorrent-alt-0`. Multus is compatible with Cilium as the primary CNI — the macvlan attachment is orthogonal to the primary CNI and will work unchanged.
- **Embedded etcd** across kube02 + kube03. Stopping K3s briefly on both control-plane nodes is safe; etcd state persists on disk and is restored on restart.

---

## Expected Downtime

All pod networking drops between Flannel teardown and Cilium becoming ready. In practice this is **5–15 minutes** total cluster outage. External services (MetalLB IPs, ingress) are unreachable during this window.

---

## Pre-Migration Checklist

Run these before the migration window:

```bash
# 1. Verify cluster health
kubectl get nodes
kubectl get pods --all-namespaces | grep -v Running | grep -v Completed

# 2. Confirm etcd health
kubectl -n kube-system exec -it $(kubectl get pods -n kube-system -l component=etcd -o name | head -1) \
  -- etcdctl --endpoints=https://127.0.0.1:2379 \
     --cacert=/var/lib/rancher/k3s/server/tls/etcd/server-ca.crt \
     --cert=/var/lib/rancher/k3s/server/tls/etcd/client.crt \
     --key=/var/lib/rancher/k3s/server/tls/etcd/client.key \
     endpoint health

# 3. Take an etcd snapshot
sudo k3s etcd-snapshot save --name pre-cilium-migration  # run on kube02 or kube03

# 4. Note current Flannel interface details for cleanup reference
kubectl get nodes -o json | python3 -c "
import json,sys; data=json.load(sys.stdin)
for n in data['items']:
    ann=n['metadata']['annotations']
    print(n['metadata']['name'], ann.get('flannel.alpha.coreos.com/backend-type'), ann.get('flannel.alpha.coreos.com/public-ip'))
"

# 5. Confirm ArgoCD is healthy and apps are synced
kubectl get applications -n argocd
```

---

## Migration Procedure

### Step 1 — Prepare K3s configuration on all nodes

On **each server node** (kube02, kube03), update `/etc/rancher/k3s/config.yaml`:

```yaml
# Add these lines (or ensure they exist):
flannel-backend: none
disable-network-policy: true
```

On **each agent node** (kube04, kube05), update `/etc/rancher/k3s/config.yaml`:

```yaml
flannel-backend: none
```

If `/etc/rancher/k3s/config.yaml` does not exist on agent nodes, create it with that single key.

> These flags tell K3s not to start Flannel and not to install its built-in NetworkPolicy controller. Cilium provides both.

### Step 2 — Stop K3s on all nodes

Stop workers first to avoid them attempting to run pods without networking:

```bash
# On kube04, kube05 (workers)
sudo systemctl stop k3s-agent

# On kube02, kube03 (control plane)
sudo systemctl stop k3s
```

### Step 3 — Clean up Flannel artifacts on all nodes

Run on **each node**:

```bash
# Remove CNI config so Flannel config is not re-applied
sudo rm -f /etc/cni/net.d/10-flannel.conflist

# Remove Flannel CNI binary (K3s ships it bundled)
sudo rm -f /opt/cni/bin/flannel

# Delete Flannel virtual interfaces
sudo ip link delete flannel.1 2>/dev/null || true
sudo ip link delete cni0 2>/dev/null || true

# Flush iptables rules added by Flannel/kube-proxy
# (K3s will re-establish correct rules on restart)
sudo iptables -F
sudo iptables -t nat -F
sudo iptables -t mangle -F
sudo iptables -X

# Remove Flannel subnet/IP allocation state
sudo rm -rf /run/flannel
sudo rm -f /var/lib/cni/flannel/*
sudo rm -f /var/lib/cni/networks/cbr0/*
```

> **Note:** `iptables -F` briefly drops all forwarding rules. This is safe during a maintenance window when K3s is already stopped.

### Step 4 — Restart K3s on control-plane nodes

```bash
# On kube02 first, wait for it to be Ready before kube03
sudo systemctl start k3s

# On kube02, watch until node registers
watch kubectl get nodes
# Wait until kube02 shows Ready

# Then on kube03
sudo systemctl start k3s
```

At this point the control plane is up but **no CNI is installed**. Pods will be in `Pending` (CNI not ready) or `ContainerCreating`. This is expected.

### Step 5 — Install Cilium

Cilium is deployed via Helm. Add it to the ArgoCD app-of-apps under `k8s/` so it follows the GitOps pattern.

Create `k8s/cilium/` with a Helm Application:

```yaml
# k8s/cilium/application.yaml
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata:
  name: cilium
  namespace: argocd
spec:
  project: default
  source:
    repoURL: https://helm.cilium.io/
    chart: cilium
    targetRevision: 1.17.x  # pin to latest stable at time of migration
    helm:
      values: |
        kubeProxyReplacement: false   # keep kube-proxy for initial migration; can enable later
        k8sServiceHost: 192.168.4.42  # kube02 control-plane VIP or first server IP
        k8sServicePort: 6443
        ipam:
          mode: kubernetes            # use K3s-assigned pod CIDRs (10.42.x.0/24 per node)
        tunnel: vxlan                 # matches current Flannel VXLAN setup
        operator:
          replicas: 1
        hubble:
          enabled: true
          relay:
            enabled: true
          ui:
            enabled: true
  destination:
    server: https://kubernetes.default.svc
    namespace: kube-system
  syncPolicy:
    automated:
      prune: true
      selfHeal: true
```

Sync immediately after kube02 is back up:

```bash
argocd app sync cilium --timeout 300
# Or via kubectl:
kubectl apply -f k8s/cilium/application.yaml
```

Watch Cilium pods come up:

```bash
kubectl -n kube-system get pods -l k8s-app=cilium -w
```

Wait until all Cilium agent pods on the running nodes are `Running` before proceeding.

### Step 6 — Restart worker nodes

```bash
# On kube04, kube05
sudo systemctl start k3s-agent
```

Cilium agents will start on workers automatically (DaemonSet). Wait for all nodes `Ready`:

```bash
kubectl get nodes -w
```

### Step 7 — Validate

```bash
# All nodes Ready
kubectl get nodes

# All Cilium pods Running
kubectl get pods -n kube-system -l k8s-app=cilium

# Cilium status
kubectl -n kube-system exec -ti ds/cilium -- cilium status

# Connectivity test (creates a temporary namespace)
kubectl apply -f https://raw.githubusercontent.com/cilium/cilium/HEAD/examples/kubernetes/connectivity-check/connectivity-check.yaml
kubectl get pods -n cilium-test -w
# Clean up after
kubectl delete namespace cilium-test

# Confirm Multus macvlan still works
kubectl get pods -n plex -o jsonpath='{range .items[*]}{.metadata.name}{"\t"}{.metadata.annotations.k8s\.v1\.cni\.cncf\.io/network-status}{"\n"}{end}'

# Confirm ingress is reachable from outside
```

### Step 8 — Update Multus configmap (if needed)

Multus reads the primary CNI from whichever `.conf` file is first alphabetically in `/etc/cni/net.d/`. After Cilium installs, it writes `05-cilium.conf` (or similar). Verify Multus is picking it up:

```bash
kubectl -n kube-system exec -ti $(kubectl get pods -n kube-system -l app=multus -o name | head -1) -- ls /etc/cni/net.d/
```

If Multus is still referencing a Flannel config, update `k8s/multus-config/` in the repo to point to the Cilium config file name.

---

## Post-Migration: Apply NetworkPolicies

With Cilium enforcing NetworkPolicies, you can now implement isolation. Recommended starting point — default-deny ingress per namespace:

```yaml
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: default-deny-ingress
spec:
  podSelector: {}
  policyTypes:
    - Ingress
```

Apply to user workload namespaces. ArgoCD, ingress-nginx, cert-manager, kube-system, metallb-system, and monitoring namespaces need explicit allow rules before default-deny is applied.

Cilium also provides `CiliumNetworkPolicy` resources with richer L7 filtering (HTTP method, DNS, etc.) when needed.

---

## Rollback Plan

If the migration fails after Step 4 (K3s back up, Cilium not yet working):

1. Stop K3s on all nodes
2. Remove Cilium configs from `/etc/cni/net.d/`
3. Restore Flannel config: revert `/etc/rancher/k3s/config.yaml` on all nodes (remove `flannel-backend: none` and `disable-network-policy: true`)
4. Restart K3s — it will reinstall Flannel automatically
5. Delete the Cilium ArgoCD Application

If etcd state is corrupted, restore from the snapshot taken in the pre-migration checklist:

```bash
sudo k3s server --cluster-reset --cluster-reset-restore-path=/var/lib/rancher/k3s/server/db/snapshots/pre-cilium-migration
```

---

## Rebuild Path (Reference Only)

If a full rebuild is ever desired in the future, these steps are required **before** decommissioning the cluster to avoid data loss:

1. **Patch all Delete-policy PVs to Retain** before deleting any PVCs:

   ```bash
   kubectl get pv -o json | \
     python3 -c "import json,sys; [print(i['metadata']['name']) for i in json.load(sys.stdin)['items'] if i['spec'].get('persistentVolumeReclaimPolicy')=='Delete']" | \
     xargs -I{} kubectl patch pv {} -p '{"spec":{"persistentVolumeReclaimPolicy":"Retain"}}'
   ```

2. Record all PV → ZFS dataset mappings from democratic-csi (stored in PV annotations) so volumes can be re-imported post-rebuild.
3. After rebuild, pre-create PV objects pointing at the existing ZFS datasets and bind them to new PVCs before deploying applications.
4. The `authentik/redis-data-authentik-redis-master-0` PVC on `local-path` storage **cannot be recovered** — it is on a node's local disk. Plan for Authentik data loss or back up the Redis data before rebuilding.
