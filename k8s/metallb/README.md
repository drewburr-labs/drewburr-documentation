# MetalLB

At the time of writing, there was not a reliable source for a MetalLB Helm Chart. Instead of a depoendency, this Chart includes definitions defined [in the MetalLB repo itself](https://github.com/metallb/metallb/blob/v0.13.11/config/manifests/metallb-native-prometheus.yaml).

```shell
kubens metallb
helm template metallb . > template.yaml
```
