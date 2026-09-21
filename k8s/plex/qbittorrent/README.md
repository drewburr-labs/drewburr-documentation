# qBittorrent

Torrent client for the Plex stack, running as `plex/plex-qbittorrent-0`
(and a second instance, `qbittorrent-alt`, with an identical setup). All
peer traffic leaves through a dedicated VPN tunnel with a kill switch, and
the client is reachable from the internet through a port forwarded across
that tunnel.

Web UI: <https://qbittorrent.drewburr.com> (internal ingress, VueTorrent).

This document records how the pieces fit together and how to verify each
one, because the failure modes are silent and easy to misattribute.
Addresses are deliberately left out; every one of them is discoverable
with the commands under [Verification](#verification).

## Architecture

```
internet peer
    |
    v
VPN server (self-hosted WireGuard, public IP)
    |  DNAT <public-ip>:<port> -> <wg-client-ip>:<port>
    v  WireGuard tunnel
UDM Pro Max, VPN client interface (wgclt*)
    |  Dest NAT <wg-client-ip>:<port> -> <pod-vlan6-ip>:<port>
    |  Firewall allow External -> Tunnel, <pod-vlan6-ip>:<port>
    v  VLAN 6 "VPN Tunnel - Secure"
pod net1 (Multus macvlan, DHCP)  ---- qBittorrent bound to net1
```

Outbound: the pod's default route is via its `net1` macvlan interface on
VLAN 6. A UniFi policy route sends everything from that network out the
VPN client with the kill switch enabled, so if the tunnel drops the
traffic is blackholed rather than leaking over the WAN.

Inbound: the WireGuard server forwards the listen port down the tunnel to
the UDM's tunnel address, and the UDM forwards it on to the pod.

### Pieces and where they live

| Piece | Where | Notes |
|---|---|---|
| Pod network attachment | `k8s/multus-config/nad.yaml` (`vpn-secure`) | macvlan on `ens19`, bridge mode, DHCP. Pod gets a fixed MAC via the `k8s.v1.cni.cncf.io/networks` annotation in `values.yaml`. |
| qBittorrent interface binding | qBittorrent options, Advanced | `Session\Interface=net1`. Nothing else should be bound. |
| Listen port | qBittorrent options, Connection | Must match the port forwarded on both the VPN server and the UDM. UPnP / NAT-PMP is useless inside the tunnel; leave it off. |
| Policy route | UniFi, Settings, Routing, Policy Based Routes | Source: the VLAN 6 network. Interface: the VPN client. Kill Switch: on. |
| VPN server port forward | WireGuard server, `iptables -t nat` | Two `PREROUTING` DNAT rules (tcp and udp) for the port, targeting the UDM's tunnel address. `net.ipv4.ip_forward=1`. |
| UDM port forward | UniFi, Settings, Routing, NAT | Type **Dest. NAT**, interface = the VPN client, destination = the UDM's tunnel address + port, translated = pod VLAN 6 address + port, TCP/UDP, source Any. The regular Port Forwarding dialog only offers physical WANs and cannot do this. |
| UDM firewall allow | UniFi, Policy Engine, Firewall | Allow, source zone External, destination zone Tunnel, destination = pod address + port, TCP/UDP. Custom NAT rules do not get an automatic allow. |
| DHCP reservation | UniFi, VLAN 6 network, the pod's MAC | Required. The NAT rule and firewall policy target the pod's address; a lease change silently breaks inbound. |
| VueTorrent | `values.yaml` init container | See below. |

### VueTorrent init container

An Alpine init container runs before qBittorrent on every pod start. It
compares the installed `version.txt` in the config PVC against the latest
GitHub release and downloads only on a mismatch. Every step falls through
on failure so a GitHub outage never blocks the pod. The init container
logs both versions on every start:

```bash
kubectl logs -n plex plex-qbittorrent-0 -c vuetorrent-install | tail -3
```

qBittorrent is pointed at it with `WebUI\AlternativeUIEnabled=true` and
`WebUI\RootFolder=/config/vuetorrent`. Updates only happen on pod
restart; there is no scheduled updater.

## UniFi gotchas that affect this setup

These were all discovered the hard way on 2026-09-20 and are the first
things to suspect if peers stop connecting.

### Threat Management reputation lists are global

Under CyberSecure, Threat Management, the categories **TOR** (in Peer to
Peer and Dark Web) and **Compromised Hosts / Malicious Hosts** (in Botnets
and Threat Intelligence) are not IPS signatures. Each loads an IP list
into an ipset (`TOR`, `ALIEN`) and installs a plain drop at the top of the
`FORWARD` chain matching on source address:

```
-A FORWARD -j TOR
-A TOR -m set --match-set TOR src -j TORLOGNDROP
```

There is no network condition. The **Selected Networks** list and the
IPS on/off switch do not affect it. Torrent peers land on these lists
constantly (seedbox hosts run Tor relays; shared VPN exits get reported),
and the drop hits the *return* packet, so the pod sends a SYN, the peer
answers, and the UDM eats the SYN-ACK. The flow log shows this as
`Block` with **no policy name** and Risk Low. No zone-policy counter
increments.

Both categories are off. Turning either back on will degrade VLAN 6
peers on every network, with no per-network exemption available.

### Region blocking is WAN-scoped (safe)

Region Blocking only inspects packets arriving on the physical WAN
interfaces:

```
-A UBIOS_FWD_IN_GEOIP_PRECHK -i eth9 -j UBIOS_IN_GEOIP
-A UBIOS_FWD_IN_GEOIP_PRECHK -i eth8 -j UBIOS_IN_GEOIP
```

Traffic arriving on the VPN client interface is never checked, so
region blocking can stay on without affecting inbound peers.

### The flow log lies about unanswered flows

A flow that simply never gets a reply (dead peer, peer that refuses VPN
ranges) is also logged as `Block`. Confirm with a gateway capture before
chasing it. A real UDM drop shows the reply arriving on `wgclt*` and never
leaving on `br6`; an unanswered flow shows only SYNs leaving `wgclt*`.

### Sessions die on pod restart

qBittorrent keeps WebUI sessions in memory. After any pod restart an
open VueTorrent tab shows all zeros, including free disk space, instead
of redirecting to login. Hard reload and log in again.

## Verification

Run top to bottom when something looks wrong. Each step isolates one
hop. `POD` is the pod name, `VIP` the VPN public IP, `PORT` the listen
port; look them up rather than hard-coding.

**1. Pod egress goes through the VPN.**

```bash
kubectl exec -n plex POD -c qbittorrent -- curl -s --interface net1 https://ifconfig.me
```
Must print the VPN server's public IP, not the home WAN.

**2. Pod can reach arbitrary ports through the tunnel.**

```bash
kubectl exec -n plex POD -c qbittorrent -- sh -c \
  'for p in 443 6881 51413; do curl -s --max-time 6 --interface net1 -o /dev/null -w "$p %{http_code}\n" http://portquiz.net:$p/; done'
```
All should print `200`. A failure here is routing or the kill switch,
not peers.

**3. Inbound port is open (run from outside the LAN, or from any host
that is not the UDM's own WAN address).**

```bash
nc -zv -w5 VIP PORT
```
- `Connection refused` immediately: the packet reached the far side of
  the chain and hit a host with nothing listening. If the VPN server's
  DNAT exists, this is the UDM answering because its Dest NAT rule is
  missing or bound to the wrong interface.
- Timeout: the VPN server's DNAT is missing, or the firewall allow on the
  UDM is missing.
- Success: TCP is forwarded end to end.

Testing from a host behind the same UDM gives false failures because the
source IP matches the WireGuard endpoint. Use a phone on cellular or the
gateway capture below instead.

**4. UDP is forwarded (gateway capture).** On the UDM:

```bash
timeout 60 tcpdump -ni any udp port PORT -c 10
```
With the port open, real peers show up within seconds arriving on
`wgclt*` and leaving on `br6` with the destination rewritten to the pod.

**5. Check the NAT chain on both ends.**

```bash
# VPN server
iptables-save -t nat | grep PORT
# UDM
iptables-save -t nat | grep -E 'DNAT.*PORT'
```
The UDM lines must carry `-i wgclt*`. Lines matching
`UBIOS_KEY_ADDRv4_eth8/eth9` are the physical-WAN port forward and do
nothing for the tunnel.

**6. Reputation lists are not loaded.** On the UDM:

```bash
iptables-save | grep -wE 'TOR|ALIEN'
ipset list -n | grep -E '^(TOR|ALIEN)$'
```
Both must print nothing.

**7. Is a specific peer being dropped by the UDM, or just unreachable?**
On the UDM, then trigger a connect from the pod:

```bash
timeout 60 tcpdump -ni any host PEER_IP -c 30
```

```bash
kubectl exec -n plex POD -c qbittorrent -- python3 -c \
  'import socket; s=socket.socket(); s.settimeout(8); s.connect(("PEER_IP", PEER_PORT))'
```
SYN-ACK arrives on `wgclt*` but never leaves on `br6`: something on the
UDM is dropping it; check `ipset test SETNAME PEER_IP` across
`ipset list -n`. No SYN-ACK at all: the peer or the VPN exit is the
problem, and the UDM is only logging the unanswered flow.

## Reading the peer columns

Peers and Seeds columns are `connected / known`. For a seeder,
connected seeds is always `0` because seed-to-seed connections are
dropped by design. Connected peers is a share of the leechers, and on
seed-heavy swarms that share is small even when everything is working.
The health signal is aggregate upload rate and ratios climbing, not
per-torrent counts. Sort by Peers descending: recent releases should
show double-digit connected peers.

## History

- 2026-09-20: Diagnosed silent peer drops to the global TOR and ALIEN
  ipsets and turned those categories off. Replaced the WAN-bound port
  forward with a Dest NAT on the VPN client plus a firewall allow;
  inbound TCP and UDP confirmed with a gateway capture. VueTorrent init
  container changed from install-once to version-compare.
