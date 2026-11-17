#!/usr/bin/env python3
"""Generate files/relay-dashboard.json (Grafana dashboard for the game relay).

Run from k8s/game-relay:  python3 files/gen-dashboard.py files/relay-dashboard.json
Edit this, not the JSON.
"""
import json
import sys

DS = {"type": "prometheus", "uid": "${datasource}"}
SEL = 'job="relay-metrics", namespace="game-relay"'
G = f'{SEL}, game=~"$game"'

panels = []
_id = [0]
_y = [0]


def nid():
    _id[0] += 1
    return _id[0]


def row(title):
    panels.append({"type": "row", "title": title, "id": nid(), "collapsed": False,
                   "gridPos": {"h": 1, "w": 24, "x": 0, "y": _y[0]}, "panels": []})
    _y[0] += 1


def target(expr, legend="", ref="A", instant=False):
    t = {"datasource": DS, "expr": expr, "legendFormat": legend or "__auto", "refId": ref,
         "range": not instant, "instant": instant}
    return t


def stat(title, exprs, x, w, unit="none", desc="", decimals=None, thresholds=None,
         mappings=None, color_mode="value", h=4):
    steps = thresholds or [{"color": "text", "value": None}]
    p = {
        "type": "stat", "title": title, "description": desc, "id": nid(), "datasource": DS,
        "gridPos": {"h": h, "w": w, "x": x, "y": _y[0]},
        "targets": [target(e, l, chr(65 + i)) for i, (e, l) in enumerate(exprs)],
        "fieldConfig": {"defaults": {"unit": unit, "mappings": mappings or [],
                                     "thresholds": {"mode": "absolute", "steps": steps},
                                     "color": {"mode": "thresholds"}}, "overrides": []},
        "options": {"reduceOptions": {"calcs": ["lastNotNull"], "fields": "", "values": False},
                    "colorMode": color_mode, "graphMode": "none", "textMode": "auto",
                    "justifyMode": "auto", "orientation": "auto", "wideLayout": True,
                    "showPercentChange": False},
    }
    if decimals is not None:
        p["fieldConfig"]["defaults"]["decimals"] = decimals
    panels.append(p)


def ts(title, exprs, x, w, unit="none", desc="", h=8, stack=False, min0=True, overrides=None,
       draw="line", fill=10, max_=None, interp="linear", interval=None, calcs=None,
       decimals=None):
    custom = {"drawStyle": draw, "lineWidth": 1, "fillOpacity": fill, "showPoints": "never",
              "spanNulls": False, "lineInterpolation": interp, "gradientMode": "none",
              "axisPlacement": "auto", "axisSoftMin": 0 if min0 else None,
              "stacking": {"mode": "normal" if stack else "none", "group": "A"},
              "thresholdsStyle": {"mode": "off"}}
    custom = {k: v for k, v in custom.items() if v is not None}
    defaults = {"unit": unit, "custom": custom, "color": {"mode": "palette-classic"},
                "thresholds": {"mode": "absolute", "steps": [{"color": "green", "value": None}]}}
    if max_ is not None:
        defaults["max"] = max_
    if decimals is not None:
        defaults["decimals"] = decimals
    if draw == "bars":
        custom["barAlignment"] = -1  # a bar covers the interval that ends at its timestamp
    panel = {
        "type": "timeseries", "title": title, "description": desc, "id": nid(), "datasource": DS,
        "gridPos": {"h": h, "w": w, "x": x, "y": _y[0]},
        "targets": [target(e, l, chr(65 + i)) for i, (e, l) in enumerate(exprs)],
        "fieldConfig": {"defaults": defaults, "overrides": overrides or []},
        "options": {"legend": {"displayMode": "list", "placement": "bottom", "showLegend": True,
                               "calcs": calcs or []},
                    "tooltip": {"mode": "multi", "sort": "desc"}},
    }
    if interval:
        panel["interval"] = interval
    panels.append(panel)


def nl(h):
    _y[0] += h


# Scrape interval of the ServiceMonitor (values.yaml serviceMonitor.interval).
SCRAPE = "30s"


