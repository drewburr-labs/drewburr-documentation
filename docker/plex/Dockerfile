# Plex 1.43.1.10611 now bundles a Battlemage-capable iHD driver, but the
# bundled libgcompat.so.0 is stale vs. the glibc the driver was compiled
# against — see README.md for the full analysis and symbol list. Build a
# small ABI shim and LD_PRELOAD it into the transcoder runtime.
FROM gcc:14 AS shim-builder
WORKDIR /build
COPY isoc23_shim.c .
RUN gcc -shared -fPIC -O2 -std=gnu11 -U_FORTIFY_SOURCE \
        -Wall -Wno-unused-parameter \
        -Wl,-soname,libisoc23shim.so.0 \
        -o libisoc23shim.so.0 isoc23_shim.c

FROM plexinc/pms-docker:latest

COPY --from=shim-builder /build/libisoc23shim.so.0 \
    /usr/lib/plexmediaserver/lib/libisoc23shim.so.0

COPY entrypoint.sh /entrypoint-wrapper.sh
RUN chmod +x /entrypoint-wrapper.sh

ENTRYPOINT ["/entrypoint-wrapper.sh"]
