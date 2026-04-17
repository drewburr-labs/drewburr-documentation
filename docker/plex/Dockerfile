# Ubuntu 25.04 ships intel-media-driver 25.1.2 which supports Intel Battlemage (Arc B-series / xe driver).
# Ubuntu 24.04 (the plexinc base) only has 24.1.0, and Plex's own bundled driver is 24.1.5 — neither
# supports Battlemage. We pull the driver and its updated libigdgmm from 25.04 via multi-stage build.
FROM ubuntu:25.04 AS media-driver
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        intel-media-va-driver-non-free \
        libigdgmm12 && \
    rm -rf /var/lib/apt/lists/*

FROM plexinc/pms-docker:latest

RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        libva2 \
        libva-drm2 \
        libigdgmm12 && \
    rm -rf /var/lib/apt/lists/*

COPY --from=media-driver \
    /usr/lib/x86_64-linux-gnu/dri/iHD_drv_video.so \
    /usr/lib/x86_64-linux-gnu/dri/iHD_drv_video.so
COPY --from=media-driver \
    /usr/lib/x86_64-linux-gnu/libigdgmm.so.12.6.0 \
    /usr/lib/x86_64-linux-gnu/libigdgmm.so.12.6.0
RUN ln -sf /usr/lib/x86_64-linux-gnu/libigdgmm.so.12.6.0 \
    /usr/lib/x86_64-linux-gnu/libigdgmm.so.12

COPY entrypoint.sh /entrypoint-wrapper.sh
RUN chmod +x /entrypoint-wrapper.sh

ENTRYPOINT ["/entrypoint-wrapper.sh"]
