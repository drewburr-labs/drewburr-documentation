/*
 * ABI shim preloaded into Plex's musl transcoder to satisfy symbols the
 * rebuilt iHD driver (and its transitive libstdc++ references) expect
 * but Plex's bundled libgcompat.so.0 does not export. See ../README.md
 * for the full analysis.
 *
 * Build:
 *   gcc -shared -fPIC -O2 -std=gnu11 -U_FORTIFY_SOURCE \
 *       -Wl,-soname,libisoc23shim.so.0 -o libisoc23shim.so.0 isoc23_shim.c
 *
 * FORTIFY wrappers drop the bounds argument and forward to the plain
 * function — the runtime bounds check becomes a no-op. Safe for Plex's
 * callers (driver init, locale parsing) but not a drop-in for code that
 * genuinely relies on __*_chk for overflow enforcement.
 */

#define _GNU_SOURCE
#include <errno.h>
#include <fcntl.h>
#include <limits.h>
#include <stdarg.h>
#include <stddef.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/types.h>
#include <unistd.h>
#include <wchar.h>

/* ---- C23 strto* wrappers. glibc 2.38+ headers redirect plain strto*()
 *      calls to __isoc23_strto*, so we have to reach the pre-C23 symbol
 *      via asm() labels or we self-recurse through our own exports. ---- */
extern unsigned long plain_strtoul(const char *, char **, int)
    __asm__("strtoul");
extern long plain_strtol(const char *, char **, int)
    __asm__("strtol");
extern long long plain_strtoll(const char *, char **, int)
    __asm__("strtoll");
extern unsigned long long plain_strtoull(const char *, char **, int)
    __asm__("strtoull");

unsigned long __isoc23_strtoul(const char *nptr, char **endptr, int base) {
    return plain_strtoul(nptr, endptr, base);
}
long __isoc23_strtol(const char *nptr, char **endptr, int base) {
    return plain_strtol(nptr, endptr, base);
}
long long __isoc23_strtoll(const char *nptr, char **endptr, int base) {
    return plain_strtoll(nptr, endptr, base);
}
unsigned long long __isoc23_strtoull(const char *nptr, char **endptr, int base) {
    return plain_strtoull(nptr, endptr, base);
}

/* ---- C23 scanf wrappers: asm() labels reach the plain symbol past the
 *      C23 header's #define redirection to __isoc23_*. ---- */
extern int plain_vfscanf(FILE *, const char *, va_list) __asm__("vfscanf");
extern int plain_vsscanf(const char *, const char *, va_list) __asm__("vsscanf");

int __isoc23_fscanf(FILE *s, const char *f, ...) {
    va_list a; va_start(a, f);
    int r = plain_vfscanf(s, f, a);
    va_end(a);
    return r;
}
int __isoc23_sscanf(const char *s, const char *f, ...) {
    va_list a; va_start(a, f);
    int r = plain_vsscanf(s, f, a);
    va_end(a);
    return r;
}

/* ---- FORTIFY mem/str wrappers ---- */
void *__memcpy_chk(void *dest, const void *src, size_t len, size_t destlen) {
    (void)destlen; return memcpy(dest, src, len);
}
void *__memmove_chk(void *dest, const void *src, size_t len, size_t destlen) {
    (void)destlen; return memmove(dest, src, len);
}
void *__memset_chk(void *dest, int c, size_t len, size_t destlen) {
    (void)destlen; return memset(dest, c, len);
}
char *__strcpy_chk(char *dest, const char *src, size_t destlen) {
    (void)destlen; return strcpy(dest, src);
}
wchar_t *__wmemcpy_chk(wchar_t *dest, const wchar_t *src, size_t n, size_t destlen) {
    (void)destlen; return wmemcpy(dest, src, n);
}
wchar_t *__wmemset_chk(wchar_t *dest, wchar_t c, size_t n, size_t destlen) {
    (void)destlen; return wmemset(dest, c, n);
}

