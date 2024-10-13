Setup

Delete default K3s Traefik install

```shell
kubens kube-system
kubectl delete helmchart traefik traefik-crd
# Ensure delete pods have completed
kubectl get pods

NAME                                      READY   STATUS      RESTARTS      AGE
helm-delete-traefik-frk5p                 0/1     Completed   0             87s
# Delete job to finish cleanup
kubectl delete jobs.batch helm-delete-traefik
```

Installation

```shell
kubectl create ns traefik
kubens traefik

# First time:
# helm template --include-crds traefik . > template.yaml
helm template traefik . > template.yaml

kubectl diff -f template.yaml
kubectl apply -f template.yaml

# Delete legacy CRDs, if applied: https://github.com/traefik/traefik-helm-chart/pull/913
# kubectl get crd | grep 'traefik.containo.us' | awk '{ print $1 }' | xargs kubectl delete crd
```
