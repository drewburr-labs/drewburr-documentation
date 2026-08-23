# rreading-glasses, patched to stop array-batching its Hardcover requests.
#
# Upstream (blampe/rreading-glasses) sends Hasura-style array-batched GraphQL
# ([{query...}]) to Hardcover, which Hardcover's endpoint rejects with 400
# "Unexpected end of document" — breaking every search and metadata lookup.
# no-batch.patch swaps the batched client for the stock genqlient client
# (one bare-object request per query). Verified end-to-end against the live
# Hardcover API on 2026-08-22. See ../../k8s/plex/rreading-glasses/.
#
# Pinned to upstream commit a2939b6 ("decode search ids as int64", #549).
FROM golang:1.26 AS build
WORKDIR /src
RUN git clone https://github.com/blampe/rreading-glasses.git . \
    && git checkout a2939b625d91389d3f0a3e58cbc3bfa7ebb8390a
COPY no-batch.patch .
RUN git apply --verbose no-batch.patch
RUN CGO_ENABLED=0 go build -trimpath -o /main ./cmd/rghc

FROM gcr.io/distroless/static:nonroot
COPY --from=build /main /main
USER 65532:65532
EXPOSE 8788
ENTRYPOINT ["/main"]