/* ---- FORTIFY printf family ---- */
int __snprintf_chk(char *s, size_t maxlen, int flag, size_t slen,
                   const char *fmt, ...) {
    (void)flag; (void)slen;
    va_list a; va_start(a, fmt);
    int r = vsnprintf(s, maxlen, fmt, a);
    va_end(a);
    return r;
}
int __vsnprintf_chk(char *s, size_t maxlen, int flag, size_t slen,
                    const char *fmt, va_list ap) {
    (void)flag; (void)slen;
    return vsnprintf(s, maxlen, fmt, ap);
}
int __sprintf_chk(char *s, int flag, size_t slen, const char *fmt, ...) {
    (void)flag; (void)slen;
    va_list a; va_start(a, fmt);
    int r = vsprintf(s, fmt, a);
    va_end(a);
    return r;
}
int __printf_chk(int flag, const char *fmt, ...) {
    (void)flag;
    va_list a; va_start(a, fmt);
    int r = vprintf(fmt, a);
    va_end(a);
    return r;
}
int __fprintf_chk(FILE *fp, int flag, const char *fmt, ...) {
    (void)flag;
    va_list a; va_start(a, fmt);
    int r = vfprintf(fp, fmt, a);
    va_end(a);
    return r;
}
int __vasprintf_chk(char **result, int flag, const char *fmt, va_list ap) {
    (void)flag;
    return vasprintf(result, fmt, ap);
}

/* ---- FORTIFY misc ---- */
char *__realpath_chk(const char *path, char *resolved, size_t resolvedlen) {
    (void)resolvedlen; return realpath(path, resolved);
}
ssize_t __read_chk(int fd, void *buf, size_t nbytes, size_t buflen) {
    (void)buflen; return read(fd, buf, nbytes);
}
size_t __mbsnrtowcs_chk(wchar_t *dst, const char **src, size_t nmc,
                        size_t len, mbstate_t *ps, size_t dstlen) {
    (void)dstlen; return mbsnrtowcs(dst, src, nmc, len, ps);
}
size_t __mbsrtowcs_chk(wchar_t *dst, const char **src, size_t len,
                       mbstate_t *ps, size_t dstlen) {
    (void)dstlen; return mbsrtowcs(dst, src, len, ps);
}

/* ---- FORTIFY open family. O_CREAT callers would need a mode arg; the
 *      driver never opens with O_CREAT so we forward without it. ---- */
int __open_2(const char *path, int flags) {
    return open(path, flags);
}
int __openat_2(int dirfd, const char *path, int flags) {
    return openat(dirfd, path, flags);
}
int __open64_2(const char *path, int flags) {
    return open(path, flags);
}
int __openat64_2(int dirfd, const char *path, int flags) {
    return openat(dirfd, path, flags);
}

/* ---- arc4random family + getentropy, backed by /dev/urandom. ---- */
int getentropy(void *buf, size_t len) {
    if (len > 256) { errno = EIO; return -1; }
    int fd = open("/dev/urandom", O_RDONLY | O_CLOEXEC);
    if (fd < 0) return -1;
    size_t total = 0;
    while (total < len) {
        ssize_t n = read(fd, (char *)buf + total, len - total);
        if (n <= 0) {
            if (n < 0 && errno == EINTR) continue;
            close(fd);
            errno = EIO;
            return -1;
        }
        total += (size_t)n;
    }
    close(fd);
    return 0;
}
void arc4random_buf(void *buf, size_t len) {
    while (len > 0) {
        size_t chunk = len > 256 ? 256 : len;
        if (getentropy(buf, chunk) != 0) return;
        buf = (char *)buf + chunk;
        len -= chunk;
    }
}
uint32_t arc4random(void) {
    uint32_t r;
    arc4random_buf(&r, sizeof(r));
    return r;
}
uint32_t arc4random_uniform(uint32_t upper) {
    if (upper < 2) return 0;
    uint32_t min = (uint32_t)(-upper) % upper;
    uint32_t r;
    do { r = arc4random(); } while (r < min);
    return r % upper;
}

/* ---- secure_getenv: plain getenv is fine for Plex's callers. ---- */
char *secure_getenv(const char *name) {
    return getenv(name);
}

/* ---- _Float128 numerics. Use __float128 (GCC) so ABI matches the real
 *      symbols on x86_64 even though we ignore the value. ---- */
int strfromf128(char *s, size_t n, const char *format, __float128 x) {
    (void)format; (void)x;
    if (n > 0) s[0] = '\0';
    return 0;
}
__float128 strtof128(const char *nptr, char **endptr) {
    return (__float128)strtold(nptr, endptr);
}

/* ---- _dl_find_object: return "not found" so libgcc_s falls back to the
 *      slower dl_iterate_phdr unwind path. The struct layout we'd need
 *      to populate drifts by glibc version; -1 sidesteps that. ---- */
int _dl_find_object(void *address, void *result) {
    (void)address; (void)result;
    return -1;
}
