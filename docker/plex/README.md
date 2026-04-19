# Plex Battlemage HW Transcoding Shim

Custom Plex image published as `ghcr.io/drewburr-labs/plex:latest`. The
image adds a small ABI shim that lets Plex's bundled Battlemage-capable
iHD driver relocate inside the musl-based Plex Transcoder runtime. The
k8s deployment at `k8s/plex/plex/values.yaml` points at this image.

**Status (2026-04-19):** deployed; HW decode + HW encode confirmed working
on an Intel Arc B570 (Battlemage, `8086:e20c`, xe kernel driver) on
kernel 6.17.0-20-generic.

## The bug this works around

Plex `1.43.1.10611-1e34174b1` bundles a Battlemage-capable iHD driver at
`/config/Library/Application Support/Plex Media Server/Drivers/imd-a5431fbbff9ce9568f94ae21-linux-x86_64/dri/iHD_drv_video.so`
(dated 2026-04-16, `intel-media-driver 25.2.6`).

Plex Transcoder is **musl**-linked (`ld-musl-x86_64.so.1`) and loads
glibc-linked libraries via `libgcompat.so.0` as a shim. Plex's latest
rebuild updated the bundled iHD driver (and its transitive deps like
the system `libstdc++.so.6`) to binaries compiled against glibc ≥2.38
headers, which emit references to symbols Plex's bundled
`libgcompat.so.0` does not export:

- C23 wrappers: `__isoc23_strtoul`, `__isoc23_strtol`, `__isoc23_strtoll`,
  `__isoc23_strtoull`, `__isoc23_fscanf`, `__isoc23_sscanf`
- FORTIFY wrappers: `__memcpy_chk`, `__memset_chk`, `__strcpy_chk`,
  `__snprintf_chk`, `__vsnprintf_chk`, `__vasprintf_chk`, `__printf_chk`,
  `__fprintf_chk`, `__sprintf_chk`, `__realpath_chk`, `__read_chk`,
  `__memmove_chk`, `__wmemcpy_chk`, `__wmemset_chk`, `__mbsnrtowcs_chk`,
  `__mbsrtowcs_chk`, `__open_2`, `__openat_2`, `__open64_2`, `__openat64_2`
- Recent libc additions: `arc4random`, `arc4random_buf`,
  `arc4random_uniform`, `getentropy`, `secure_getenv`
- `_Float128` numerics: `strfromf128`, `strtof128`
- Dynamic loader API: `_dl_find_object`

Without the shim, the musl loader refuses to relocate the iHD driver
and libva init fails with:

```text
libva: dlopen of .../iHD_drv_video.so failed:
  Error relocating .../iHD_drv_video.so: __isoc23_strtoul: symbol not found
Failed to initialise VAAPI connection: -1 (unknown libva error).
```

Filed upstream on the Plex forum:
<https://forums.plex.tv/t/bundled-ihd-driver-references-glibc-symbols-not-exported-by-libgcompat-vaapi-init-fails-on-arc-b570/938129>.
The workaround should be deleted the moment Plex rebuilds `libgcompat.so.0`
against a current glibc.

## How the shim works

`isoc23_shim.c` exports each missing symbol and forwards it to the
non-FORTIFY / non-C23 equivalent. `Dockerfile` builds it with `gcc:14`
against glibc (not musl — it needs to run inside Plex's glibc-based
container alongside the musl transcoder), drops the `.so` into
`/usr/lib/plexmediaserver/lib/libisoc23shim.so.0`, and `entrypoint.sh`
wraps Plex's `/init` with `LD_PRELOAD` set so the driver's undefined
refs resolve against the shim before falling through to
`libgcompat.so.0`.

FORTIFY wrappers drop the bounds argument and forward to the plain
function — the runtime bounds-check becomes a no-op. Safe for the
callers we care about (driver init, locale parsing); not a drop-in for
code that genuinely relies on `__*_chk` for overflow enforcement.
`arc4random*` and `getentropy` are backed by `/dev/urandom`.
`strfromf128` is stubbed to empty-string, `strtof128` forwards to
`strtold` (cast through `__float128` so the x86_64 ABI matches the real
symbol). `_dl_find_object` returns `-1` so libgcc\_s falls back to
`dl_iterate_phdr` for unwinding.

### Gotcha: glibc 2.38+ self-redirects plain strto\*() to the C23 name

