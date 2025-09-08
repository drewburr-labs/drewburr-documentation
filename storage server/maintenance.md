# Storage Maintenance

## Shutdown relevant workloads

`group by (namespace, pod)(kube_pod_spec_volumes_persistentvolumeclaims_info)`

Regex replace

```text
.*="([\w-]+)",.*="([\w-]+)".*
kubectl delete pod -n \1 \2 --wait=false
```

Cordon all nodes, then run the generated commands

Confirm pods are all down

`kubectl get pods -A | grep Terminating`

Storage is now safe to shut down from a K8s perspective
