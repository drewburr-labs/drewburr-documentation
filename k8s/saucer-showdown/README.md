# Saucer Showdown relay

Relay server for [Saucer Showdown](https://github.com/drewburr-labs/saucer-showdown#relay-server)
online play. Stateless, one replica, UDP only.

| Piece | Value |
|---|---|
| Image | `ghcr.io/drewburr-labs/saucer-showdown-relay` (public), `latest` with `imagePullPolicy: Always` |
| Service | `LoadBalancer`, MetalLB `192.168.4.68`, `udp/24680`, `externalTrafficPolicy: Local` |
| DNS | `saucer.drewburr.com` CNAME `ip.drewburr.com`, created by external-dns (cloudflare-service) |
| Metrics | `tcp/24681` (`/metrics`, `/healthz`) on ClusterIP `relay-metrics` only; scraped by ServiceMonitor `relay` |
| Router | UDM port forward **WAN udp/24680 -> 192.168.4.68:24680** (not in git; set by hand) |

`externalTrafficPolicy: Local` keeps real client addresses, which the relay's
per-address limit (20 wrong room codes per minute) depends on.

To pick up a new image, restart the pod (ArgoCD: Restart on the Deployment).
That only matters when `VERSION` in `relay/relay_protocol.gd` changes;
the relay never reads game messages.

## Check it

From a saucer-showdown checkout:

```sh
godot --headless --path . --script res://relay/relay_probe.gd -- saucer.drewburr.com
```

Opens a room, joins it, and passes a packet each way. The k8s probes hit
`/healthz` on the metrics port, which only shows the process is up; this
probe is the real end-to-end check.
