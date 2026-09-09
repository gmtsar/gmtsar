/* getline() shim for native Windows (MinGW) builds, where the mingw-w64
 * runtime does not export this glibc/POSIX extension (declared by some
 * mingw stdio.h versions, but not linkable -- "undefined reference").
 * Only fitoffset.c uses it. Force-included via that target's
 * target_compile_options(-include ...) in gmtsar/CMakeLists.txt, rather
 * than editing fitoffset.c itself, to keep upstream .c files untouched
 * (see gmtsar/compat_win32/sys/mman.h for the same convention).
 */
#ifndef GMTSAR_COMPAT_WIN32_GETLINE_SHIM_H
#define GMTSAR_COMPAT_WIN32_GETLINE_SHIM_H

#include <stdio.h>
#include <stdlib.h>

#ifdef _MSC_VER
#include <fcntl.h>
#include <io.h>
#include <string.h>
#include <sys/stat.h>
#include <windows.h>

typedef __int64 ssize_t;

#define close _close
#define fdopen _fdopen
#define pclose _pclose
#define popen _popen
#define unlink _unlink

/* fitoffset uses POSIX /tmp templates.  Translate those to the native
 * per-user temporary directory and create the file with exclusive access. */
static __inline int gmtsar_mkstemp(char *file_template) {
    char temp_dir[MAX_PATH];
    char native_template[MAX_PATH];
    const char *leaf;
    size_t length;

    if (!file_template || GetTempPathA(MAX_PATH, temp_dir) == 0)
        return -1;
    leaf = strrchr(file_template, '/');
    leaf = leaf ? leaf + 1 : file_template;
    if (snprintf(native_template, sizeof native_template, "%s%s", temp_dir, leaf) < 0)
        return -1;
    length = strlen(native_template) + 1;
    if (_mktemp_s(native_template, length) != 0)
        return -1;
    strcpy_s(file_template, MAX_PATH, native_template);
    return _open(file_template, _O_CREAT | _O_EXCL | _O_RDWR | _O_BINARY,
        _S_IREAD | _S_IWRITE);
}

#define mkstemp gmtsar_mkstemp
#endif

static __inline ssize_t getline(char **lineptr, size_t *n, FILE *stream) {
    if (!lineptr || !n || !stream)
        return -1;

    if (!*lineptr || *n == 0) {
        *n = 128;
        *lineptr = (char *)malloc(*n);
        if (!*lineptr)
            return -1;
    }

    size_t pos = 0;
    int c;
    while ((c = fgetc(stream)) != EOF) {
        if (pos + 1 >= *n) {
            size_t new_size = *n * 2;
            char *new_ptr = (char *)realloc(*lineptr, new_size);
            if (!new_ptr)
                return -1;
            *lineptr = new_ptr;
            *n = new_size;
        }
        (*lineptr)[pos++] = (char)c;
        if (c == '\n')
            break;
    }

    if (pos == 0 && c == EOF)
        return -1;

    (*lineptr)[pos] = '\0';
    return (ssize_t)pos;
}

#endif /* GMTSAR_COMPAT_WIN32_GETLINE_SHIM_H */
