# Saucer Showdown relay

Relay server for [Saucer Showdown](https://github.com/drewburr-labs/saucer-showdown#relay-server)
online play. Stateless, one replica, UDP only.

| Piece | Value |
|---|---|
| Image | `ghcr.io/drewburr-labs/saucer-showdown-relay` (public), pinned `sha-<commit>` in `values.yaml` |
| Service | `LoadBalancer`, MetalLB `192.168.4.68`, `udp/24680`, `externalTrafficPolicy: Local` |
| DNS | `saucer.drewburr.com` CNAME `ip.drewburr.com`, created by external-dns (cloudflare-service) |
| Router | UDM port forward **WAN udp/24680 -> 192.168.4.68:24680** (not in git; set by hand) |

`externalTrafficPolicy: Local` keeps real client addresses, which the relay's
per-address limit (20 wrong room codes per minute) depends on.

Only redeploy (bump the tag) when `VERSION` in `scripts/net/relay_protocol.gd`
changes; the relay never reads game messages.

## Check it

From a saucer-showdown checkout:

```sh
godot --headless --path . --script tools/relay_probe.gd -- saucer.drewburr.com
```

Opens a room, joins it, and passes a packet each way. There are no k8s probes
(no TCP/HTTP endpoint), so this is the real health check.
