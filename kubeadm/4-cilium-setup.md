# Cilium Setup

Installation using kubeadm [docs](https://docs.cilium.io/en/stable/installation/k8s-install-kubeadm/)

## Setup dependencies

Installation of Helm from binary release [(docs)](https://helm.sh/docs/intro/install/#from-the-binary-releases)

```shell
DOWNLOAD_DIR="/usr/local/bin"
# https://github.com/helm/helm/releases
HELM_RELEASE=v3.13.2
curl -L "https://get.helm.sh/helm-${HELM_RELEASE}-linux-amd64.tar.gz" | sudo tar -C $DOWNLOAD_DIR -xz
sudo mv $DOWNLOAD_DIR/linux-amd64/helm $DOWNLOAD_DIR
sudo rm -rf $DOWNLOAD_DIR/linux-amd64
```

## Cilium Installation

```shell
API_SERVER_IP=10.128.0.3
API_SERVER_PORT=6443
CILIUM_RELEASE=1.14.4
helm repo add cilium https://helm.cilium.io/
# https://github.com/cilium/cilium/releases
helm install cilium cilium/cilium --version ${CILIUM_RELEASE} \
    --namespace kube-system \
    --set kubeProxyReplacement=true \
    --set k8sServiceHost=${API_SERVER_IP} \
    --set k8sServicePort=${API_SERVER_PORT}
```
