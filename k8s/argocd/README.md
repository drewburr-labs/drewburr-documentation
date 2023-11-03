# ArgoCD

```shell
kubens argocd
helm template argocd . > template.yaml
kubectl diff -f template.yaml
# kubectl apply -f template.yaml
```
