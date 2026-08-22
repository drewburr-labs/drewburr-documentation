# Books stack (calibre-web / shelfmark / bookshelf)

Self-serve ebook pipeline living in the plex namespace so it can reuse the
existing qbittorrent, sabnzbd, flare-bypasser, and plex-data infrastructure.

- **calibre-web** — Calibre-Web NextGen (community continuation of
  Calibre-Web-Automated). Family-facing library UI at
  <https://books.drewburr.com> (external ingress). Per-user accounts,
  send-to-kindle email, OPDS, auto-convert, auto-ingest.
- **shelfmark** — search/request UI at <https://books.drewburr.com/request>
  (subpath on the books host via `URL_BASE`; `AUTH_METHOD=cwa` reuses
  calibre-web's user database, so family members log in with their
  books.drewburr.com account, and `CALIBRE_WEB_URL` gives it a "Library"
  button back to the main site). Drops books into the shared ingest folder.
  Uses the existing flare-bypasser instead of its bundled SeleniumBase one.
  Pinned to calibre-web's node via required podAffinity — it mounts the RWO
  calibre-web-config PVC read-only for app.db. Its ingress carries no tls
  block or DNS annotation: the calibre-web ingress owns cert and DNS for
  the host.
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
   `/cwa-book-ingest`; configure SMTP for send-to-kindle (see below); create
   family user accounts (each user sets their own `@kindle.com` address and
   whitelists the sender address in their Amazon account).
2. **bookshelf**: add download clients `plex-qbittorrent-http:8080`
   (category `books`) and `plex-sabnzbd-http:8080` (category `books`); add
   indexers (Jackett Torznab feeds); set root folder `/data/books/ingest` so
   completed imports flow through calibre-web ingest. Note qbittorrent-alt
   also exists if the primary's VPN egress isn't wanted for books.
3. **qbittorrent/sabnzbd**: create the `books` categories with save paths
   under `/data/` so bookshelf can import without path mapping.

## Send-to-kindle email (iCloud SMTP, configured 2026-08-22)

Settings live in calibre-web's admin UI (stored in app.db, not this repo):

```text
SMTP host   smtp.mail.me.com:587 STARTTLS
Login       drewburr@icloud.com          <- MUST be the @icloud.com address
Password    app-specific password         (account.apple.com, not the real one)
From        books@drewburr.com            <- custom-domain address on iCloud+
```

Hard-won quirks, in the order they bit:

- The login must be the **@icloud.com address**. The Apple ID primary (a
  gmail address) authenticates fine (no 5.7.8) but every send then fails
  with `5.1.1 Mailbox does not exist` regardless of From/recipient, because
  iCloud can't map a third-party login to the iCloud mailbox as a sender.
- A custom-domain alias as login fails outright with `5.7.8 authentication
  failed`.
- The From address must exist under **iCloud+ Custom Email Domain → Manage
  email addresses** (being listed in the Apple ID "Email & Phone Numbers"
  sign-in list is a different registry and not sufficient).

Per family member (the "email never arrives" checklist): calibre-web user
profile has their `@kindle.com` address, and `books@drewburr.com` is in
their Amazon **Approved Personal Document E-mail List** (amazon.com →
Content & Devices → Preferences) — Amazon silently drops mail otherwise.
