# drewburr documentation

Documentation related to the drewburr.com environment.

> All hostnames in this repository are under the `drewburr.com` domain unless otherwise stated (e.g. `pve05` means `pve05.drewburr.com`).

## Index

- [Environment Overview](#environment-overview)
- [Operational Essentials](#operational-essentials)
- [Minecraft server hosting: service offering](minecraft-hosting/README.md)
- [Workstation: OpenRGB lighting](workstation/openrgb/README.md)
- [qBittorrent over VPN: routing, port forward, UniFi gotchas](k8s/plex/qbittorrent/README.md)

## Environment Overview

The core goal of this architecture is to allow for simple mangement and control of a Kubernetes environment, while also providing high availability and redundancy whre possible. It should be possible to migrate workloads off a particular physical server, then reboot said server without causing downtime to the rest of the cluster. In a perfect world, an unexpected, hard-down situation should still allow for stateful, HA-configured services within the Kuberenetes cluster to remain up and operational throughout loss and recovery.

The drewburr environment consists of a 4-node [Proxmox VE](https://pve.proxmox.com/wiki/Main_Page) (PVE) cluster hosting [Ubuntu](https://ubuntu.com/download/server) VMs. (Current hardware verified October 2026.)

|Node|Model|CPU|Memory|Networking|Storage|Usage|
|-|-|-|-|-|-|-|
|[pve01](servers/pve01/README.md)|Intel NUC8i7HVK (Hades Canyon)|i7-8809G (4C/8T)|32GB DDR4|1GbE, DHCP|480GB NVMe (OS), 960GB PLP NVMe|Proxmox VE 8.4, unattended install; replaces the retired HP ProDesk pve01. No guest VMs currently.|
|pve02|HP ProDesk 400 G5 Desktop Mini|i9-9900T (engineering sample; reports as `Genuine Intel 0000 @ 1.70GHz`, 8C/16T)|64GB DDR4|2.5GbE|500GB NVMe, 250GB SATA SSD|VM `kube02` running K3s|
|pve03|HP ProDesk 400 G5 Desktop Mini|i9-9900T (engineering sample; reports as `Genuine Intel 0000 @ 1.70GHz`, 8C/16T)|64GB DDR4|2.5GbE|500GB NVMe, 250GB SATA SSD|VM `kube03` running K3s|
|pve05|Custom build (Gigabyte X570 AORUS MASTER)|Ryzen 7 5800XT|128GB DDR4|10GbE|20x 400GB SAS SSD, 6x 12-14TB HDD, 4TB NVMe, 500GB SATA SSD|VM `storage01` hosting a raidz3 SSD pool and a raidz2 HDD pool, provided over NVMe-oF and NFS. Secondary VM `kube05` running K3s|

> **pve04 was decommissioned.** The original pve01 and pve04 (both HP ProDesk 400 G5 / i9-9900T units) were repurposed for an unrelated project; pve01 was later rebuilt on the Intel NUC above. The cluster is now four nodes (pve01, pve02, pve03, pve05).

Each Ubuntu VM is cloned from a common VM template, then is initialized by [Cloud-Init](https://cloudinit.readthedocs.io/en/latest/) on first startup. The process of cloning, starting, and configuring a new VM is handled by Ansible automation defined in [drewburr-labs/proxmox-automation](https://github.com/drewburr-labs/proxmox-automation). This same repository contains the automation used to install and configure the Kubernetes cluster.

## Operational Essentials

In order to have a resilient and effective environment, as well as to ensure operational effectiveness as a user and administrator of said environment, a few key items should be considered hard requirements before fully leaning into a Kubernetes environment. The following items should be accounted for from day 1.

- Service exposure: Opening ports, creating DNS records, managing certificates.
- Observability: Quickly and accurately view and describe the current and historical health of the environment and the services within it.
- Deployability: Automated processes and standardized techniques to create and update Kuberenetes definitions.
- Storage: Persistent storage option
- Secrets management: Management and exposure of sensitive information with scalable, programmatic processes.
- Log aggregation: View logs from across the environment in a single location.

### Service exposure

[MetalLB](https://metallb.universe.tf/)  is used to provide IP add assignment for LoadBalancer services. This is required as the drewburr environment is not cloud-based, and thus does not receive the required controllers out of the box.

[Cert-manager](https://cert-manager.io/) provides certificate creation and rotation methods. ACME with Let's Encrypt was preferred, noting the cost and ease of use.

Ingress-nginx provides proxying for web-based services. Its flexibility as a service and extensive usage make it notable over the alternatives.

### Observability

[Prometheus](https://prometheus.io/) is used for metric data aggregation. Its simplicity in setup, widespread support, and surrounding CRDs make it a default for a time-series database. The Prometheus community also provides a suite of helm charts which make metrics enablement simple. In my case, I utilized the [kube-prometheus-stack](https://github.com/prometheus-community/helm-charts/tree/main/charts/kube-prometheus-stack) chart to immediately enable base K8s metrics and setup surrounding components.

[Grafana](https://grafana.com/) provides the web UI and alerting functionality, based on Prometheus data. The `kube-prometheus-stack` Helm chart also provides Grafana out of the box, making this an easy choice. I also have a fair sum of experience working with Grafana, making this a personal preference.

### Storage

Originally I used Ceph for storage, but found the speeds I was able to get with the then 1GbE networking was far below what I considered a minimum. I have a lot of fast hardware and was pushing USB 2.0 speeds. Instead, I opted to centralize my storage, upgrade the ProDesk nodes to 2.5GbE via a network card swap, and purchase a [MikroTik CRS310-8G+2S+IN](https://mikrotik.com/product/crs310_8g_2s_in) to support 2.5 and 10Gb networking without breaking the bank.

pve05 hosts 20x 400GB enterprise SAS SSDs in a raidz3 pool (`sas-pool`, ~7TB) and 6x 12-14TB HDDs in a raidz2 pool (`lake`, ~65TB raw) used for Plex media. The SAS controller and the motherboard SATA controller are provided directly to the `storage01` VM using PCI passthrough, and democratic-csi is responsible for creating volumes and exposing them over NVMe-oF or NFS, depending on context. The storage and client VMs are configured via Ansible automation as needed. With this setup, I'm able to reliably saturate the 10Gb line at the cost of 10-15% CPU usage. Far fewer moving parts, and significantly improved speeds.

If I find a need for replicated distributed storage, I will likely opt to local-hostpath the unused SATA SSDs on each host and dedicate them to a replicated Minio cluster.

### Secrets Management

TBD. I've been wanting to use Bitwarden, but it seems their support of this is relatively limited and a bit sketchy. Currently all secrets are manually created and stored in Bitwarden.

### Log Aggregation

TBD. This is something I need to set up, even if its to keep a week worth of logs. There have been several times where viewing logs across several pods would be a massive help.