The most subtle bug in this shim is that with `gcc:14` + glibc 2.38+,
simply calling `strtoul(...)` inside the shim does **not** call the
plain symbol. The header declares:

```c
extern unsigned long strtoul (...) __asm__("__isoc23_strtoul");
```

…via `__REDIRECT_NTH` whenever `_GNU_SOURCE` (or any feature-test macro
that pulls in C2x/C23 support) is set. The compiler emits the call as
a reference to `__isoc23_strtoul` — which is the exact symbol the shim
exports. Under `LD_PRELOAD` the resolved target is our own function,
so the forwarding path becomes:

```text
__isoc23_strtoul  →  our shim  →  "strtoul"  →  __isoc23_strtoul  →  …
```

…infinite recursion, 99% CPU. Bash hung in `40-plex-first-run` on the
first preferences-file parse the first time we deployed.

Fix (already applied): reach the pre-C23 symbol via an explicit `asm()`
label on a renamed extern prototype, the same trick used for the
scanf family:

```c
extern unsigned long plain_strtoul(const char *, char **, int)
    __asm__("strtoul");

unsigned long __isoc23_strtoul(const char *nptr, char **endptr, int base) {
    return plain_strtoul(nptr, endptr, base);
}
```

When auditing the shim after a Plex rebuild, verify no new wrapper has
slipped back into the same pattern. `objdump -d libisoc23shim.so.0`
should show each `__isoc23_*` jumping to the plain symbol's PLT slot,
not back to its own.

## Deployment dependencies

### 1. `LD_PRELOAD` set by `entrypoint.sh`

The wrapper exports
`LD_PRELOAD=/usr/lib/plexmediaserver/lib/libisoc23shim.so.0` before
`exec /init`. The shim is glibc-linked; it works because Plex's musl
loader + libgcompat pick it up during the driver `dlopen`.

### 2. AppArmor Unconfined on the plex container

`cri-containerd`'s default AppArmor profile denies DRM ioctls on the
xe driver — `DRM_IOCTL_VERSION` returns `ECANCELED` and libva can't
even open the device. The helm values at `k8s/plex/plex/values.yaml`
set:

```yaml
securityContext:
  appArmorProfile:
    type: Unconfined
```

only on the plex container. The `mkdir` initContainer keeps the
default profile.

### 3. Env var conventions

The image is based on `plexinc/pms-docker:latest`, not linuxserver,
so env vars follow the plexinc convention: `PLEX_UID` / `PLEX_GID`
(not `PUID` / `PGID`), and `CHANGE_CONFIG_DIR_OWNERSHIP: 'false'` to
avoid chowning the 80 Gi config volume on every start (`fsGroup: 1001`
handles ownership).

## Build pipeline

`.github/workflows/docker-plex.yml` builds on every push to `main`
that touches `docker/plex/**` and publishes `ghcr.io/drewburr-labs/plex:latest`.

## Operational notes

- **Do not `rmmod` / unbind the xe driver to recover from a hung GPU.**
  On Battlemage with kernel 6.17.0-20, the driver's `.remove()` path
  deadlocks against a hung GT and takes the node offline — recovery
  requires a cold power cycle. See
  [`incidents/kube05-xe-unbind-lockup.md`](../../incidents/kube05-xe-unbind-lockup.md)
  for the full write-up. Use drain + reboot instead.

- **When Plex ships a new Transcoder build**, re-audit the shim. Run
  `nm -D --undefined` against the live `iHD_drv_video.so` and
  `libstdc++.so.6` inside the running container, diff against what
  musl + libgcompat + the shim provide, and add any new unresolved
  symbols. The list above was enumerated iteratively — a silent new
  dependency would present as "libva init fails" after an image
  bump, not as a relocation error at load time.

- **Delete this shim when upstream fixes libgcompat.** Revisit after
  each Plex beta; monitor the forum thread linked above.

## Risks / maintenance

- Brittle: any Plex rebuild that pulls in a newer `libstdc++` or iHD
  may introduce new unresolved symbols.
- FORTIFY bypass is acceptable here but not stealthy — if Plex ever
  relies on `__memcpy_chk` for intentional runtime bounds enforcement,
  those checks become no-ops.
- AppArmor Unconfined is a security posture downgrade from the default
  profile. The plex container already runs with broad device access
  (`/dev/dri/*`, large storage mounts) so the marginal risk is small
  in this environment, but it should be noted for anyone copying this
  setup into a more security-sensitive context.
