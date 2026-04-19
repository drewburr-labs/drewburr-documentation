#!/bin/bash
set -eu

SHIM="/usr/lib/plexmediaserver/lib/libisoc23shim.so.0"

if [ -f "${SHIM}" ]; then
    export LD_PRELOAD="${SHIM}${LD_PRELOAD:+:${LD_PRELOAD}}"
    echo "[entrypoint] LD_PRELOAD=${LD_PRELOAD}"
else
    echo "[entrypoint] WARNING: ${SHIM} not found — HW transcoding will fail"
fi

exec /init "$@"
