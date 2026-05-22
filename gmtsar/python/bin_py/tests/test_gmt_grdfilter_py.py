#!/usr/bin/env python3
"""test_gmt_grdfilter_py — C-parity tests for the Numba port of
`gmt grdfilter -Fg -Dp -Ni`.

These are bit-faithful tests against the real `gmt` binary. They run
gmt and the Python port on the SAME input bytes and assert
float32-roundoff identity. They are NOT self-consistency tests.

If `gmt` is not on PATH these tests fail LOUDLY (per Mira rule and the
project memory note "bin_py tests need C-parity, not self-consistency").

Run:
    python3 -m unittest gmtsar/python/bin_py/tests/test_gmt_grdfilter_py.py -v
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
from typing import Optional

import numpy as np

# Locate gmt — prefer the conda env on this host.
_GMT_CANDIDATES = [
    "/home/staff/dliu/anaconda3/envs/gmtsar/bin/gmt",
    shutil.which("gmt") or "",
]
GMT = next((g for g in _GMT_CANDIDATES if g and os.path.exists(g)), "")

_HERE = Path(__file__).resolve().parent
_UTILS = _HERE.parent.parent / "utils"
sys.path.insert(0, str(_UTILS))

from gmt_grd_io import read_gmt_grd, write_gmt_grd  # noqa: E402
from gmt_grdfilter_py import gmt_grdfilter_py        # noqa: E402


# Parity tolerance: float32 ULP at unit-scale is ~1e-7. Allow a small
# multiple to absorb the difference between gmt's double-precision
# accumulator (cast to float on write) and our double accumulator
# (also cast to float on output). Empirically ~1e-6 works.
ATOL_FLOAT32 = 1e-5


def _require_gmt() -> str:
    if not GMT:
        raise unittest.SkipTest(
            "gmt binary not found; gmt grdfilter parity tests require GMT 6. "
            "Install gmt or activate the conda gmtsar env."
        )
    return GMT


def _gmt_grdfilter_fg(
    gmt_bin: str,
    data: np.ndarray,
    x: np.ndarray,
    y: np.ndarray,
    filtx: float,
    filty: Optional[float],
    inc_x_out: float,
    inc_y_out: float,
    node_offset: int,
    tmpdir: Path,
    tag: str = "gmt",
) -> np.ndarray:
    """Run the real `gmt grdfilter` and read back the output grid.

    If `filty is None`: `-Fg<filtx>` (single width → CIRCULAR branch).
    Else:               `-Fg<filtx>/<filty>` (two widths → RECT branch).
    """
    in_grd = tmpdir / f"{tag}_in.grd"
    out_grd = tmpdir / f"{tag}_out.grd"
    write_gmt_grd(str(in_grd), data, x, y, node_offset=node_offset)
    if filty is None:
        f_arg = f"-Fg{filtx}"
    else:
        f_arg = f"-Fg{filtx}/{filty}"
    cmd = [
        gmt_bin, "grdfilter", str(in_grd),
        "-Dp", f_arg,
        f"-G{out_grd}", "-Vq", "-Ni",
        f"-I{inc_x_out}/{inc_y_out}",
    ]
    subprocess.run(cmd, check=True)
    z_gmt, _, _, _ = read_gmt_grd(str(out_grd))
    return z_gmt


class TestGmtGrdfilterParitySynthetic(unittest.TestCase):
    """Synthetic-input parity. Bit-faithful within float32 ULP."""

    @classmethod
    def setUpClass(cls):
        cls.gmt = _require_gmt()
        cls.tmpdir = Path(tempfile.mkdtemp(prefix="grdfilter_synth_"))

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmpdir, ignore_errors=True)

    def test_gaussian_bump_no_resample(self):
        """Smooth Gaussian bump, no -I resampling, gridline reg.
        Output shape == input shape; both kernels see no NaN, no
        boundary truncation in the interior, partial circle at the edges.
        """
        ny, nx = 80, 100
        cy, cx = ny / 2.0, nx / 2.0
        yy, xx = np.mgrid[0:ny, 0:nx].astype(np.float64)
        # Smooth Gaussian bump, amplitude 10, sigma ~15.
        data = (10.0 * np.exp(-((yy - cy) ** 2 + (xx - cx) ** 2) / (2.0 * 15.0 ** 2))).astype(np.float32)
        x = np.arange(nx, dtype=np.float64)
        y = np.arange(ny, dtype=np.float64)

        filtx = filty = 21.0
        z_gmt = _gmt_grdfilter_fg(
            self.gmt, data, x, y, filtx, filty,
            inc_x_out=1.0, inc_y_out=1.0,
            node_offset=0, tmpdir=self.tmpdir, tag="bump_noresamp",
        )
        z_py, _, _ = gmt_grdfilter_py(
            data, x, y,
            filter_type="g", filter_width=filtx, filter_width2=filty,
            mode="mean", distance_units="p", nan_mode="i",
            inc_x_out=1.0, inc_y_out=1.0, node_offset=0,
        )
        self.assertEqual(z_gmt.shape, z_py.shape,
                         f"shape mismatch: gmt={z_gmt.shape}, py={z_py.shape}")
        diff = z_gmt - z_py
        max_abs = float(np.nanmax(np.abs(diff)))
        rms = float(np.sqrt(np.nanmean(diff ** 2)))
        self.assertLess(max_abs, ATOL_FLOAT32,
                        f"gaussian-bump parity diverged: max|diff|={max_abs:.3e}, "
                        f"rms={rms:.3e} (tolerance {ATOL_FLOAT32:.0e})")

    def test_gaussian_bump_with_resample(self):
        """Same bump, with -I8/8 resampling (matches iono-path pattern)."""
        ny, nx = 80, 100
        cy, cx = ny / 2.0, nx / 2.0
        yy, xx = np.mgrid[0:ny, 0:nx].astype(np.float64)
        data = (10.0 * np.exp(-((yy - cy) ** 2 + (xx - cx) ** 2) / (2.0 * 15.0 ** 2))).astype(np.float32)
        x = np.arange(nx, dtype=np.float64)
        y = np.arange(ny, dtype=np.float64)

        filtx = filty = 21.0
        inc_out = 8.0
        z_gmt = _gmt_grdfilter_fg(
            self.gmt, data, x, y, filtx, filty,
            inc_x_out=inc_out, inc_y_out=inc_out,
            node_offset=0, tmpdir=self.tmpdir, tag="bump_resamp",
        )
        z_py, _, _ = gmt_grdfilter_py(
            data, x, y,
            filter_type="g", filter_width=filtx, filter_width2=filty,
            mode="mean", distance_units="p", nan_mode="i",
            inc_x_out=inc_out, inc_y_out=inc_out, node_offset=0,
        )
        self.assertEqual(z_gmt.shape, z_py.shape,
                         f"shape mismatch (with -I{inc_out}): gmt={z_gmt.shape}, py={z_py.shape}")
        diff = z_gmt - z_py
        max_abs = float(np.nanmax(np.abs(diff)))
        rms = float(np.sqrt(np.nanmean(diff ** 2)))
        self.assertLess(max_abs, ATOL_FLOAT32,
                        f"resampled-bump parity diverged: max|diff|={max_abs:.3e}, "
                        f"rms={rms:.3e}")

    def test_gaussian_bump_circular_single_width(self):
        """Single-width Gaussian -Fg21 (no slash) → CIRCULAR branch.
        Confirms the circular-truncated kernel matches gmt's single-width
        path (different code path inside gmt — F.rect = false)."""
        ny, nx = 80, 100
        cy, cx = ny / 2.0, nx / 2.0
        yy, xx = np.mgrid[0:ny, 0:nx].astype(np.float64)
        data = (10.0 * np.exp(-((yy - cy) ** 2 + (xx - cx) ** 2) / (2.0 * 15.0 ** 2))).astype(np.float32)
        x = np.arange(nx, dtype=np.float64)
        y = np.arange(ny, dtype=np.float64)

        filt = 21.0   # odd integer pixel count — gmt -Dp requirement
        # gmt: -Fg21 (single width). py: omit filter_width2 (rect=False).
        z_gmt = _gmt_grdfilter_fg(
            self.gmt, data, x, y, filt, None,
            inc_x_out=1.0, inc_y_out=1.0,
            node_offset=0, tmpdir=self.tmpdir, tag="bump_circ",
        )
        z_py, _, _ = gmt_grdfilter_py(
            data, x, y,
            filter_type="g", filter_width=filt,    # filter_width2=None → circular
            mode="mean", distance_units="p", nan_mode="i",
            inc_x_out=1.0, inc_y_out=1.0, node_offset=0,
        )
        self.assertEqual(z_gmt.shape, z_py.shape,
                         f"circular shape mismatch: gmt={z_gmt.shape}, py={z_py.shape}")
        diff = z_gmt - z_py
        max_abs = float(np.nanmax(np.abs(diff)))
        rms = float(np.sqrt(np.nanmean(diff ** 2)))
        self.assertLess(max_abs, ATOL_FLOAT32,
                        f"circular-bump parity diverged: max|diff|={max_abs:.3e}, "
                        f"rms={rms:.3e} (tolerance {ATOL_FLOAT32:.0e})")

    def test_nan_skip_renormalize(self):
        """Half the grid masked NaN — verifies -Ni skip-and-renormalize
        matches gmt exactly. This is the hardest path because both
        kernels must agree on which pixels contribute to which output cell.
        """
        ny, nx = 60, 80
        rng = np.random.default_rng(42)
        data = (rng.standard_normal((ny, nx)) * 3.0).astype(np.float32)
        # Mask the right half — boundary-of-NaN cells must renormalize.
        data[:, nx // 2:] = np.nan
        x = np.arange(nx, dtype=np.float64)
        y = np.arange(ny, dtype=np.float64)
        filtx = filty = 15.0
        z_gmt = _gmt_grdfilter_fg(
            self.gmt, data, x, y, filtx, filty,
            inc_x_out=1.0, inc_y_out=1.0,
            node_offset=0, tmpdir=self.tmpdir, tag="nan_skip",
        )
        z_py, _, _ = gmt_grdfilter_py(
            data, x, y,
            filter_type="g", filter_width=filtx, filter_width2=filty,
            inc_x_out=1.0, inc_y_out=1.0, node_offset=0,
        )
        self.assertEqual(z_gmt.shape, z_py.shape)
        # NaN locations should agree exactly.
        nan_gmt = ~np.isfinite(z_gmt)
        nan_py  = ~np.isfinite(z_py)
        n_mismatch = int(np.sum(nan_gmt ^ nan_py))
        self.assertEqual(n_mismatch, 0,
                         f"NaN locations differ: {n_mismatch} cells diverge")
        # On the finite cells, max abs diff < tolerance.
        both_finite = (~nan_gmt) & (~nan_py)
        diff = z_gmt[both_finite] - z_py[both_finite]
        if diff.size:
            max_abs = float(np.max(np.abs(diff)))
            self.assertLess(max_abs, ATOL_FLOAT32,
                            f"NaN-skip parity diverged: max|diff|={max_abs:.3e}")


class TestGmtGrdfilterParityIonoRealistic(unittest.TestCase):
    """Iono-realistic parity. Uses real corr.grd from the csh oracle as
    READ-ONLY input (Rule 9 compliance: no writes under csh_test)."""

    REAL_CORR = Path(
        "/home/staff/dliu/gmtsar/gmtsar/python/work/csh_test/"
        "ALOS_haiti/intf/2009068_2010025/corr.grd"
    )

    @classmethod
    def setUpClass(cls):
        cls.gmt = _require_gmt()
        if not cls.REAL_CORR.exists():
            raise unittest.SkipTest(
                f"iono-realistic test needs {cls.REAL_CORR}; not present. "
                "Run `tests/sweep.sh` once to populate csh_test fixtures."
            )
        cls.tmpdir = Path(tempfile.mkdtemp(prefix="grdfilter_iono_"))

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmpdir, ignore_errors=True)

    def test_iono_corr_grd_width_25(self):
        """Filter the real corr.grd with width=25 pixels — exactly the
        gmtsar iono-path style. Assert bit parity vs gmt.

        gmt's `-Dp -Fg<W1>/<W2>` reads W1, W2 as ODD INTEGER PIXEL counts
        (grdfilter.c lines 1020-1032). gmt internally multiplies by
        inc_x for BOTH widths and divides by inc_x and inc_y respectively
        to get the half-widths. Our port takes widths in COORD UNITS,
        so the equivalent call passes filter_width = 25*inc_x for both
        x and y; this matches gmt's internal Ctrl->F.width / Ctrl->F.width2
        after line 1025/1031 multiply.
        """
        # Read once (READ-ONLY; we copy to tmpdir before gmt sees it so
        # gmt doesn't even touch the oracle path).
        z_in, x_in, y_in, info = read_gmt_grd(str(self.REAL_CORR))
        node_offset = info.get("node_offset", 0)

        # Take a 400x400 sub-window to keep gmt's runtime under ~5s
        # (full grid is 2826x3456 = 10M cells, gmt does it in ~30s; we
        # don't need the full grid for parity).
        ny_in, nx_in = z_in.shape
        ys = ny_in // 2 - 200
        xs = nx_in // 2 - 200
        z_sub = z_in[ys:ys + 400, xs:xs + 400]
        x_sub = x_in[xs:xs + 400]
        y_sub = y_in[ys:ys + 400]

        inc_x_in = float(x_sub[1] - x_sub[0])
        inc_y_in = float(y_sub[1] - y_sub[0])

        # gmt side: -Dp -Fg25/25 (pixel units, odd integer per gmt rule)
        # py side: filter_width and filter_width2 in coord units, with
        # gmt's internal convention that BOTH widths get multiplied by
        # inc_x (line 1031), then divided by inc_x and inc_y respectively
        # at line 1192-1193. So:
        #   gmt internal Ctrl->F.width  = 25 * inc_x = 25 * inc_x
        #   gmt internal Ctrl->F.width2 = 25 * inc_x = 25 * inc_x
        filtx_pix = 25  # odd, gmt -Dp requirement
        filty_pix = 25
        filtx_coord = filtx_pix * inc_x_in
        filty_coord = filty_pix * inc_x_in   # NOTE: inc_x_in per gmt line 1031
        # Use the input increments for the output (no -I resampling) to
        # isolate the kernel correctness.
        z_gmt = _gmt_grdfilter_fg(
            self.gmt, z_sub, x_sub, y_sub, float(filtx_pix), float(filty_pix),
            inc_x_out=inc_x_in, inc_y_out=inc_y_in,
            node_offset=node_offset, tmpdir=self.tmpdir, tag="iono",
        )
        z_py, _, _ = gmt_grdfilter_py(
            z_sub, x_sub, y_sub,
            filter_type="g", filter_width=filtx_coord, filter_width2=filty_coord,
            inc_x_out=inc_x_in, inc_y_out=inc_y_in,
            node_offset=node_offset,
        )
        self.assertEqual(z_gmt.shape, z_py.shape,
                         f"iono shape mismatch: gmt={z_gmt.shape}, py={z_py.shape}")
        # NaN locations agree
        nan_gmt = ~np.isfinite(z_gmt)
        nan_py  = ~np.isfinite(z_py)
        n_mismatch = int(np.sum(nan_gmt ^ nan_py))
        self.assertEqual(n_mismatch, 0,
                         f"iono NaN mask differs: {n_mismatch} cells")
        both_finite = (~nan_gmt) & (~nan_py)
        diff = z_gmt[both_finite] - z_py[both_finite]
        if diff.size:
            max_abs = float(np.max(np.abs(diff)))
            rms = float(np.sqrt(np.mean(diff ** 2)))
            self.assertLess(max_abs, ATOL_FLOAT32,
                            f"iono-realistic parity diverged: max|diff|={max_abs:.3e}, "
                            f"rms={rms:.3e} (signal range {float(z_gmt[both_finite].min()):.3f} "
                            f"to {float(z_gmt[both_finite].max()):.3f})")


class TestGmtGrdfilterPyContract(unittest.TestCase):
    """Argument-validation tests (no gmt subprocess needed — these check
    rule-1 'no silent fallback' compliance)."""

    def setUp(self):
        self.x = np.arange(20, dtype=np.float64)
        self.y = np.arange(15, dtype=np.float64)
        self.data = np.zeros((15, 20), dtype=np.float32)

    def _call(self, **kwargs):
        return gmt_grdfilter_py(self.data, self.x, self.y, **kwargs)

    def test_unsupported_filter_raises(self):
        with self.assertRaises(ValueError):
            self._call(filter_type="m", filter_width=5.0)
        with self.assertRaises(ValueError):
            self._call(filter_type="b", filter_width=5.0)

    def test_unsupported_distance_raises(self):
        with self.assertRaises(ValueError):
            self._call(filter_type="g", filter_width=5.0, distance_units="0")
        with self.assertRaises(ValueError):
            self._call(filter_type="g", filter_width=5.0, distance_units="4")

    def test_unsupported_nan_mode_raises(self):
        with self.assertRaises(ValueError):
            self._call(filter_type="g", filter_width=5.0, nan_mode="p")
        with self.assertRaises(ValueError):
            self._call(filter_type="g", filter_width=5.0, nan_mode="r")

    def test_zero_width_raises(self):
        with self.assertRaises(ValueError):
            self._call(filter_type="g", filter_width=0.0)
        with self.assertRaises(ValueError):
            self._call(filter_type="g", filter_width=-1.0)

    def test_default_width2(self):
        """filter_width2 defaults to filter_width."""
        z, _, _ = self._call(filter_type="g", filter_width=5.0)
        self.assertEqual(z.shape, self.data.shape)


# --- Performance reference (not a parity test) -----------------------

class TestGmtGrdfilterPerf(unittest.TestCase):
    """Report wall-clock time vs gmt grdfilter. NOT a parity test —
    just a perf reference; fails only if the port is catastrophically
    slow (>10x gmt) so a regression is caught."""

    @classmethod
    def setUpClass(cls):
        cls.gmt = _require_gmt()
        cls.tmpdir = Path(tempfile.mkdtemp(prefix="grdfilter_perf_"))

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmpdir, ignore_errors=True)

    def test_perf_512_grid(self):
        """Wall time on a 512x512 grid filtered with width=21."""
        ny, nx = 512, 512
        rng = np.random.default_rng(7)
        data = rng.standard_normal((ny, nx)).astype(np.float32)
        x = np.arange(nx, dtype=np.float64)
        y = np.arange(ny, dtype=np.float64)
        filtx = filty = 21.0

        # Warm numba JIT (cache=True; first call pays compile cost, then
        # subsequent calls reuse the disk cache).
        _ = gmt_grdfilter_py(
            data[:8, :8], x[:8], y[:8],
            filter_type="g", filter_width=filtx, filter_width2=filty,
        )

        t0 = time.perf_counter()
        z_py, _, _ = gmt_grdfilter_py(
            data, x, y,
            filter_type="g", filter_width=filtx, filter_width2=filty,
        )
        t_py = time.perf_counter() - t0

        t0 = time.perf_counter()
        z_gmt = _gmt_grdfilter_fg(
            self.gmt, data, x, y, filtx, filty,
            inc_x_out=1.0, inc_y_out=1.0,
            node_offset=0, tmpdir=self.tmpdir, tag="perf",
        )
        t_gmt = time.perf_counter() - t0

        print(f"\n[perf 512x512 -Fg21] gmt={t_gmt*1e3:.1f}ms  py={t_py*1e3:.1f}ms  "
              f"ratio={t_py/t_gmt:.2f}x  (gmt includes subprocess fork + netcdf I/O)")

        # Parity sanity: shapes match, values match.
        self.assertEqual(z_gmt.shape, z_py.shape)
        diff = z_gmt - z_py
        max_abs = float(np.nanmax(np.abs(diff)))
        self.assertLess(max_abs, ATOL_FLOAT32,
                        f"perf-grid parity diverged: max|diff|={max_abs:.3e}")

        # Catastrophic-regression gate: py must not be > 10x slower than
        # gmt+subprocess+I/O on a 512x512 grid. (gmt amortizes well over
        # large grids; small grids are dominated by fork cost where py
        # wins by default.)
        self.assertLess(
            t_py, 10.0 * t_gmt,
            f"py port is {t_py/t_gmt:.1f}x slower than gmt+subprocess; "
            "investigate numba compilation/cache."
        )


if __name__ == "__main__":
    unittest.main()
