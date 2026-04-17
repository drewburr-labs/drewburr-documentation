#!/bin/bash

SYSTEM_IHD="/usr/lib/x86_64-linux-gnu/dri/iHD_drv_video.so"
PLEX_CONFIG_DIR="${PLEX_MEDIA_SERVER_APPLICATION_SUPPORT_DIR:-/config/Library/Application Support/Plex Media Server}"
PLEX_CACHE_DRI="${PLEX_CONFIG_DIR}/Cache/va-dri-linux-x86_64"

if [ -f "${SYSTEM_IHD}" ]; then
    echo "[entrypoint] Injecting system intel-media-driver into Plex driver cache"
    mkdir -p "${PLEX_CACHE_DRI}"
    cp "${SYSTEM_IHD}" "${PLEX_CACHE_DRI}/iHD_drv_video.so"

    # Replace any already-downloaded driver bundles under the Drivers dir
    find "${PLEX_CONFIG_DIR}/Drivers" -name "iHD_drv_video.so" \
        -exec cp "${SYSTEM_IHD}" {} \; 2>/dev/null || true
else
    echo "[entrypoint] WARNING: ${SYSTEM_IHD} not found — hardware transcoding may not work"
fi

exec /init "$@"
