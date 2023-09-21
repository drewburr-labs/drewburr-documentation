# drewburr documentation

Documentation related the the drewburr.com environment

## Index

- [Environment Overview](#environment-overview)
- [Operational Essentials](#operational-essentials)

## Environment Overview

The core goal of this architecture is to allow for simple mangement and control of a Kubernetes environment, while also providing high availability and redundancy throughout the stack. It should be possible to migrate workloads off a particular physical server (further referred to as a blade), then reboot said blade without causing downtime to the rest of the cluster. In a perfect world, an unexpected, hard-down situation should still allow for stateful, HA-configured services within the Kuberenetes cluster to remain up and operational throughout the loss and recovery of the blade. Services should be resilient to an accidental dismount of a blade's power cable.

The drewburr environment consists of a 4-node [Proxmox VE](https://pve.proxmox.com/wiki/Main_Page) (PVE) cluster, which hosts [Ubuntu](https://ubuntu.com/download/server) VMs. Each VM is dedicated to running a HA [K3s](https://k3s.io/) cluster.

PVE is manually provisioned on bare metal via ISO installer. Each blade provides a 500GB NVMe drive, a 6 core CPU (i5-9500T @ 2.20GHz), and 16GB of DDR4 memory (8GBx2). Each NVMe drive is allocated to a [Ceph](https://docs.ceph.com/en/latest/) cluster that is managed by PVE. Ceph provides a RDB filesystem to PVE, creating up to ~500GB of safely replicated storage across the cluster (higher values create risk during blade downtime).

Each Ubuntu VM is cloned from a common VM template, then is initialized by [Cloud-Init](https://cloudinit.readthedocs.io/en/latest/) on first startup. The process of cloning, configuring, and starting a new VM is handled by automation defined in [drewburr-labs/proxmox-automation](https://github.com/drewburr-labs/proxmox-automation). This same repository contains the automation used to install and configure the Kubernetes clsuter.

## Operational Essentials

In order to have a resilient and effective environment, as well as to ensure operational effectiveness as a user and administrator of said environment, a few key items should be considered hard requirements before fully leaning into a Kubernetes environment. The following items should be accounted for from day 1.

- Deployability: Automated processes and standardized techniques to create and update Kuberenetes definitions.
- Observability: Quickly and accurately view and describe the current and historical health of the environment and the services within it.
- Secrets management: Management and exposure of sensitive information with scalable, programmatic processes.
- Service exposure: Opening ports, creating DNS records, managing certificates.
- Log aggregation: View logs from across the environment in a single location.
