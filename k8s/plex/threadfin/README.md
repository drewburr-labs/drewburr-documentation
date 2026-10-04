# Threadfin

Bridges the IPTV provider's M3U into Plex Live TV & DVR by emulating an
HDHomeRun tuner. Plex can't read M3U directly.

```
provider M3U -> Threadfin (plex-threadfin-http:34400) -> Plex Live TV & DVR
```

- Web UI: https://threadfin.drewburr.com (internal ingress only)
- Tuner URL for Plex: `http://plex-threadfin-http.plex.svc.cluster.local:34400`

## Provider facts (measured 2026-10-04, `../iptv-poc/`)

- **3 concurrent connections.** A 4th stream connects, then is cut within a
  second; existing streams are untouched. Every consumer of the account
  (Plex viewers, DVR recordings, any other app) draws from the same 3.
- Streams: MPEG-TS, H.264 High 720p60 + AAC stereo, ~3 Mbps. Plex can
  direct-stream this; no transcode needed for LAN clients.
- Stream auth is session-based: a stale downloaded playlist returns 401.
  Always give Threadfin the playlist **URL**, never a downloaded file.
- No EPG URL in the playlist. Only channels with a `tvg-id` (all of
  "USA Premium", ~1/4 of "US Sports") can be mapped to a real guide; event
  channels (`NFL 04: Bills vs Patriots (10.04 ...)`) have rotating names and
  no IDs, and don't fit Plex's guide model.

## Settings (web UI)

Settings live in `settings.json` on the `threadfin-config` PVC, including the
M3U URL (which embeds the provider credentials), so they are not in git.

| Setting | Value | Why |
|---|---|---|
| Playlist | provider M3U URL, tuners **3** | Matches the provider limit |
| Buffer | **Threadfin** | With no buffer (`-`) Threadfin hands Plex the provider URL directly, so the tuner limit isn't enforced and two viewers of one channel use two connections. Buffering shares one upstream per channel |
| Auto update | **off** | It downloads a binary at runtime; the read-only root FS blocks it anyway. Upgrade via `appVersion` |
| SSDP | off | Discovery doesn't cross pods; Plex adds the tuner by URL |
| Authentication | enable web auth | The UI displays the M3U URL |
| Filter | channel groups to expose | Plex caps a tuner at 480 channels; only map channels with guide data |

## Adding to Plex

1. Plex -> Settings -> Live TV & DVR -> Set up Plex DVR (requires Plex Pass).
2. "Don't see your HDHomeRun device?" -> enter the tuner URL above.
3. Guide: "Have an XMLTV guide on your server?" ->
   `http://plex-threadfin-http.plex.svc.cluster.local:34400/xmltv/threadfin.xml`
   (404s until channels are mapped in Threadfin; the file is generated then).
