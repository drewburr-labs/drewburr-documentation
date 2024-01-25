# ArgoCD

```shell
kubens argocd
helm dependency update # or `build`
helm template argocd . > template.yaml
kubectl diff -f template.yaml
# kubectl apply -f template.yaml
```
