# K3s Cluster Security Benchmark

**Date:** 2026-04-12
**Cluster:** k3s.drewburr.com
**K3s Version:** v1.35.2+k3s1
**Nodes:** kube02, kube03 (control-plane/etcd), kube04, kube05 (workers)
**OS:** Ubuntu 24.04.4 LTS

---

## Methodology

This benchmark combines:

- **kube-bench** CIS Kubernetes Benchmark v1.12 (worker node & policy sections)
- Manual RBAC audit via `kubectl`
- Pod security posture review (privileged containers, hostNetwork/hostPID, securityContext)
- Network policy coverage check
- Service account token and secret handling review
- Image hygiene review

> **Note:** K3s bundles apiserver, etcd, controller-manager, and scheduler into a single binary (`k3s server`). kube-bench's generic CIS benchmark does not include a K3s-specific master node profile in the current image; master node checks (sections 1–3) are not covered by the automated scan. Worker node (section 4) and policy (section 5) results are included.

---

## Executive Summary

| Severity | Count |
|----------|-------|
| High     | 4     |
| Medium   | 6     |
| Low      | 4     |
| Info     | 3     |

**kube-bench Totals (sections 4–5):** 5 PASS · 10 FAIL · 44 WARN

Most critical issues relate to kubelet authentication/authorization configuration and the absence of any network policy or pod security enforcement across the cluster. CSI driver and infrastructure daemonset findings (privileged, hostNetwork) are expected and documented as accepted risk.

---

## Findings

### HIGH — Kubelet Anonymous Authentication Enabled

**Finding:** CIS 4.2.1 — kubelet `--anonymous-auth` is not set to `false`.
Unauthenticated requests to the kubelet API are allowed, meaning the kubelet's read endpoints (`/logs`, `/stats`) may be reachable without credentials from within the cluster network.

**Remediation:** On each node, edit `/var/lib/rancher/k3s/agent/kubelet.kubeconfig` or add to the K3s server/agent config:

```yaml
# /etc/rancher/k3s/config.yaml (on each node)
kubelet-arg:
  - "anonymous-auth=false"
```

---

### HIGH — Kubelet Authorization Mode Not Set to Webhook

**Finding:** CIS 4.2.2 — kubelet `--authorization-mode` is not restricted; the default `AlwaysAllow` means any authenticated request to the kubelet API is authorized.

**Remediation:**

```yaml
kubelet-arg:
  - "authorization-mode=Webhook"
```

---

### HIGH — Kubelet Client CA Not Configured

**Finding:** CIS 4.2.3 — `--client-ca-file` is not set on the kubelet. Without this, the kubelet cannot verify the identity of the API server making requests.

**Remediation:**

```yaml
kubelet-arg:
  - "client-ca-file=/var/lib/rancher/k3s/agent/client-ca.crt"
```

K3s places the CA at this path on each node.

---

### HIGH — kube-proxy Metrics Exposed on All Interfaces

**Finding:** CIS 4.3.1 — kube-proxy metrics service is not bound to localhost (`127.0.0.1`). The metrics endpoint is accessible on all node interfaces, potentially leaking internal cluster topology.

**Remediation:** Configure kube-proxy to bind metrics to localhost only. In K3s this is managed via the embedded kube-proxy configuration.

---

### MEDIUM — Kubelet Config File Permissions Too Permissive

**Findings:**

- CIS 4.1.1 — Kubelet service file permissions are not `600`
- CIS 4.1.5 — `/var/lib/rancher/k3s/agent/kubelet.kubeconfig` permissions are not `600`
- CIS 4.1.9 — `/var/lib/kubelet/config.yaml` permissions are not `600`
- CIS 4.1.10 — `/var/lib/kubelet/config.yaml` not owned by `root:root`

**Remediation:** On each node:

```bash
chmod 600 /var/lib/rancher/k3s/agent/kubelet.kubeconfig
chmod 600 /var/lib/kubelet/config.yaml
chown root:root /var/lib/kubelet/config.yaml
```

---

### MEDIUM — Anonymous ClusterRoleBinding (system:public-info-viewer)

**Finding:** The `system:public-info-viewer` ClusterRoleBinding grants the `system:unauthenticated` group access to the `system:public-info-viewer` ClusterRole. This allows unauthenticated users to query cluster info endpoints.

```
system:public-info-viewer -> system:public-info-viewer [Group: system:unauthenticated]
```

**Remediation:** Evaluate whether anonymous discovery is required. If not, remove the binding:

```bash
kubectl delete clusterrolebinding system:public-info-viewer
```

---

### MEDIUM — Stale cluster-admin Bindings for Traefik Helm Jobs

**Finding:** Two ClusterRoleBindings grant `cluster-admin` to Helm-managed Traefik service accounts that are likely lingering post-install:

- `helm-kube-system-traefik` → `ServiceAccount:helm-traefik`
- `helm-kube-system-traefik-crd` → `ServiceAccount:helm-traefik-crd`

These were created by K3s's built-in Helm controller during Traefik chart installation and may not be cleaned up after the job completes.

**Remediation:** Verify the service accounts and jobs no longer exist, then remove the bindings if unused. If they are still required by the Helm controller lifecycle, no action is needed — document as accepted risk.

---

### MEDIUM — No NetworkPolicies Defined Anywhere

**Finding:** Zero NetworkPolicy objects exist in the cluster. All pods can communicate with all other pods across all namespaces by default, providing no lateral movement boundaries.

```
kubectl get networkpolicy --all-namespaces  # (no results)
```

**Remediation:** Implement default-deny ingress policies per namespace and explicitly allow required traffic. A recommended starting point:

