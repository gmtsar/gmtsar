"""GMT v4 native-binary "=bf" grd format I/O helpers.

The GMT4 native float grid format is what filter.csh pipes around via the
`=bf` suffix. Layout (892-byte header + raw float32 data, native endian):

    int32  nx                   # number of columns
    int32  ny                   # number of rows
    int32  node_offset          # 0 gridline, 1 pixel
    double x_min, x_max         # span in x
    double y_min, y_max         # span in y
    double z_min, z_max         # data range (informational; may be 0)
    double x_inc, y_inc         # grid spacing
    double z_scale_factor       # usually 1.0
    double z_add_offset         # usually 0.0
    char   x_units[80]
    char   y_units[80]
    char   z_units[80]
    char   title[80]
    char   command[320]
    char   remark[160]
    -- total = 12 + 80 + 80*4 + 320 + 160 = 892 bytes

Data follows immediately as nx*ny float32 in row-major order, with row 0
being the TOP of the image (highest y, image-style — same as netCDF GMT
grds when read by GMT_Read_Data in the C `conv` source).
"""
from __future__ import annotations

import struct
from typing import Tuple

import numpy as np

_HEADER_SIZE = 892


def read_bf(path: str) -> Tuple[np.ndarray, dict]:
    """Read a GMT v4 native binary float grd ("=bf" format).

    Returns (data, info):
        data: float32 ndarray, shape (ny, nx), row 0 = top of image.
        info: dict with nx, ny, node_offset, x_min/x_max/y_min/y_max,
              x_inc, y_inc, z_min, z_max.
    """
    with open(path, "rb") as f:
        hdr = f.read(_HEADER_SIZE)
        if len(hdr) != _HEADER_SIZE:
            raise IOError(f"{path}: short header ({len(hdr)} bytes, expected {_HEADER_SIZE})")
        nx, ny, node_offset = struct.unpack("<iii", hdr[:12])
        x_min, x_max, y_min, y_max, z_min, z_max, x_inc, y_inc, _zsf, _zao = \
            struct.unpack("<10d", hdr[12:92])
        data = np.fromfile(f, dtype=np.float32, count=nx * ny)
        if data.size != nx * ny:
            raise IOError(
                f"{path}: short data — got {data.size} floats, expected {nx*ny}"
            )
        data = data.reshape(ny, nx)
    info = dict(
        nx=nx, ny=ny, node_offset=node_offset,
        x_min=x_min, x_max=x_max, y_min=y_min, y_max=y_max,
        z_min=z_min, z_max=z_max, x_inc=x_inc, y_inc=y_inc,
    )
    return data, info


def write_bf(path: str, data: np.ndarray, *,
             x_min: float = 0.0, y_min: float = 0.0,
             x_inc: float = 1.0, y_inc: float = 1.0,
             node_offset: int = 1,
             title: str = "", remark: str = "", command: str = "") -> None:
    """Write a GMT v4 native binary float grd ("=bf" format).

    `data` must be shape (ny, nx) and in row-0=top-of-image orientation
    (the C-conv convention). Will be cast to float32.

    Pixel registration default; for gridline pass node_offset=0.
    """
    data = np.ascontiguousarray(data, dtype=np.float32)
    ny, nx = data.shape

    if node_offset == 1:
        x_max = x_min + nx * x_inc
        y_max = y_min + ny * y_inc
    else:
        x_max = x_min + (nx - 1) * x_inc
        y_max = y_min + (ny - 1) * y_inc

    if data.size == 0:
        z_min = z_max = 0.0
    else:
        valid = ~np.isnan(data)
        if valid.any():
            z_min = float(data[valid].min())
            z_max = float(data[valid].max())
        else:
            z_min = z_max = 0.0

    hdr = bytearray(_HEADER_SIZE)
    struct.pack_into("<iii", hdr, 0, nx, ny, node_offset)
    struct.pack_into("<10d", hdr, 12,
                     x_min, x_max, y_min, y_max,
                     z_min, z_max, x_inc, y_inc, 1.0, 0.0)
    # 80*3 + 80 + 320 + 160 strings (x_units, y_units, z_units, title,
    # command, remark) — all zero-padded by default.
    # Stash a tiny title/remark at the correct offsets:
    off = 92  # start of string section
    def _put(s: str, n: int, base: int) -> None:
        b = s.encode("ascii", errors="replace")[: n - 1]
        hdr[base:base + len(b)] = b
        # rest stays zero
    _put("", 80, off);             off += 80   # x_units
    _put("", 80, off);             off += 80   # y_units
    _put("", 80, off);             off += 80   # z_units
    _put(title, 80, off);          off += 80   # title
    _put(command, 320, off);       off += 320  # command
    _put(remark, 160, off);        off += 160  # remark
    assert off == _HEADER_SIZE

    with open(path, "wb") as f:
        f.write(bytes(hdr))
        data.tofile(f)
