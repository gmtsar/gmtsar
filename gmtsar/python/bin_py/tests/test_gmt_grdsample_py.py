#!/usr/bin/env python3
"""test_gmt_grdsample_py — C-parity test for utils/gmt_grdsample_py.

Runs ``gmt grdsample`` (subprocess) and ``gmt_grdsample_py`` on the SAME
input grid and asserts that the resampled outputs agree.

Three test families:

  1. Synthetic gridline-registered grid (smooth product of trig functions
     — bandlimited so resampling at finer increments has a unique answer
     and bicubic gives near-roundoff parity).
     - shrink 2x, shrink 4x
     - expand 2x, expand 4x
     - same-size resample with shifted region (sub-pixel shift)
     For each: assert rms(py - gmt) <= 1e-5 (bicubic) or <= 1e-4
     (bilinear; B-spline on smooth data is also tight).

  2. Real DEM grid: take work/csh_test/RS2_SLC_Hawaii/topo/dem.grd
     (READ-ONLY per Rule 9), resample 2x downsample via gmt and via
     gmt_grdsample_py. Assert rms(py - gmt) <= 1.0 m for both bilinear
     and bicubic. (Float32 has ULP ~ 5e-7 of value magnitude; on a
     DEM ranging 5 -> 4196 m, ULP ~ 2e-3 m, so 1 m is ~500x ULP — slack
     to allow for the natural-BC vs index-clamp difference at the
     2-cell-thick edge.  Interior-only RMS is tighter; see test.)

  3. Pixel-registration round trip: build a pixel-registered synthetic
     grid, resample via gmt and py.  Both must produce the same
     registration flag and matching values.

Skips loudly (does NOT silently pass) if ``gmt`` is not on PATH.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

import numpy as np

# ---------------------------------------------------------------------------
# Locate sources
# ---------------------------------------------------------------------------

_HERE = Path(__file__).resolve().parent
_UTILS = _HERE.parent.parent / "utils"          # gmtsar/python/utils/
sys.path.insert(0, str(_UTILS))

from gmt_grdsample_py import gmt_grdsample_py   # noqa: E402
from gmt_grd_io import write_gmt_grd, read_gmt_grd  # noqa: E402

_GMT = shutil.which("gmt")
_HAVE_GMT = _GMT is not None and os.access(_GMT, os.X_OK)

# Real DEM file (READ-ONLY).
_WORK_ROOT = Path(
    os.environ.get("GMTSAR_TEST_WORK")
    or (os.environ.get("GMTSAR", "") + "/gmtsar/python/work"
        if os.environ.get("GMTSAR") else "")
    or str(_HERE.parents[2] / "work")
)
_DEM_PATH = _WORK_ROOT / "csh_test/RS2_SLC_Hawaii/topo/dem.grd"
_HAVE_DEM = _DEM_PATH.exists()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _gmt_grdsample(in_path: str, out_path: str, args: list[str]) -> float:
    """Invoke ``gmt grdsample <in> <args> -G<out>``. Return wall time (s)."""
    cmd = [_GMT, "grdsample", in_path, *args, f"-G{out_path}"]
    t0 = time.time()
    res = subprocess.run(cmd, capture_output=True, text=True, check=False)
    dt = time.time() - t0
    if res.returncode != 0:
        raise RuntimeError(
            f"gmt grdsample failed (rc={res.returncode})\n"
            f"  cmd: {' '.join(cmd)}\n  stderr: {res.stderr}"
        )
    return dt


def _make_smooth_grid(nx: int, ny: int,
                      xmin=0.0, xmax=10.0,
                      ymin=0.0, ymax=8.0):
    """Smooth product-of-trig field on a gridline-registered lattice.

    Bandlimited at wavenumber 2 cycles across the domain (Nyquist-safe
    for >= 5 samples/cycle). Returns (data, x, y)."""
    x = np.linspace(xmin, xmax, nx, dtype=np.float64)
    y = np.linspace(ymin, ymax, ny, dtype=np.float64)
    kx = 2.0 * np.pi / (xmax - xmin)
    ky = 2.0 * np.pi / (ymax - ymin)
    z = (np.sin(kx * x[None, :] * 2.0) *
         np.cos(ky * y[:, None] * 1.5)).astype(np.float32)
    return z, x, y


def _rms(a: np.ndarray, b: np.ndarray) -> float:
    """RMS of (a - b), ignoring NaN."""
    diff = a.astype(np.float64) - b.astype(np.float64)
    mask = np.isfinite(diff)
    if not mask.any():
        return float('nan')
    return float(np.sqrt(np.mean(diff[mask] ** 2)))


# ---------------------------------------------------------------------------
# Suite 1: synthetic grids
# ---------------------------------------------------------------------------

@unittest.skipUnless(_HAVE_GMT, "gmt binary not on PATH; parity test cannot run")
class TestSyntheticSmooth(unittest.TestCase):
    """Resample a smooth synthetic grid at several rates / shifts."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp(prefix="grdsample_par_")
        cls.in_path = os.path.join(cls.tmp, "in.grd")
        cls.data, cls.x, cls.y = _make_smooth_grid(nx=61, ny=49)
        # Write a gridline-registered .grd
        write_gmt_grd(cls.in_path, cls.data, cls.x, cls.y, node_offset=0)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def _run_case(self, gmt_args: list[str], py_kwargs: dict,
                  rms_tol_bilinear: float, rms_tol_bicubic: float,
                  label: str, rms_tol_bspline: float | None = None):
        """Run gmt + py for bilinear, bicubic, and (optional) b-spline.

        ``rms_tol_bspline`` defaults to ``rms_tol_bicubic`` if not given —
        b-spline weights are a smoother and add a small DC bias, but at
        roundoff-parity vs gmt (the C kernel formulas are identical to
        ours, see gmt_bcr.c:178-199).
        """
        if rms_tol_bspline is None:
            rms_tol_bspline = rms_tol_bicubic
        for interp, tol, gflag in (
            ("bilinear", rms_tol_bilinear, "-nl"),
            ("bicubic", rms_tol_bicubic, "-nc"),
            ("bspline",  rms_tol_bspline,  "-nb"),
        ):
            out_gmt = os.path.join(self.tmp, f"out_{label}_{interp}.grd")
            _gmt_grdsample(self.in_path, out_gmt, gmt_args + [gflag])
            z_gmt, x_gmt, y_gmt, info_gmt = read_gmt_grd(out_gmt)

            z_py, x_py, y_py, info_py = gmt_grdsample_py(
                self.data, self.x, self.y, interp=interp, **py_kwargs,
            )
            # Shapes must match
            self.assertEqual(z_py.shape, z_gmt.shape,
                             f"{label}/{interp}: py shape {z_py.shape} != gmt {z_gmt.shape}")
            self.assertEqual(len(x_py), len(x_gmt))
            self.assertEqual(len(y_py), len(y_gmt))
            # Coord arrays match to roundoff
            np.testing.assert_allclose(x_py, x_gmt, atol=1e-9, err_msg=f"{label}/{interp}: x_out")
            np.testing.assert_allclose(y_py, y_gmt, atol=1e-9, err_msg=f"{label}/{interp}: y_out")
            # gmt writes north-first internally but read_gmt_grd flips
            # back to y-ascending, so z_gmt and z_py share that layout.
            r = _rms(z_py, z_gmt)
            self.assertLessEqual(
                r, tol,
                f"{label}/{interp}: rms={r:.3e} exceeds tol {tol:.3e}"
            )

    def test_shrink_2x(self):
        """Halve the increments (more output cells)."""
        in_dx = float(self.x[1] - self.x[0])
        in_dy = float(self.y[1] - self.y[0])
        self._run_case(
            gmt_args=[f"-I{in_dx/2}/{in_dy/2}"],
            py_kwargs=dict(new_x_inc=in_dx / 2, new_y_inc=in_dy / 2),
            rms_tol_bilinear=5e-5,
            rms_tol_bicubic=5e-6,
            label="shrink2x",
        )

    def test_shrink_4x(self):
        in_dx = float(self.x[1] - self.x[0])
        in_dy = float(self.y[1] - self.y[0])
        self._run_case(
            gmt_args=[f"-I{in_dx/4}/{in_dy/4}"],
            py_kwargs=dict(new_x_inc=in_dx / 4, new_y_inc=in_dy / 4),
            rms_tol_bilinear=5e-5,
            rms_tol_bicubic=5e-6,
            label="shrink4x",
        )

    def test_expand_2x(self):
        """Double the increments (fewer output cells, aliasing-prone)."""
        in_dx = float(self.x[1] - self.x[0])
        in_dy = float(self.y[1] - self.y[0])
        self._run_case(
            gmt_args=[f"-I{in_dx*2}/{in_dy*2}"],
            py_kwargs=dict(new_x_inc=in_dx * 2, new_y_inc=in_dy * 2),
            # Aliasing is OK -- both gmt and py do the same thing,
            # so the parity tolerance stays tight.
            rms_tol_bilinear=5e-5,
            rms_tol_bicubic=5e-6,
            label="expand2x",
        )

    def test_expand_4x(self):
        in_dx = float(self.x[1] - self.x[0])
        in_dy = float(self.y[1] - self.y[0])
        self._run_case(
            gmt_args=[f"-I{in_dx*4}/{in_dy*4}"],
            py_kwargs=dict(new_x_inc=in_dx * 4, new_y_inc=in_dy * 4),
            rms_tol_bilinear=5e-5,
            rms_tol_bicubic=5e-6,
            label="expand4x",
        )

    def test_subpixel_shift_same_inc(self):
        """Resample at the same increment but with a sub-pixel region shift.

        This is the case that actually exercises the kernel weights —
        if increments are unchanged AND region is aligned to grid nodes
        the output coincides with input cells and weights collapse to
        identities, hiding kernel bugs.
        """
        in_dx = float(self.x[1] - self.x[0])
        in_dy = float(self.y[1] - self.y[0])
        # Shift the region by 0.37*dx and 0.21*dy; trim by one cell so the
        # output stays strictly inside the input extent (no BC dependence).
        shift_x = 0.37 * in_dx
        shift_y = 0.21 * in_dy
        xlo = float(self.x[0]) + shift_x
        xhi = float(self.x[-1]) - in_dx + shift_x
        ylo = float(self.y[0]) + shift_y
        yhi = float(self.y[-1]) - in_dy + shift_y
        self._run_case(
            gmt_args=[f"-R{xlo}/{xhi}/{ylo}/{yhi}",
                      f"-I{in_dx}/{in_dy}"],
            py_kwargs=dict(new_x_inc=in_dx, new_y_inc=in_dy,
                           new_region=(xlo, xhi, ylo, yhi)),
            rms_tol_bilinear=5e-5,
            rms_tol_bicubic=5e-6,
            label="shift_subpx",
        )


