#!/usr/bin/env python3
"""build_snaphu_kernel.py — build _snaphu_solver_kernel Cython extension in-place.

Usage:
    python3 build_snaphu_kernel.py build_ext --inplace

The compiled .so is placed next to this script in bin_py/snaphu_py/.
network_flow_optimize_cy() in snaphu_solver_numba.py imports it via
`from _snaphu_solver_kernel import tree_solve_kernel_cy` with a graceful
ImportError fallback to the numba kernel.

Build requirements:
    - Cython >= 3.0
    - gcc (or compatible C compiler)
    - numpy

Arithmetic contract:
    All arithmetic is integer (int64, int32, int16, int8).
    No floating-point operations in the kernel — no -ffp-contract concerns.
    -O2 -march=native is safe and gives ~20-30% win over -O0.

Design:
    The .pyx mirrors the numba SoA layout exactly (flat int32/int64 arrays).
    All hot-path cdef functions are marked noexcept nogil — zero Python
    overhead on the critical path.
"""
import os
import sys
import numpy as np
from setuptools import setup, Extension
from Cython.Build import cythonize

HERE = os.path.dirname(os.path.abspath(__file__))

extra_flags = os.environ.get(
    "SNAPHU_KERNEL_CFLAGS", "-O2 -march=native"
).split()

ext = Extension(
    "_snaphu_solver_kernel",
    sources=[os.path.join(HERE, "_snaphu_solver_kernel.pyx")],
    include_dirs=[np.get_include()],
    extra_compile_args=extra_flags,
)

setup(
    name="_snaphu_solver_kernel",
    ext_modules=cythonize(
        [ext],
        compiler_directives={
            "language_level": "3",
            "boundscheck": False,
            "wraparound": False,
            "cdivision": True,
            "nonecheck": False,
        },
        annotate=False,
    ),
    script_args=sys.argv[1:],
)
