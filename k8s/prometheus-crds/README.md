# prometheus-crds

Installing CRDS - [docs](https://github.com/prometheus-community/helm-charts/tree/main/charts/kube-prometheus-stack#upgrading-chart)

Template and install chart

```sh
helm template prometheus-crds . > template.yaml
kubectl create -f template.yaml
```

Upgrades should be completed via `kubectl replace`
