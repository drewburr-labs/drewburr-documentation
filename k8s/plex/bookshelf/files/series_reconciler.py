#!/usr/bin/env python3
"""Series reconciler for Bookshelf.

Bookshelf (Readarr lineage) has no persisted series-level monitoring: the
UI's series bookmark only bulk-toggles the books that exist at click time,
so future volumes arrive per the author's monitor-new-items setting. With
that set to "none" (to avoid the author firehose), new volumes of a wanted
series would sit unmonitored forever.

This reconciler closes the gap. Intent is declared by tagging an author in
Bookshelf with the kebab-case slug of a series title (e.g. tag
"dungeon-crawler-carl" on Matt Dinniman). Each run, for every tagged
series, any volume that is unmonitored, has no file, and has never been
grabbed or imported (history check — this is what distinguishes a NEW
volume from one already handled and unmonitored after calibre-web consumed
it) is monitored and searched.

Env: BOOKSHELF_URL, BOOKSHELF_API_KEY, DRY_RUN (optional, any value).
"""

import json
import os
import re
import sys
import urllib.request

BASE = os.environ["BOOKSHELF_URL"].rstrip("/")
KEY = os.environ["BOOKSHELF_API_KEY"]
DRY = bool(os.environ.get("DRY_RUN"))


def api(path, method="GET", body=None):
    req = urllib.request.Request(
        f"{BASE}/api/v1/{path}",
        method=method,
        headers={"X-Api-Key": KEY, "Content-Type": "application/json"},
        data=json.dumps(body).encode() if body is not None else None,
    )
    with urllib.request.urlopen(req, timeout=60) as r:
        raw = r.read()
    return json.loads(raw) if raw else None


def slug(text):
    return re.sub(r"-+", "-", re.sub(r"[^a-z0-9]+", "-", text.lower())).strip("-")


def series_name(book):
    # seriesTitle looks like "The Empyrean #3"; bare titles pass through.
    title = book.get("seriesTitle") or ""
    return re.sub(r"\s*#[\d.\-]+$", "", title).strip()


def was_handled(book_id):
    hist = api(f"history?bookId={book_id}&pageSize=50")
    events = hist.get("records", hist) if isinstance(hist, dict) else hist
    return any(
        e.get("eventType") in ("grabbed", "bookFileImported", "downloadImported")
        for e in events or []
    )


def main():
    tags = {t["id"]: t["label"] for t in api("tag")}
    to_search = []

    for author in api("author"):
        wanted = {tags[t] for t in author.get("tags", []) if t in tags}
        if not wanted:
            continue

        name = author["authorName"]
        # The series bookmark UI needs the author monitored; monitored alone
        # grabs nothing (monitorNewItems stays "none").
        if not author.get("monitored"):
            print(f"[{name}] setting author monitored=true (monitorNewItems=none)")
            if not DRY:
                author["monitored"] = True
                author["monitorNewItems"] = "none"
                api(f"author/{author['id']}", "PUT", author)

        for book in api(f"book?authorId={author['id']}"):
            sname = series_name(book)
            if not sname or slug(sname) not in wanted:
                continue
            if book.get("monitored"):
                continue
            stats = book.get("statistics") or {}
            if stats.get("bookFileCount", 0) > 0:
                continue
            if was_handled(book["id"]):
                continue
            print(f"[{name}] new volume in '{sname}': {book['title']}")
            to_search.append(book["id"])

    if to_search:
        print(f"monitoring + searching {len(to_search)} book(s)")
        if not DRY:
            api("book/monitor", "PUT", {"bookIds": to_search, "monitored": True})
            api("command", "POST", {"name": "BookSearch", "bookIds": to_search})
    else:
        print("nothing to do")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:  # noqa: BLE001 - surface any failure in job logs
        print(f"reconciler failed: {exc}", file=sys.stderr)
        sys.exit(1)