def events(metric, sel, by="", window="$__interval"):
    """Exact number of counter increments in `window`.

    rate()/increase() are wrong for this relay's rare events: they extrapolate one
    event into "40 per hour", and they never count a series' first value. A game's
    series is created by its first room, already at 1, so that room was dropped.
    Instead, subtract the value one scrape earlier at every scrape and add those
    up; a series that didn't exist a scrape earlier counts from 0. The steps
    telescope, so the total is exact. A relay restart is a new pod, so new series:
    counters never reset within one.
    """
    x = f"{metric}{{{sel}}}"
    step = f"({x} - ({x} offset {SCRAPE} or {x} * 0))"
    agg = f"sum by ({by})" if by else "sum"
    return f"{agg} (sum_over_time({step}[{window}:{SCRAPE}]))"


def q(quant, metric, by="le", sel=G, window="$__rate_interval"):
    return (f"histogram_quantile({quant}, sum by ({by}) "
            f"(rate({metric}_bucket{{{sel}}}[{window}])))")


# ---------------------------------------------------------------- Now
row("Now")
stat("Up", [(f"up{{{SEL}}}", "")], 0, 3, desc="Prometheus can scrape the relay's metrics port.",
     mappings=[{"type": "value", "options": {"0": {"text": "DOWN", "color": "red"},
                                             "1": {"text": "UP", "color": "green"}}}],
     thresholds=[{"color": "red", "value": None}, {"color": "green", "value": 1}],
     color_mode="background")
stat("Players (machines)", [(f"sum(relay_room_peers{{{G}}}) or vector(0)", "")], 3, 3,
     desc="Machines in open rooms, hosts included. Couch players on one machine count once.")
stat("Rooms open", [(f"sum(relay_rooms{{{G}}}) or vector(0)", "")], 6, 3)
stat("Seats filled", [(f"sum(relay_room_peers{{{G}}}) / sum(relay_room_seats{{{G}}})", "")],
     9, 3, unit="percentunit", decimals=0,
     desc="Machines in rooms / machines the open rooms have room for. Shows 'no rooms' when none are open.")
panels[-1]["fieldConfig"]["defaults"]["noValue"] = "no rooms"
stat("Connections", [(f"relay_connections{{{SEL}}}", "")], 12, 3,
     desc="Open connections, in a room or not.")
stat("Rooms hosted (range)",
     [(events("relay_rooms_opened_total", G, window="$__range") + " or vector(0)", "")], 15, 3,
     decimals=0, desc="Rooms opened over the dashboard's time range. Includes relay-probe checks "
     "unless filtered out with the game variable.")
stat("Uptime", [(f"time() - process_start_time_seconds{{{SEL}}}", "")], 18, 3, unit="s",
     desc="Since the relay process started. Every counter resets on restart.")
stat("Protocol", [(f"max by (protocol) (relay_info{{{SEL}}})", "v{{protocol}}")], 21, 3,
     desc="Relay protocol version. Game builds speaking a different version are refused "
     "(reason=outdated).")
panels[-1]["options"]["textMode"] = "name"
nl(4)

# ---------------------------------------------------------------- Activity
row("Activity")
PEAK = dict(stack=True, interp="stepAfter", fill=30, interval="1m", decimals=0,
            calcs=["max"])
ts("Players by game (peak)",
   [(f"sum by (game) (max_over_time(relay_room_peers{{{G}}}[$__interval]))", "{{game}}")],
   0, 8, desc="Most machines in open rooms at any scrape in each interval, hosts included. "
   "Rooms shorter than a scrape (30 s) can be missed; the counts on the right are exact.",
   **PEAK)
ts("Rooms by game (peak)",
   [(f"sum by (game) (max_over_time(relay_rooms{{{G}}}[$__interval]))", "{{game}}")],
   8, 8, desc="Most rooms open at any scrape in each interval.", **PEAK)
COUNT = dict(draw="bars", fill=80, interval="1m", decimals=0, calcs=["sum"], unit="short")
ts("Rooms opened, closed & joins",
   [(events("relay_rooms_opened_total", G), "rooms opened"),
    (events("relay_rooms_closed_total", G), "rooms closed"),
    (events("relay_room_joins_total", G), "joins")],
   16, 8, desc="Exact count in each bar's interval (zoom out and bars widen). Legend = total "
   "for the time range.", **COUNT)
