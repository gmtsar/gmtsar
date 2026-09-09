#!/usr/bin/env python3
"""build_surface_kernel.py — build _surface_kernel Cython extension in-place.

Usage:
    python3 build_surface_kernel.py build_ext --inplace

The compiled .so is placed next to this script in utils/.  gmt_surface_py.py
imports it via `from _surface_kernel import ...` with a graceful ImportError
fallback to Numba, then to pure Python.

Build requirements:
    - Cython >= 3.0
    - gcc (or compatible C compiler)
    - numpy

Environment:
    SURFACE_KERNEL_CFLAGS : extra compiler flags
        Default: -O2 -march=native -ffp-contract=off
        -ffp-contract=off disables FMA contraction so float32*float32 products
        are rounded to float32 before promotion to double — required for
        bit-identity with Numba's float32 arithmetic order.

Arithmetic contract (float32 version, Mira #72):
    u[]      : float32 (gmt_grdfloat)
    briggs_b : float32 (gmt_grdfloat)
    coeff_*  : float64
    b[k]*u[] : float32*float32=float32 (rounded), then cast to double
    stencil  : float32*float64 → double (implicit C promotion)
    write-back: double → float32 (truncates each iteration)
"""
import os
import sys
import numpy as np
from setuptools import setup, Extension
from Cython.Build import cythonize

HERE = os.path.dirname(os.path.abspath(__file__))

extra_flags = os.environ.get(
    "SURFACE_KERNEL_CFLAGS", "-O2 -march=native -ffp-contract=off"
).split()

ext = Extension(
    "_surface_kernel",
    sources=[os.path.join(HERE, "_surface_kernel.pyx")],
    include_dirs=[np.get_include()],
    extra_compile_args=extra_flags,
)

setup(
    name="_surface_kernel",
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
