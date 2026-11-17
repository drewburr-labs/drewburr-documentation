# Game relay

Room-code relay for online games, from
[drewburr-labs/game-relay](https://github.com/drewburr-labs/game-relay). Saucer
Showdown plays through it. Stateless, one replica, UDP only.

| Piece | Value |
|---|---|
| Image | `ghcr.io/drewburr-labs/game-relay` (public), `latest` with `imagePullPolicy: Always` |
| Service | `LoadBalancer` `relay`, MetalLB `192.168.4.68`, `udp/24680`, `externalTrafficPolicy: Local` |
| DNS | `relay.drewburr.com` and `saucer.drewburr.com`, both CNAME `ip.drewburr.com`, created by external-dns (cloudflare-service) |
| Metrics | `tcp/24681` (`/metrics`, `/healthz`) on ClusterIP `relay-metrics` only; ServiceMonitor `relay`, so Prometheus `job="relay-metrics"`, `namespace="game-relay"` |
| Dashboard | Grafana "Game relay" (uid `game-relay`). Edit `files/gen-dashboard.py`, then regenerate `files/relay-dashboard.json` |
| Router | UDM port forward **WAN udp/24680 -> 192.168.4.68:24680** (not in git; set by hand) |

`externalTrafficPolicy: Local` keeps real client addresses, which the relay's
per-address limit (20 wrong room codes per minute) depends on.

**`saucer.drewburr.com` is still needed.** `HOST_NAME` in `relay_protocol.gd`
(game-relay, and Saucer Showdown's copy in `relay/`) is `saucer.drewburr.com`,
so shipped game builds connect there. Remove it from `service.hostnames` only
after games use `relay.drewburr.com`. external-dns runs `upsert-only`, so
removing it here won't delete the Cloudflare record; delete that by hand.

To pick up a new image, restart the pod (ArgoCD: Restart on the Deployment).
That only matters when `VERSION` in `relay_protocol.gd` changes (clients with
another version are refused); the relay never reads game messages.

## History

Replaced the `saucer-showdown` app (namespace `saucer-showdown`, image
`ghcr.io/drewburr-labs/saucer-showdown-relay`) when the relay moved out of the
Saucer Showdown repo. Same IP and port, so the port forward carried over.

## Check it

From a game-relay checkout:

```sh
godot --headless --path . --import
godot --headless --path . --script res://relay_probe.gd -- relay.drewburr.com
```

Opens a room, checks a different game id can't join it, joins, and passes a
packet each way. The k8s probes hit `/healthz` on the metrics port, which only
shows the process is up; this probe is the real end-to-end check.
