# Books stack (calibre-web / shelfmark / bookshelf)

Self-serve ebook pipeline living in the plex namespace so it can reuse the
existing qbittorrent, sabnzbd, flare-bypasser, and plex-data infrastructure.

- **calibre-web** — Calibre-Web NextGen (community continuation of
  Calibre-Web-Automated). Family-facing library UI at
  <https://books.drewburr.com> (external ingress). Per-user accounts,
  send-to-kindle email, OPDS, auto-convert, auto-ingest.
- **shelfmark** — search/download UI at <https://shelfmark.drewburr.com>
  (external; `AUTH_METHOD=cwa` reuses calibre-web's user database, so family
  members log in with their books.drewburr.com account). Drops books into
  the shared ingest folder. Uses the existing flare-bypasser instead of its
  bundled SeleniumBase one. Pinned to calibre-web's node via required
  podAffinity — it mounts the RWO calibre-web-config PVC read-only for
  app.db.
- **bookshelf** — Readarr fork at <https://bookshelf.drewburr.com> (internal).
  Monitored-author automation via the existing download clients. `hardcover`
  image tag = Hardcover metadata; `softcover` = Goodreads.

All three run rootless (uid/gid 1001, `runAsNonRoot`), verified with
`podman run --user 1001:1001` on 2026-08-21. The original
crocodilestick/calibre-web-automated image cannot start non-root (s6
privilege-drop loop), which is why NextGen is used.

## Shared paths on plex-data

```text
/data/books/calibre-library   calibre library (calibre-web: /calibre-library)
/data/books/ingest            ingest drop (calibre-web + shelfmark: /cwa-book-ingest,
                              bookshelf root folder: /data/books/ingest)
```

The subtree is created by `mkdir` initContainers (same pattern as the plex
chart's mkdir init), running as 1001 since fsGroup does not chown NFS
volumes. calibre-web creates both dirs; shelfmark creates the ingest dir so
neither app depends on the other's sync order.

## Post-deploy wiring (one-time, in-app)

1. **calibre-web**: create the library at `/calibre-library`; set ingest dir
   `/cwa-book-ingest`; configure SMTP for send-to-kindle; create family user
   accounts (each user sets their own `@kindle.com` address and whitelists
   the sender address in their Amazon account).
2. **bookshelf**: add download clients `plex-qbittorrent-http:8080`
   (category `books`) and `plex-sabnzbd-http:8080` (category `books`); add
   indexers (Jackett Torznab feeds); set root folder `/data/books/ingest` so
   completed imports flow through calibre-web ingest. Note qbittorrent-alt
   also exists if the primary's VPN egress isn't wanted for books.
3. **qbittorrent/sabnzbd**: create the `books` categories with save paths
   under `/data/` so bookshelf can import without path mapping.
