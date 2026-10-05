# Threadfin

Bridges the IPTV provider's M3U into Plex Live TV & DVR by emulating an
HDHomeRun tuner. Plex can't read M3U directly. The goal is live sports.

```
provider M3U -> Threadfin (plex-threadfin-http:34400) -> Plex Live TV & DVR
```

- Web UI: https://threadfin.drewburr.com (internal ingress only)
- Tuner URL for Plex: `http://plex-threadfin-http.plex.svc.cluster.local:34400`
- XMLTV URL for Plex: `http://plex-threadfin-http.plex.svc.cluster.local:34400/xmltv/threadfin.xml`

## Provider facts (measured 2026-10-04, `../iptv-poc/`)

- **3 concurrent connections.** A 4th stream connects, then is cut within a
  second; existing streams are untouched. Every consumer of the account
  (Plex viewers, DVR recordings, any other app) draws from the same 3.
- Streams: MPEG-TS, H.264 High 720p60 + AAC stereo, ~3 Mbps. Plex can
  direct-stream this; no transcode needed for LAN clients.
- Stream auth is session-based: a stale downloaded playlist returns 401.
  Always give Threadfin the playlist **URL**, never a downloaded file.
- Channel selection is also trimmed provider-side (1733 of ~11k channels).
- No EPG URL in the playlist.

## Settings (web UI)

There is no setup wizard in 1.2.37; everything is in the menus. Settings
live in `settings.json` on the `threadfin-config` PVC, including the M3U URL
(which embeds the provider credentials), so they are not in git.

**Playlist** (per-playlist in this version):

| Setting | Value | Why |
|---|---|---|
| M3U File | provider playlist URL | |
| Buffer | **FFmpeg** | With `-` Threadfin hands Plex the provider URL directly, so the tuner limit isn't enforced. There is no "Threadfin" buffer option in 1.2.37. Default ffmpeg options copy video, re-encode audio only |
| Tuner / Streams | **3** | Provider limit; only applies with a buffer |

**Settings:**

| Setting | Value | Why |
|---|---|---|
| Automatic update | off | Downloads a binary at runtime; read-only root FS blocks it anyway. Upgrade via `appVersion` |
| SSDP | off | Discovery doesn't cross pods; Plex adds the tuner by URL |
| Number of Tuners | **3** | This is what `discover.json` reports to Plex |
| EPG Source | XEPG | Threadfin builds the guide Plex reads |
| Schedule for updating | `0600,1000,1200,1500,1800` | Event channel names rotate during the day |
| Replace PPV channels title/desc | on | Live-event guide entries use the channel (matchup) name as title |

## Filters (Plex caps a tuner at 480 channels)

Filter matching is a case-insensitive substring test on the channel name;
Include/Exclude are comma-separated. Totals as of 2026-10-04: 389 channels.

| Filter | Group | Live Event | Include | Exclude | Ch. start |
|---|---|---|---|---|---|
| US Sports Networks | US Sports | no | `us:` | | 1000 |
| NFL Games | NFL | yes | `nfl 0`..`nfl 9`, `nfl \|`, `nfl  \|`, `nfl   \|` | | 2000 |
| NBA Games | NBA | yes | `nba 0`..`nba 9` | `2098,(nba` | 3000 |
| NHL Games | NHL | yes | `nhl \|`, `nhl 0`..`nhl 9` | | 4000 |

**Live Event groups** are the per-game slots (`NFL 04: Bills vs Patriots
(10.04 1:00PM ET)`). Threadfin keys these by stream URL instead of name, so
a slot stays the same Plex channel as the provider renames it, and
auto-maps them to the "PPV" dummy guide. Known 1.2.37 behaviour: the
start-time parser in `createLiveProgram` doesn't extract the time from the
name, so every event shows 06:00-23:59 today. The title is correct; the
time is not.

**Mapping:** live-event channels activate themselves. Non-live channels
(US Sports Networks) must be activated in Mapping -> Bulk Edit -> select all
inactive -> Active, XMLTV File "Threadfin Dummy", XMLTV Channel
`60_Minutes`. The bulk dialog pre-fills XMLTV Channel with the clicked
channel's tvg-id (e.g. `espn.us`), which is not a valid dummy value; set it
explicitly before Done.

## Adding to Plex

1. Plex -> Settings -> Live TV & DVR -> Set up Plex DVR (requires Plex Pass).
2. "Don't see your HDHomeRun device?" -> enter the tuner URL above.
3. "Have an XMLTV guide on your server?" -> the XMLTV URL above.
4. Channel mapping matches 1:1 by number. Saving sends every mapping in one
   query string (~16KB at 389 channels); `ingress-nginx-external` needs
   `large-client-header-buffers: "4 32k"` or the save fails with "There was
   a problem saving channel mappings".

After changing filters, rescan the tuner in Plex.
