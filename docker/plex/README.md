# Plex Battlemage HW Transcoding Shim (proposed)

Background for a rebuild of `docker/plex/` that makes Plex's bundled
Battlemage-capable iHD driver actually load inside the Plex container.
None of this is deployed today — the current `Dockerfile` + `entrypoint.sh`
target an earlier failure mode (Plex base lacked the driver entirely)
that Plex has since addressed upstream, exposing a different bug.

## Current state (Plex `1.43.1.10611-1e34174b1`, any Docker image)

- `plexinc/pms-docker:latest` → Ubuntu 24.04 base, glibc 2.39.
- Plex now bundles a Battlemage-capable iHD driver at
  `/config/Library/Application Support/Plex Media Server/Drivers/imd-a5431fbbff9ce9568f94ae21-linux-x86_64/dri/iHD_drv_video.so`
  (dated 2026-04-16, `intel-media-driver 25.2.6`).
- Every transcode still falls back to CPU. Logs show:

  ```
  Failed to initialise VAAPI connection: -1 (unknown libva error)
  Error relocating .../iHD_drv_video.so: __isoc23_strtoul: symbol not found
  TPU: hardware transcoding: enabled, but no hardware decode accelerator found
  ```

- Swapping to `lscr.io/linuxserver/plex:latest` does not help:
  linuxserver repackages Plex's official `.deb` so the transcoder binary
  and `libgcompat.so.0` are byte-identical (58688 bytes, mtime Apr 9).

## Root cause

Plex Transcoder is **musl**-linked (`ld-musl-x86_64.so.1`) and loads
glibc-linked libraries via `libgcompat.so.0` as a shim. Plex's latest
rebuild updated the bundled iHD driver (and its transitive deps like
the system `libstdc++.so.6`) to binaries compiled against glibc ≥2.38
headers, which emit references to:

- C23 wrappers: `__isoc23_strtoul`, `__isoc23_strtol`, `__isoc23_strtoll`,
  `__isoc23_strtoull`, `__isoc23_fscanf`, `__isoc23_sscanf`
- FORTIFY wrappers: `__memcpy_chk`, `__memset_chk`, `__strcpy_chk`,
  `__snprintf_chk`, `__vsnprintf_chk`, `__vasprintf_chk`, `__printf_chk`,
  `__fprintf_chk`, `__sprintf_chk`, `__realpath_chk`, `__read_chk`,
  `__memmove_chk`, `__wmemcpy_chk`, `__wmemset_chk`, `__mbsnrtowcs_chk`,
  `__mbsrtowcs_chk`, `__open_2`, `__openat_2`, `__open64_2`, `__openat64_2`
- Recent libc additions: `arc4random`, `arc4random_buf`, `arc4random_uniform`,
  `getentropy`, `secure_getenv`
- `_Float128` numerics: `strfromf128`, `strtof128`
- Dynamic loader API: `_dl_find_object`

Plex's own bundled `libgcompat.so.0` exports **zero** of these, so the
musl loader refuses to relocate the iHD driver and libva init fails
with `-1 (unknown libva error)`.

The upstream driver overlay the current `Dockerfile` does
(copying `intel-media-va-driver-non-free` from Ubuntu 25.04) does not
help: that driver has the same `__isoc23_*` references because it's
compiled against a newer glibc too.

## Proposed fix: ABI shim preloaded into Plex Transcoder

Build a small `.so` that exports each of the missing symbols and forwards
to the non-FORTIFY / non-C23 equivalents. Preload it via `LD_PRELOAD`
so musl's loader resolves the iHD driver's undefined refs against it
before falling through to `libgcompat.so.0`.

Prototype work verified this approach: a hand-rolled shim (live in the
test pod, reverted) successfully unblocked the VAAPI `dlopen` up through
the `_dl_find_object` layer. Convergence testing wasn't completed because
iteration against a shared pod isn't appropriate — further work should
be done against an offline copy of the binaries.

### Symbol signatures (forwarding stubs)

All wrappers drop the FORTIFY bounds parameter and forward to the plain
function. This discards FORTIFY's runtime bounds-check guarantee but is
safe for Plex's callers (Intel's driver parsing PCI IDs, locale init,
etc.).

For scanf-family stubs, the C23 header redirection forces use of
`asm()` labels to reference the plain symbol:

```c
extern int plain_vfscanf(FILE *, const char *, va_list) __asm__("vfscanf");
int __isoc23_fscanf(FILE *s, const char *f, ...) {
    va_list a; va_start(a,f);
    int r = plain_vfscanf(s, f, a);
    va_end(a); return r;
}
```

