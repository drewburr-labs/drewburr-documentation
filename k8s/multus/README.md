# multus

Multus (thick plugin) gives pods extra network interfaces. The only
attachment in use is `vpn-secure` (`k8s/multus-config/nad.yaml`): a
macvlan on the VLAN 6 NIC with DHCP IPAM, used by qBittorrent. See
[`k8s/plex/qbittorrent/README.md`](../plex/qbittorrent/README.md).

This page was written on 2026-10-24 from the state of the nodes. The
host-side setup below was done by hand and wasn't written down before.

## How it fits together

- containerd calls `multus-shim` as its CNI plugin.
- The shim hands the request to the `kube-multus-ds` daemon over a
  socket.
- The daemon calls flannel for the pod's primary network. It then calls
  the delegate plugins for any extra attachments (`macvlan`, plus `dhcp`
  for IPAM).

## Paths

k3s keeps two CNI directories, and they're used by different things:

| Path | Used by | Contents |
| ---- | ------- | -------- |
| `/var/lib/rancher/k3s/data/cni` | **containerd** (`bin_dirs` in `/var/lib/rancher/k3s/agent/etc/containerd/config.toml`). This is the only place containerd looks for CNI plugins. | k3s symlinks (flannel, bridge, portmap, ...), plus `multus-shim` and `passthru` copied in by hand in 2025-09 |
| `/var/lib/rancher/k3s/data/current/bin` | **multus daemon** (`cni.binDir` in `values.yaml`, which sets the daemon's `binDir` and the init container's install target) | k3s binaries, `multus-shim` and `passthru` installed by the chart's init container, and the hand-installed `macvlan`, `dhcp` and `host-device` |
| `/opt/cni/bin` | nothing | `multus-shim`, `passthru` left from the 2025-09 install |

`cni.binDir` does two jobs, so don't change it to fix only one of them.
The chart's init container copies `multus-shim` into `binDir`, where
containerd never looks. The daemon finds its delegate plugins through
the same `binDir`. #65 pointed it at `data/cni` to fix the shim. That
would have hidden `macvlan` and `dhcp` from the daemon and broken
`vpn-secure`; it was reverted in #66 before it was synced.

`data/current` is a symlink that k3s repoints to a new
`data/<hash>/` directory on every upgrade. Anything put in it by hand
has to be put in again after a k3s upgrade.

## Hand-installed pieces

### Delegate plugins

`macvlan`, `dhcp` and `host-device` from the CNI plugins **v1.8.0**
release (the version the binaries report), in
`/var/lib/rancher/k3s/data/current/bin`. They were copied in on
2026-03-08, into both the current k3s data directory (`f8ef5058...`) and
the previous one (`9ba85800...`). k3s doesn't ship them.

### dhcp.service

The `dhcp` IPAM plugin needs its daemon running on the host.
`/etc/systemd/system/dhcp.service`, enabled on each node that runs
`vpn-secure` pods:

```ini
[Unit]
Description=CNI DHCP daemon
Documentation=https://www.cni.dev/plugins/current/ipam/dhcp/
After=network-online.target
Wants=network-online.target
ConditionPathIsExecutable=/var/lib/rancher/k3s/data/current/bin/dhcp

[Service]
Type=simple
# Remove any stale socket before start
ExecStartPre=/usr/bin/rm -f /run/cni/dhcp.sock
# Adjust path to the installed CNI dhcp binary if different
ExecStart=/var/lib/rancher/k3s/data/current/bin/dhcp daemon -socketpath /run/cni/dhcp.sock -broadcast
Restart=on-failure
RestartSec=2
User=root
Group=root

# Capabilities required for DHCP client (raw packets, low port bind)
# and netns operations
AmbientCapabilities=CAP_NET_RAW CAP_NET_BIND_SERVICE CAP_NET_ADMIN CAP_SYS_ADMIN
CapabilityBoundingSet=CAP_NET_RAW CAP_NET_BIND_SERVICE CAP_NET_ADMIN CAP_SYS_ADMIN
NoNewPrivileges=true

# Security hardening
ProtectSystem=strict
ProtectHome=true
PrivateTmp=true
ProtectProc=invisible
ProtectControlGroups=true
ProtectKernelTunables=true
ProtectKernelModules=true
ProtectKernelLogs=true
LockPersonality=true
RestrictSUIDSGID=true
RestrictNamespaces=false
RestrictRealtime=true
SystemCallFilter=@system-service setns
MemoryDenyWriteExecute=true

# Runtime directory management
RuntimeDirectory=cni
RuntimeDirectoryMode=0755

# Resource limits
LimitNOFILE=4096

[Install]
WantedBy=multi-user.target
```

Because of `ConditionPathIsExecutable`, the service quietly skips
starting if `dhcp` is missing from `data/current/bin`, for example after
a k3s upgrade.

### multus-shim in data/cni

`multus-shim` and `passthru` were copied into
`/var/lib/rancher/k3s/data/cni` on 2025-09-05. The chart doesn't manage
these copies. Without them containerd can't find `multus-shim`, and
**every** pod on the node fails with:

```text
failed to find plugin "multus-shim" in path [/var/lib/rancher/k3s/data/cni]
```

## Node status (2026-10-24)

| Node | `macvlan`/`dhcp`/`host-device` | `dhcp.service` | shim in `data/cni` | multus image |
| ---- | ------------------------------ | -------------- | ------------------ | ------------ |
| kube02 | yes | enabled, active | yes | `sha256:96dac83c...` |
| kube03 | yes | enabled, active | yes | `sha256:96dac83c...` |
| kube05 | yes | enabled, active | yes | `sha256:96dac83c...` |
| kube01 | no | not installed | **no**, so pods can't start | `sha256:24406387...` |

On kube02, kube03 and kube05 the shim in `data/cni` has the same
checksum as the one the chart installs into `data/current/bin`. kube01
is the dedicated etcd node, tainted `CriticalAddonsOnly`, so it never
runs `vpn-secure` pods and only needs the shim.

## Setting up a new node

1. Copy the shim where containerd looks, after the `kube-multus-ds` pod
   on the node has started (its init container writes the files):

   ```bash
   sudo install -m 755 /var/lib/rancher/k3s/data/current/bin/multus-shim /var/lib/rancher/k3s/data/cni/multus-shim
   sudo install -m 755 /var/lib/rancher/k3s/data/current/bin/passthru /var/lib/rancher/k3s/data/cni/passthru
   ```

2. Only on nodes that will run `vpn-secure` pods: put `macvlan`, `dhcp`
   and `host-device` from the CNI plugins release
   (<https://github.com/containernetworking/plugins/releases>, v1.8.0
   to match) into `/var/lib/rancher/k3s/data/current/bin`. Then install
   the `dhcp.service` unit above and enable it:

   ```bash
   sudo systemctl daemon-reload
   sudo systemctl enable --now dhcp.service
   ```

After every k3s upgrade, redo step 2 on those nodes, because
`data/current` points at a new directory, then restart `dhcp.service`.

## Known issues

- **Floating image tag.** `image.tag` is `snapshot-thick` with
  `pullPolicy: IfNotPresent`. Each node runs whatever the tag pointed to
  when it first pulled, which is why kube01's digest differs from the
  others. Pinning a release tag or digest would fix it.
- **Upgrade fragility.** The delegate plugins and `dhcp.service` depend
  on `data/current`, which moves on every k3s upgrade. Moving them to a
  directory that survives upgrades means changing `cni.binDir` and the
  unit together, on every node at once.
- **Unmanaged shim copy.** The `data/cni` shim isn't managed by the
  chart, so it doesn't update when the image does.
