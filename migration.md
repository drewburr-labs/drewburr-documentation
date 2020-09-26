# migration.md

Documenting the effort to migrate from Digital Ocean to a local Proxmox host. This is mainly about saving money, since I'm not using the platform enough to justify the cost.

## Proxmox server

Host details

```text
FQDN - prdpve01.drewburr.com
IPv4 - 192.168.1.101
Management Interface - enp8s0
Web portal port - 8006
```

## Other servers

Rebuilt the IPA server for local to ensure docs were up to date and proper.

Rebuilt the OpenConnect server to allow external connections/deployments into the network.

Created prddiscord01 to hold all the Discord bots for now. Eventually I'll want this to be in Kubernetes.