nl(8)
ts("Capacity used",
   [(f"sum(relay_rooms{{{SEL}}}) / max(relay_rooms_limit{{{SEL}}})", "rooms / limit"),
    (f"relay_connections{{{SEL}}} / relay_connections_limit{{{SEL}}}", "connections / limit")],
   0, 8, unit="percentunit", max_=1,
   desc="Against the relay's limits (400 rooms, 1024 connections). Across every game.")
ts("Refusals by reason",
   [(events("relay_refusals_total", SEL, by="reason"), "{{reason}}")], 8, 8, stack=True,
   **COUNT,
   desc="Exact count per bar interval; legend = total for the range. no_such_room = wrong code, outdated = old game build, too_many_tries = rate limited "
   "(20 wrong codes / address / min), room_full, relay_full, bad_request.")
ts("Connections opened & closed",
   [(events("relay_connections_opened_total", SEL), "opened"),
    (events("relay_connections_closed_total", SEL), "closed")],
   16, 8, desc="Exact count per bar interval; legend = total for the range. Open connections "
   "now are in the stat row.", **COUNT)
nl(8)

# ---------------------------------------------------------------- Connection quality
row("Connection quality")
ts("Round trip, relay to players",
   [(q(0.5, "relay_peer_round_trip_seconds"), "p50"),
    (q(0.95, "relay_peer_round_trip_seconds"), "p95"),
    (q(0.99, "relay_peer_round_trip_seconds"), "p99")], 0, 8, unit="s",
   desc="Sampled every 10 s for each machine in a room. A player's ping to the host is roughly "
   "theirs plus the host's. Gaps = nobody in a room.")
ts("Round trip p95 by game",
   [(q(0.95, "relay_peer_round_trip_seconds", by="le, game"), "{{game}}")], 8, 8, unit="s")
ts("Packet loss to players",
   [(q(0.5, "relay_peer_packet_loss_ratio"), "p50"),
    (q(0.95, "relay_peer_packet_loss_ratio"), "p95"),
    (f"sum(rate(relay_peer_packet_loss_ratio_sum{{{G}}}[$__rate_interval])) / "
     f"sum(rate(relay_peer_packet_loss_ratio_count{{{G}}}[$__rate_interval]))", "mean")],
   16, 8, unit="percentunit",
   desc="0 to 1 per machine, sampled with the round trip. Quantiles are coarse (bucketed).")
nl(8)

# ---------------------------------------------------------------- Sessions
row("Sessions")


def hq(quant, metric, window="1h"):
    """Quantile over closed rooms in the trailing window, counting every room exactly
    (the histogram's series appear at a game's first close, already at 1)."""
    return f"histogram_quantile({quant}, {events(metric + '_bucket', G, by='le', window=window)})"


def hmean(metric, window="1h"):
    return (f"{events(metric + '_sum', G, window=window)} / "
            f"{events(metric + '_count', G, window=window)}")


ts("Room length (closed rooms, trailing hour)",
   [(hq(0.5, "relay_room_duration_seconds"), "p50"),
    (hq(0.9, "relay_room_duration_seconds"), "p90"),
    (hmean("relay_room_duration_seconds"), "mean")],
   0, 12, unit="s", interval="1m",
   desc="How long rooms stayed open, over rooms that closed in the hour before each point.")
ts("Room size at peak (closed rooms, trailing hour)",
   [(hmean("relay_room_peak_peers"), "mean"),
    (hq(0.9, "relay_room_peak_peers"), "p90")],
   12, 12, unit="short", interval="1m",
   desc="Most machines each closed room had at once, host included, over rooms that closed "
   "in the hour before each point.")
nl(8)

# ---------------------------------------------------------------- Traffic
row("Traffic")
ts("Network throughput",
   [(f"rate(relay_network_received_bytes_total{{{SEL}}}[$__rate_interval])", "received"),
    (f"rate(relay_network_sent_bytes_total{{{SEL}}}[$__rate_interval])", "sent")],
   0, 8, unit="Bps", desc="On the wire, ENet overhead included.")
