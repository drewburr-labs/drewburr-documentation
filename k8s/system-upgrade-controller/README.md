# system-upgrade-controller

Controller for handling K3s upgrades

Uses Plans to define upgrade targets and process. Plans should be applied into the `system-upgrade` namespace

The process used in [upgrade-plan.yaml](./upgrade-plan.yaml) required the K3s version to be updated, and the target nodes to be given a `k3s-upgrade: true` label.

`# kubectl label node kube01 k3s-upgrade=true`

See [k3s-io/k3s-upgrade](https://github.com/k3s-io/k3s-upgrade) for additional details.

Post-upgrade, labels can be removed via:

`kubectl label node kube04 k3s-upgrade-`

## Upgrade steps

0. Double check if nodes have the `k3s-upgrade` label set. If this exists at all, an upgrade will be executed when applying the plan.
1. Update [upgrade-plan.yaml](./upgrade-plan.yaml) with the K3s verion to upgrade to.
2. Apply `upgrade-plan.yaml` to the `system-upgrade` namespace.
3. Add `k3s-upgrade` label to a node, and monitor cluster health. It is reccommended to upgade one node at a time, and to upgrade the controllers last.
4. Upgrade remaining nodes.
5. Remove `k3s-upgrade` label from all nodes, to avoid an accidental upgrade.