`strfromf128` / `strtof128` should also use `asm()` labels to avoid
touching `_Float128` in the C signature (not portable across all
toolchains); stub to empty-string and `strtold` respectively.

`_dl_find_object` returns `-1` (not found) — libgcc_s falls back to
the slower `dl_iterate_phdr` unwind path.

### Build pipeline

1. Produce the shim from a self-contained `isoc23_shim.c` compiled with
   `gcc -shared -fPIC -O2` against glibc (not musl — it needs to run
   inside Plex's glibc-based container alongside the musl transcoder).
2. Multi-stage Dockerfile:
   - Stage 1: `gcc:14` builds `libisoc23shim.so.0`.
   - Stage 2: `FROM plexinc/pms-docker:latest`, copy the shim into
     `/usr/lib/plexmediaserver/lib/`, wrap the entrypoint to export
     `LD_PRELOAD=/usr/lib/plexmediaserver/lib/libisoc23shim.so.0`.
3. Drop the Ubuntu 25.04 driver overlay — obsolete now that Plex
   ships its own Battlemage driver.
4. CI already publishes to `ghcr.io/drewburr-labs/plex:latest`;
   `k8s/plex/plex/values.yaml` points at `lscr.io/linuxserver/plex:latest`
   and needs to be updated to the GHCR image once the shim image is
   validated.

### Before converging

Run `nm -D --undefined` against the live `iHD_drv_video.so` and
`libstdc++.so.6` (copies extracted from the running container) and diff
against symbols provided by musl + Plex's libgcompat + this shim. The
list above was gathered iteratively; a full offline enumeration may
reveal more FORTIFY or locale symbols that weren't hit yet.

### Risks / maintenance

- Brittle: any Plex rebuild that pulls in a newer `libstdc++` or iHD may
  introduce new unresolved symbols. The shim needs re-auditing whenever
  Plex ships a transcoder update.
- FORTIFY bypass is acceptable here but not stealthy — if Plex ever
  relies on `__memcpy_chk` for intentional runtime bounds enforcement,
  those checks become no-ops.
- This workaround becomes unnecessary the moment Plex rebuilds
  `libgcompat.so.0` in their transcoder runtime. Revisit after each
  Plex beta release; the shim should be deleted, not maintained, as
  soon as upstream fixes the packaging.

## Filing with Plex

The fix belongs upstream. A report on the Plex forum lets support match
it to the existing Battlemage thread:

- **Category:** Plex Media Server → Hardware Transcoding (or post as a
  reply on the existing thread
  <https://forums.plex.tv/t/intel-arc-b570-hardware-transcoding-support-timeline-request/922599>
  if it's still open; otherwise open a new topic titled something like
  *"Plex 1.43.1.10611 — iHD driver references glibc symbols not exported
  by bundled libgcompat"*).
- **Include:**
  - Plex version: `1.43.1.10611-1e34174b1` (Docker, `plexinc/pms-docker:latest`,
    Ubuntu 24.04 / glibc 2.39).
  - GPU: Intel Arc B570 (Battlemage, PCI `8086:e20c`), xe kernel driver,
    `/dev/dri/renderD128` exposed to the container.
  - The exact relocation error from `Plex Media Server.log`:

    ```
    libva: dlopen of .../Drivers/imd-a5431fbbff9ce9568f94ae21-linux-x86_64/dri/iHD_drv_video.so failed:
      Error relocating .../iHD_drv_video.so: __isoc23_strtoul: symbol not found
    Failed to initialise VAAPI connection: -1 (unknown libva error).
    ```

  - The diagnostic:
    - `grep -aoE "__isoc23_[a-z_]+" .../libgcompat.so.0` → empty.
    - `grep -aoE "__isoc23_[a-z_]+" .../iHD_drv_video.so` → 6 matches
      (`strtoul`, `strtol`, `strtoll`, `strtoull`, `fscanf`, `sscanf`).
    - Same pattern for `arc4random`, `getentropy`, `__*_chk`, `strfromf128`,
      `strtof128`, `_dl_find_object` undefined in the transcoder runtime.
  - Request: rebuild `libgcompat.so.0` (or switch to a maintained fork)
    so it exports the C23 / FORTIFY / recent-glibc symbols the newly
    bundled iHD driver references. The bundled driver is fine; the
    musl compatibility shim is stale relative to the compiler used
    for the driver.
- **Do not include** your Plex token, server ID, or library contents
  in the ticket — the relocation error alone is sufficient reproduction.
