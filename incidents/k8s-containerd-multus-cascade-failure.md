# K8s: Pods Stuck in ContainerCreating — Containerd/Multus Cascade Failure

## Summary

Pods get stuck in `ContainerCreating` indefinitely across one or more nodes. The root cause is a
self-reinforcing failure loop involving stale containerd sandboxes and Multus CNI rate limiting.
This typically follows an unclean node restart or containerd crash.

---

## Identifying the Issue

### Step 1: Check the stuck pod

```bash
kubectl describe pod <pod-name> -n <namespace>
```

A pod stuck in `ContainerCreating` with only a `Scheduled` event and no further progress is the
first indicator:

```
Events:
  Type    Reason     Age    From               Message
  ----    ------     ----   ----               -------
  Normal  Scheduled  5m     default-scheduler  Successfully assigned plex/plex-radarr-0 to kube03
```

### Step 2: Check namespace events for CNI/sandbox errors

```bash
kubectl get events -n <namespace> --sort-by='.lastTimestamp'
```

Look for either of these patterns:

**Stale sandbox reservation:**
```
Warning  FailedCreatePodSandBox  pod/plex-radarr-0  Failed to create pod sandbox: rpc error:
code = Unknown desc = failed to reserve sandbox name
"plex-radarr-0_plex_e7fc1981-..._0": name "plex-radarr-0_plex_e7fc1981-..._0" is reserved
for "8cfb644d1e4a43be64e7184e4b764c6a1cdc42fc97622eca1d9c5442d3727b6f"
```

**CNI timeout:**
```
Warning  FailedCreatePodSandBox  pod/plex-radarr-0  Failed to create pod sandbox: rpc error:
code = DeadlineExceeded desc = context deadline exceeded
```

If the blocking container ID keeps changing with every event, the cascade is active — each failed
attempt is leaving a new stale reservation.

### Step 3: Check the k3s journal on the affected node

```bash
ssh ubuntu@<node>.drewburr.com "sudo journalctl -u k3s --since '10 minutes ago' --no-pager 2>&1 | grep -E 'DeadlineExceeded|reserve sandbox' | tail -20"
```

If you see `DeadlineExceeded` errors for many different pods across multiple namespaces, the node
has a node-wide cascade failure rather than a pod-specific issue.

### Step 4: Check for stale sandboxes on the node

```bash
ssh ubuntu@<node>.drewburr.com "sudo crictl --runtime-endpoint unix:///run/k3s/containerd/containerd.sock pods 2>&1"
```

Sandboxes with `NotReady` state and a creation time of `271 years ago` are stale remnants from a
previous containerd crash. These are the source of the name reservations blocking new pods.

```
POD ID              CREATED             STATE      NAME                 NAMESPACE   ATTEMPT
bf45b21fca9b7       271 years ago       NotReady   ingress-nginx-...    ingress-... 1
0005841533a4b       271 years ago       NotReady   loki-backend-2       loki        0
42bfc92287efb       271 years ago       NotReady   promtail-j2l9d       promtail    0
```

### Step 5: Check the Multus daemon logs

```bash
kubectl logs -n kube-system <kube-multus-ds-pod> --tail=50
```

The Multus rate limiter error confirms the cascade is active:

```
[error] Multus: [plex/plex-radarr-0/e7fc1981-...]: error waiting for pod:
client rate limiter Wait returned an error: context deadline exceeded
```

You may also see the flannel delegation failure caused by the race condition between containerd
cleaning up a failed netns and Multus still trying to configure it:

```
[error] DelegateAdd: cannot set "" interface name to "eth0": validateIfName:
no net namespace /var/run/netns/cni-c389a3e7-9ea2-cf85-1c8d-6fdde0ddb04d found:
failed to Statfs "/var/run/netns/cni-c389a3e7-...": no such file or directory
```

---

## Root Cause

The failure is a self-reinforcing loop with two components:

1. **Stale sandbox reservations** — An unclean containerd restart leaves dead pod sandboxes in
   containerd's name registry. New pods with the same names cannot start because the name is
   "reserved" for a non-existent container. Each failed attempt creates a new reservation,
   compounding the problem.

2. **Multus API rate limiter saturation** — Multus must query the Kubernetes API for pod metadata
   during CNI setup. When many pods are simultaneously retrying, the volume of API calls trips
   Multus's client-side rate limiter. CNI calls then time out, causing more sandbox failures,
   which cause more retries — a feedback loop.

---

## Resolution

### Step 1: Remove all stale NotReady sandboxes

On the affected node, force-remove all `NotReady` sandboxes in one command:

```bash
ssh ubuntu@<node>.drewburr.com "sudo crictl --runtime-endpoint unix:///run/k3s/containerd/containerd.sock pods 2>&1 \
  | grep NotReady \
  | awk '{print \$1}' \
  | xargs -I{} sudo crictl --runtime-endpoint unix:///run/k3s/containerd/containerd.sock rmp --force {}"
```

Expected output:
```
Removed sandbox bf45b21fca9b7
Removed sandbox 0005841533a4b
Removed sandbox 37f53ec209be7
Removed sandbox 42bfc92287efb
...
```

### Step 2: Restart the Multus DaemonSet pod on the affected node

Restarting Multus clears the saturated rate limiter and any pending in-flight requests.

First, find the Multus pod on the node:
```bash
kubectl get pod -n kube-system -l app=multus --field-selector spec.nodeName=<node>
```

Then delete it (the DaemonSet will immediately reschedule it):
```bash
kubectl delete pod -n kube-system <kube-multus-ds-pod>
```

### Step 3: Verify recovery

```bash
kubectl get pod -n <namespace> <pod-name>
```

The pod should transition out of `ContainerCreating` within ~30 seconds:
```
NAME            READY   STATUS    RESTARTS   AGE
plex-radarr-0   1/1     Running   0          97m
```

Check that no other pods on the node are still stuck:
```bash
kubectl get pods -A --field-selector spec.nodeName=<node> | grep -v Running
```

---

## Notes

- **This is a node-wide issue.** If one pod is stuck with these symptoms, other pods on the same
  node will likely be affected too. Check all pods on the node before assuming it is isolated.

- **A k3s restart alone may not be sufficient.** Restarting k3s clears some state but the Multus
  rate limiter loop can re-establish itself quickly if many pods begin retrying simultaneously
  before Multus has fully recovered. The targeted crictl cleanup + Multus pod restart is more
  reliable.

- **The `271 years ago` timestamp** is a reliable indicator of a corrupted/stale sandbox entry.
  It results from containerd loading a zero or invalid Unix timestamp from a previous crashed
  session.

- **The `rbd.csi.ceph.com not found` error** may appear in logs alongside this issue. It is
  unrelated — it refers to a separate stuck volume unmount for a PV that previously used Ceph RBD
  CSI (no longer present in the cluster). It does not cause the ContainerCreating failure.
