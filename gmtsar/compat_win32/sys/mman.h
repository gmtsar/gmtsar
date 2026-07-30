/* Minimal mmap()/munmap() shim for native Windows (MinGW) builds, where
 * <sys/mman.h> does not exist. Only the subset gmtsar's sbas_utils.c,
 * resamp.c and sbas.c actually use: PROT_READ/PROT_WRITE, MAP_SHARED,
 * mmap() over a file descriptor, munmap(). Implemented on top of
 * CreateFileMapping/MapViewOfFile via _get_osfhandle(fd).
 */
#ifndef GMTSAR_COMPAT_WIN32_SYS_MMAN_H
#define GMTSAR_COMPAT_WIN32_SYS_MMAN_H

#include <io.h>
/* Exclude winsock.h -- it declares its own connect(), which collides with
 * gmtsar's unrelated SBAS graph-connectivity function of the same name in
 * sbas.c/sbas_utils.c. This shim only needs the file-mapping API. */
#ifndef WIN32_LEAN_AND_MEAN
#define WIN32_LEAN_AND_MEAN
#endif
#include <windows.h>

#define PROT_READ  0x1
#define PROT_WRITE 0x2
#define MAP_SHARED 0x01
#define MAP_FAILED ((void *)-1)

static __inline void *mmap(void *addr, size_t length, int prot, int flags,
                            int fd, long offset) {
    (void)addr;
    (void)flags;
    HANDLE file = (HANDLE)_get_osfhandle(fd);
    if (file == INVALID_HANDLE_VALUE)
        return MAP_FAILED;

    DWORD protect = (prot & PROT_WRITE) ? PAGE_READWRITE : PAGE_READONLY;
    DWORD access = (prot & PROT_WRITE) ? FILE_MAP_WRITE : FILE_MAP_READ;

    HANDLE mapping = CreateFileMapping(file, NULL, protect, 0, 0, NULL);
    if (mapping == NULL)
        return MAP_FAILED;

    void *view = MapViewOfFile(mapping, access, 0,
                                (DWORD)(offset & 0xffffffff), length);
    /* The mapping handle isn't needed once the view exists -- Windows
     * keeps it alive internally until UnmapViewOfFile(). */
    CloseHandle(mapping);
    if (view == NULL)
        return MAP_FAILED;
    return view;
}

static __inline int munmap(void *addr, size_t length) {
    (void)length;
    return UnmapViewOfFile(addr) ? 0 : -1;
}

#endif /* GMTSAR_COMPAT_WIN32_SYS_MMAN_H */