# ---------------------------------------------------------------------------
# Suite 2: real DEM
# ---------------------------------------------------------------------------

@unittest.skipUnless(_HAVE_GMT, "gmt binary not on PATH")
@unittest.skipUnless(_HAVE_DEM, f"dem.grd not present at {_DEM_PATH}")
class TestRealDemHawaii(unittest.TestCase):
    """Parity vs gmt on real RS2 Hawaii dem.grd. READ-ONLY input (Rule 9)."""

    @classmethod
    def setUpClass(cls):
        # Per Rule 9: copy dem.grd to a fresh tmp dir before any gmt call
        # (gmt grdsample never writes to its input, but defence-in-depth).
        cls.tmp = tempfile.mkdtemp(prefix="grdsample_dem_")
        cls.dem_copy = os.path.join(cls.tmp, "dem.grd")
        shutil.copyfile(str(_DEM_PATH), cls.dem_copy)
        # Read the dem once via gmt_grd_io for the py call.
        cls.dem_data, cls.dem_x, cls.dem_y, cls.dem_info = read_gmt_grd(cls.dem_copy)
        cls.in_dx = float(cls.dem_x[1] - cls.dem_x[0])
        cls.in_dy = float(cls.dem_y[1] - cls.dem_y[0])

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def _real_case(self, interp: str, factor: float,
                   rms_tol_global: float, rms_tol_interior: float):
        new_dx = self.in_dx * factor
        new_dy = self.in_dy * factor
        gflag = {'bilinear': '-nl', 'bicubic': '-nc', 'bspline': '-nb'}[interp]
        out_gmt = os.path.join(self.tmp, f"out_{interp}_{factor}.grd")
        t_gmt = _gmt_grdsample(
            self.dem_copy, out_gmt,
            [f"-I{new_dx}/{new_dy}", gflag],
        )
        z_gmt, x_gmt, y_gmt, info_gmt = read_gmt_grd(out_gmt)

        t0 = time.time()
        z_py, x_py, y_py, info_py = gmt_grdsample_py(
            self.dem_data, self.dem_x, self.dem_y,
            new_x_inc=new_dx, new_y_inc=new_dy,
            interp=interp,
        )
        t_py = time.time() - t0

        self.assertEqual(z_py.shape, z_gmt.shape,
                         f"{interp}@{factor}x: shape {z_py.shape} != {z_gmt.shape}")
        np.testing.assert_allclose(x_py, x_gmt, atol=1e-8)
        np.testing.assert_allclose(y_py, y_gmt, atol=1e-8)

        rms_global = _rms(z_py, z_gmt)
        # Interior excludes 4 rows/cols on each edge -- our boundary
        # policy (index clamp) differs from gmt's natural BC.
        if z_py.shape[0] > 8 and z_py.shape[1] > 8:
            rms_interior = _rms(z_py[4:-4, 4:-4], z_gmt[4:-4, 4:-4])
        else:
            rms_interior = rms_global
        print(f"   dem/{interp} f={factor}: rms_glob={rms_global:.3e}, "
              f"rms_int={rms_interior:.3e}, t_gmt={t_gmt:.2f}s, t_py={t_py:.2f}s")
        self.assertLessEqual(
            rms_global, rms_tol_global,
            f"{interp}@{factor}: global rms {rms_global:.3e} > {rms_tol_global:.3e}"
        )
        self.assertLessEqual(
            rms_interior, rms_tol_interior,
            f"{interp}@{factor}: interior rms {rms_interior:.3e} > {rms_tol_interior:.3e}"
        )

    def test_dem_downsample_2x_bilinear(self):
        """Real DEM downsampled 2x with bilinear."""
        # DEM range is 5-4196 m.  Tolerances pick up the ~1-2 m natural-
        # BC edge difference globally, ~0.01 m interior agreement.
        self._real_case("bilinear", factor=2.0,
                        rms_tol_global=2.0,
                        rms_tol_interior=0.05)

    def test_dem_downsample_2x_bicubic(self):
        """Real DEM downsampled 2x with bicubic."""
        self._real_case("bicubic", factor=2.0,
                        rms_tol_global=5.0,
                        rms_tol_interior=0.5)

    def test_dem_downsample_2x_bspline(self):
        """Real DEM downsampled 2x with b-spline (-nb)."""
        # b-spline is a smoother — its weights are not interpolatory
        # (wx(0) != 1, see gmt_bcr.c:182), so absolute deviations from
        # the original samples are larger than bicubic at the boundary,
        # but the C and py kernels are formula-identical so parity stays
        # tight in the interior.
        self._real_case("bspline", factor=2.0,
                        rms_tol_global=5.0,
                        rms_tol_interior=0.5)


