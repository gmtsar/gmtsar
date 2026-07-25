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