```yaml
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: default-deny-ingress
  namespace: <namespace>
spec:
  podSelector: {}
  policyTypes:
    - Ingress
```

Apply to all user-workload namespaces. Note: K3s ships with Flannel as the default CNI; Flannel does **not** enforce NetworkPolicies. You must deploy a NetworkPolicy-capable CNI (e.g., Cilium, Calico, Canal) for policies to take effect.

---

### MEDIUM — No Pod Security Standards Enforcement

**Finding:** 47 out of 50 namespaces have no Pod Security Standards (PSS) labels. Only three namespaces enforce PSS, all at the `privileged` level (democratic-csi, system-upgrade). No namespace enforces `baseline` or `restricted`.

**Remediation:** Apply at minimum `baseline` enforcement to all user-workload namespaces:

```bash
kubectl label namespace <ns> pod-security.kubernetes.io/enforce=baseline
kubectl label namespace <ns> pod-security.kubernetes.io/warn=restricted
```

Namespaces with legitimate privileged requirements (CSI drivers, Multus, MetalLB) should be explicitly labeled `privileged` with documentation.

---

### MEDIUM — Certificate Rotation Not Enabled on Kubelet

**Finding:** CIS 4.2.10 — `rotateCertificates` is not set to `true` on the kubelet. If kubelet certificates expire, nodes will lose connectivity to the API server.

**Remediation:**

```yaml
kubelet-arg:
  - "rotate-certificates=true"
```

---

### LOW — 161 Containers Without Resource Limits

**Finding:** 161 running containers have no CPU or memory limits set. This allows any container to consume unbounded node resources, creating denial-of-service risk.

**Remediation:** Set resource requests and limits on all Deployments, StatefulSets, and DaemonSets. Apply LimitRange objects to namespaces to enforce defaults:

```yaml
apiVersion: v1
kind: LimitRange
metadata:
  name: default-limits
spec:
  limits:
    - type: Container
      default:
        cpu: 500m
        memory: 256Mi
      defaultRequest:
        cpu: 100m
        memory: 64Mi
```

---

### LOW — 36 Containers Using :latest or Untagged Images

**Finding:** 36 containers use `:latest` or untagged image references, preventing reproducible deployments and making it harder to reason about what code is running.

Notable examples:

- `democratic-csi/democratic-csi:latest` (all node/controller pods)
- `craftycontroller:latest` (multiple namespaces)
- `ubuntu`, `alpine` (untagged)
- `minecraft-*` namespaces (various)

**Remediation:** Pin all images to a specific digest or semantic version tag.

---

### LOW — makeIPTablesUtilChains Not Set to True

**Finding:** CIS 4.2.6 — kubelet `makeIPTablesUtilChains` is not set, which can affect iptables chain management on nodes.

**Remediation:**

```yaml
kubelet-arg:
  - "make-iptables-util-chains=true"
```

---

### INFO — Privileged CSI Driver Containers (Accepted Risk)

**Finding:** All democratic-csi node driver pods run with `privileged: true`, `allowPrivilegeEscalation: true`, `SYS_ADMIN`, and `hostNetwork`. This is expected and required behavior for CSI drivers that interact with kernel storage subsystems (ZFS, NFS, NVMe-oF).

**Status:** Accepted risk. Three of the four affected namespaces are already labeled `pod-security.kubernetes.io/enforce=privileged`.
**Recommendation:** Label `democratic-csi-nfs-lake` with the same `privileged` PSS label for consistency.

---

### INFO — 59 Containers Using Secrets as Environment Variables

**Finding:** 59 containers inject secrets via `env.valueFrom.secretKeyRef` (e.g., ArgoCD Redis credentials, database passwords). Secrets in environment variables are accessible to any process in the container and appear in debug dumps.

**Status:** Low-priority in a homelab context. For higher-security workloads, prefer mounting secrets as files or using a secret store (e.g., Vault, External Secrets Operator).

---

### INFO — Service Account Token Automount

**Finding:** 111 non-default service accounts have `automountServiceAccountToken` unset or `true`, meaning pods using these accounts receive a mounted API token by default.

Notable: ArgoCD SAs require tokens (intentional). cert-manager SAs require tokens (intentional).

**Recommendation:** Explicitly set `automountServiceAccountToken: false` on service accounts that do not need API access, and `true` on those that do, to make intent clear:

```yaml
automountServiceAccountToken: false  # for workloads with no k8s API access
```

---

## Accepted Risk Summary

| Finding | Reason |
|---------|--------|
| CSI driver privileged containers (democratic-csi) | Required for kernel-level storage (ZFS/NFS/NVMe-oF) |
| Multus DaemonSet privileged | Required for CNI plugin binary installation |
| MetalLB speaker SYS_ADMIN | Required for FRR/BGP route management |
| node-exporter hostNetwork + hostPID | Required for accurate host-level metrics |
| kube-summary-exporter hostNetwork | Required to reach kubelet metrics endpoint |

---

## Remediation Priority

| Priority | Action |
|----------|--------|
| 1 (immediate) | Disable kubelet anonymous auth, set authorization-mode=Webhook, set client-ca-file |
| 2 | Fix kubelet config file permissions (chmod 600, chown root:root) |
| 3 | Evaluate and remove anonymous ClusterRoleBinding if not required |
| 4 | Deploy NetworkPolicy-capable CNI (Cilium recommended) and implement default-deny policies |
| 5 | Apply Pod Security Standards labels to all user-workload namespaces |
| 6 | Pin container images to specific version tags |
| 7 | Set resource limits on all workloads |
| 8 | Set automountServiceAccountToken: false on SAs that don't need API access |