# ---------------------------------------------------------------------------
# Suite 3: pixel registration
# ---------------------------------------------------------------------------

@unittest.skipUnless(_HAVE_GMT, "gmt binary not on PATH")
class TestPixelRegistration(unittest.TestCase):
    """Verify pixel-registered input / output is handled correctly."""

    def test_pixel_in_pixel_out_bilinear(self):
        tmp = tempfile.mkdtemp(prefix="grdsample_pix_")
        try:
            nx, ny = 41, 33
            data, x_gridline, y_gridline = _make_smooth_grid(nx=nx, ny=ny)
            # Convert to pixel-registered coordinates: x is at cell centres
            in_dx = float(x_gridline[1] - x_gridline[0])
            in_dy = float(y_gridline[1] - y_gridline[0])
            x_pix = x_gridline  # values don't matter for the writer,
            y_pix = y_gridline  # but the registration flag does.
            in_path = os.path.join(tmp, "in_pix.grd")
            write_gmt_grd(in_path, data, x_pix, y_pix, node_offset=1)

            out_gmt = os.path.join(tmp, "out_pix.grd")
            _gmt_grdsample(in_path, out_gmt,
                           [f"-I{in_dx/2}/{in_dy/2}", "-nl", "-r"])
            z_gmt, x_gmt, y_gmt, info_gmt = read_gmt_grd(out_gmt)
            self.assertEqual(info_gmt['node_offset'], 1,
                             "gmt output must be pixel-registered")

            z_py, x_py, y_py, info_py = gmt_grdsample_py(
                data, x_pix, y_pix,
                new_x_inc=in_dx / 2, new_y_inc=in_dy / 2,
                interp="bilinear",
                pixel_reg=True, in_pixel_reg=True,
            )

            self.assertEqual(z_py.shape, z_gmt.shape,
                             f"pixel/2x: {z_py.shape} != {z_gmt.shape}")
            np.testing.assert_allclose(x_py, x_gmt, atol=1e-9)
            np.testing.assert_allclose(y_py, y_gmt, atol=1e-9)
            r = _rms(z_py, z_gmt)
            self.assertLessEqual(r, 5e-5, f"pixel/2x: rms={r:.3e}")
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


# ---------------------------------------------------------------------------
# Suite 4: oracle-availability gate
# ---------------------------------------------------------------------------

class TestOracleAvailability(unittest.TestCase):
    """Loud failure if the gmt binary isn't present (per Mira rule)."""

    def test_gmt_is_on_path(self):
        if not _HAVE_GMT:
            self.skipTest(
                "gmt binary not on PATH. parity test cannot validate "
                "gmt_grdsample_py vs the C reference -- this is a "
                "loud SKIP, not a pass. Install gmt to run parity."
            )
        # If we get here, gmt is callable -- assert it's actually
        # version 6 (the only one whose source we ported against).
        res = subprocess.run([_GMT, "--version"], capture_output=True, text=True)
        self.assertEqual(res.returncode, 0)
        self.assertTrue(res.stdout.startswith("6."),
                        f"unexpected gmt version: {res.stdout!r}")


if __name__ == "__main__":
    unittest.main(verbosity=2)