ts("Network packets",
   [(f"rate(relay_network_received_packets_total{{{SEL}}}[$__rate_interval])", "received"),
    (f"rate(relay_network_sent_packets_total{{{SEL}}}[$__rate_interval])", "sent"),
    (f"rate(relay_ignored_packets_total{{{SEL}}}[$__rate_interval])", "ignored")],
   8, 8, unit="pps",
   desc="ignored = empty, too big, unknown type, or data from outside a room.")
ts("Game payload by game",
   [(f"sum by (game) (rate(relay_game_bytes_total{{{G}}}[$__rate_interval]))", "{{game}}")],
   16, 8, unit="Bps", stack=True,
   desc="Game packets taken in to pass on (payload only).")
nl(8)

# ---------------------------------------------------------------- Process
row("Relay process")
ts("Added delay (poll duration)",
   [(f"histogram_quantile(0.5, sum by (le) (rate(relay_poll_duration_seconds_bucket{{{SEL}}}"
     f"[$__rate_interval])))", "p50"),
    (f"histogram_quantile(0.99, sum by (le) (rate(relay_poll_duration_seconds_bucket{{{SEL}}}"
     f"[$__rate_interval])))", "p99")],
   0, 8, unit="s", desc="Time per pass over waiting packets; packets wait while one runs, so "
   "this is the delay the relay adds. The loop also naps 1 ms (10 ms when idle) between passes.")
ts("CPU",
   [(f"rate(process_cpu_seconds_total{{{SEL}}}[$__rate_interval])", "process"),
    (f"rate(relay_poll_duration_seconds_sum{{{SEL}}}[$__rate_interval])", "relay work")],
   8, 8, unit="short", desc="Cores in use. relay work = time spent in poll passes.")
ts("Memory (RSS)", [(f"process_resident_memory_bytes{{{SEL}}}", "rss")], 16, 8, unit="bytes",
   desc="Pod memory limit is 256 MiB.")
nl(8)

dash = {
    "uid": "game-relay",
    "title": "Game relay",
    "description": "relay.drewburr.com:24680/udp. Provisioned from drewburr-documentation "
                   "k8s/game-relay (files/gen-dashboard.py); edit there, not in the UI.",
    "tags": ["game-relay", "relay"],
    "editable": True,
    "graphTooltip": 1,
    "refresh": "30s",
    "schemaVersion": 41,
    "time": {"from": "now-24h", "to": "now"},
    "timezone": "browser",
    "links": [{"title": "Relay README", "type": "link", "targetBlank": True, "icon": "doc",
               "url": "https://github.com/drewburr-labs/game-relay#metrics"}],
    "templating": {"list": [
        {"type": "datasource", "name": "datasource", "label": "Data source", "query": "prometheus",
         "current": {"text": "default", "value": "default"}, "hide": 0, "refresh": 1,
         "options": [], "regex": ""},
        {"type": "query", "name": "game", "label": "Game", "datasource": DS,
         "query": {"query": f"label_values(relay_rooms_opened_total{{{SEL}}}, game)",
                   "refId": "game"},
         "definition": f"label_values(relay_rooms_opened_total{{{SEL}}}, game)",
         "includeAll": True, "multi": True, "allValue": ".*",
         "current": {"text": ["All"], "value": ["$__all"]},
         "refresh": 2, "sort": 1, "hide": 0, "options": [], "regex": ""},
    ]},
    "annotations": {"list": [
        {"builtIn": 1, "datasource": {"type": "grafana", "uid": "-- Grafana --"}, "enable": True,
         "hide": True, "iconColor": "rgba(0, 211, 255, 1)", "name": "Annotations & Alerts",
         "type": "dashboard"},
        {"datasource": DS, "enable": True, "iconColor": "orange", "name": "Relay restarts",
         "expr": f"changes(process_start_time_seconds{{{SEL}}}[2m]) > 0",
         "step": "60s", "titleFormat": "Relay restarted (counters reset)"},
    ]},
    "panels": panels,
}

json.dump(dash, open(sys.argv[1], "w"), indent=2)
print(f"{len([p for p in panels if p['type'] != 'row'])} panels -> {sys.argv[1]}")
