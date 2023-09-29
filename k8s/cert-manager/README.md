helm template cert-manager . > template.yaml
kubectl apply -f template.yaml
