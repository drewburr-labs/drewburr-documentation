# AGENTS.md

Guidance for AI agents working in this repository.

## Hostnames

All hostnames in this repository and environment are accessible under the
`drewburr.com` domain. Short names in the docs (e.g. `pve05`, `storage01`,
`spud`) are not DNS-resolvable on their own — append `.drewburr.com` to reach
them, e.g. `pve05` is accessible at `pve05.drewburr.com`.

When connecting to a host, use the FQDN:

```sh
ssh pve05.drewburr.com
ssh storage01.drewburr.com
```

## SSH access

- **Proxmox hosts** (`pve01`, `pve02`, `pve03`, `pve05`): log in as `root` with a
  password. SSH key auth is not set up for these. They answer on the usual port 22
  over the VPN tunnel; the web UI is at `https://<host>:8006`.
- **VMs and workstations** (`storage01` as `ubuntu`, the `kube*` nodes, `spud`,
  `airunner01`): SSH key auth only — no password needed. Reach each VM directly by
  its own hostname/IP; you do not go through its Proxmox host.
- `airunner01` may be powered off; confirm it is up before relying on it.
