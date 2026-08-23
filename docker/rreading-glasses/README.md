# rreading-glasses (patched)

Custom build of [blampe/rreading-glasses](https://github.com/blampe/rreading-glasses),
the Readarr-compatible metadata server, used by Bookshelf in the plex
namespace so book searches use our own Hardcover API quota instead of the
shared `hardcover.bookinfo.pro` proxy (which rate-limited us to death).

## Why the patch

Upstream's GraphQL client batches requests **Hasura-style**: it sends a JSON
array `[{query, variables}]` and expects an array response. Hardcover's
`api.hardcover.app/v1/graphql` does **not** accept array-batched requests —
it returns `400 Bad Request` / `"Unexpected end of document"` — so every
search and metadata lookup fails with a 400 the UI surfaces as
"unexpected token '<'… is not valid JSON".

Diagnosed by MITM-capturing the exact outbound request (2026-08-22): the
identical query as a bare object returns `200`; wrapped in a one-element
array it returns `400`. Hardcover also caps any request at **5 top-level
queries** (`403` over that, per their rate-limit docs), so upstream merging
up to 25 into one request is doubly incompatible.

`no-batch.patch` makes `NewBatchedGraphQLClient` return the stock genqlient
client (one bare-object query per request) **and** throttles it to
Hardcover's 60/min via the codebase's existing `throttledTransport`. The
throttle is essential, not cosmetic: without batching, a single search fans
out ~20-40 concurrent work/edition fetches, instantly blows Hardcover's
burst bucket, every sub-fetch `429`s, and the results all get dropped —
searches return `[]` with a misleading `200`. Verified end-to-end against
the live API: search returns real results with **zero 429s** across the
fanout.

**Trade-off:** throttling paces cold lookups at ~1/sec, so the first fetch
of a large author can take tens of seconds. Everything caches in Postgres,
so it's a one-time cost per work/author. Hardcover's per-minute limit is 60
regardless of plan, so 1/sec is the safe sustained ceiling; a Supporter
plan raises the daily limit (50k) and burst (15) but not the sustained
rate.

## Maintenance

Pinned to upstream commit `a2939b6`. To bump: change the SHA in the
Dockerfile, re-run `git apply` locally against the new tree, refresh the
patch if the anchor moved, and push (the workflow rebuilds and pushes
`ghcr.io/drewburr-labs/rreading-glasses:latest`). If upstream fixes the
batching (track issues #574/#576), drop this image and point the chart back
at `blampe/rreading-glasses:hardcover`.
