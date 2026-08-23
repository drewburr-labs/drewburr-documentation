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
array it returns `400`. `no-batch.patch` makes `NewBatchedGraphQLClient`
return the stock genqlient client, which sends one bare-object request per
query. Verified end-to-end against the live Hardcover API — search returns
real results.

**Trade-off:** no request batching means more calls to Hardcover. Their free
tier is 60/min + burst 10, ample for a home library, and rreading-glasses
caches everything in Postgres so each author/work is fetched once. Heavy
first-time author fanouts can still transiently hit 429; they resolve on
retry as the cache warms.

## Maintenance

Pinned to upstream commit `a2939b6`. To bump: change the SHA in the
Dockerfile, re-run `git apply` locally against the new tree, refresh the
patch if the anchor moved, and push (the workflow rebuilds and pushes
`ghcr.io/drewburr-labs/rreading-glasses:latest`). If upstream fixes the
batching (track issues #574/#576), drop this image and point the chart back
at `blampe/rreading-glasses:hardcover`.
