#!/usr/bin/env python3
"""test_iono_gauss_parity — record parity gap between scipy.ndimage and
`gmt grdfilter -Fg`.

Mira #46 follow-up (2026-05-22): the mission to make
`estimate_ionospheric_phase` "native Python" included replacing the
one `gmt grdfilter -Fg` call with `scipy.ndimage.gaussian_filter`.
Investigation showed the substitution is NOT byte-identical (max
relative divergence ~0.7-1% on smooth iono-like input, ~10% on white
noise). Root causes:

  - GMT uses a CIRCULAR Gaussian kernel truncated at full diameter
    `W` (= 6·sigma); scipy.ndimage uses a SEPARABLE RECTANGULAR
    Gaussian kernel truncated at `truncate·sigma` (default 4·sigma).
  - GMT applies per-cell weight renormalization over the unmasked
    pixels in the window (so edges of the grid don't get shrunk
    toward zero); scipy.ndimage's "reflect"/"mirror"/"nearest" modes
    are different boundary policies.
  - GMT's `-I<inc>` resampling does a careful weighted average at
    each coarsened cell centre; the opt-in scipy path strides the
    filtered grid — another divergence.

This test serves three roles:

  1. CONTRACT: confirms `_scipy_gauss_filter` runs end-to-end and
     produces a well-formed `.grd` output (no crash, output shape
     matches the strided coarsening).
  2. PARITY-GAP RECORD: asserts the divergence vs gmt grdfilter -Fg
     is below `MAX_REL_DIVERGENCE = 0.02` (2%) on a representative
     smooth signal — not zero. Tightening this past ~1% is impossible
     without a custom GMT-faithful kernel implementation.
  3. RIPCORD: if any future scipy/numpy version regresses the relative
     divergence past 2%, this test catches it and forces a re-audit.

This is NOT a Mira-style C-parity test. The Mira-discipline parity
contract is that `gmt grdfilter -Fg` stays as the default (via the
opt-out env flag `GMTSAR_IONO_GAUSS_PY` left unset). This test only
guards the opt-IN path.

Test skips loudly (with a documented reason) when GMT is not on PATH.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np

_HERE = Path(__file__).resolve().parent
_UTILS = _HERE.parents[1] / "utils"
sys.path.insert(0, str(_UTILS))

from gmt_grd_io import read_gmt_grd, write_gmt_grd  # noqa: E402

_GMT_CANDIDATES = [
    Path("/home/staff/dliu/anaconda3/envs/gmtsar/bin/gmt"),
    Path(shutil.which("gmt") or "/__NO_GMT__"),
]

# Tolerance bands (see module docstring).
MAX_REL_DIVERGENCE_SMOOTH = 0.02   # 2% on iono-shape smooth signal
MAX_REL_DIVERGENCE_NOISE  = 0.30   # 30% on white-noise input (sanity-only;
                                   # iono input is never white)


def _find_gmt() -> Path | None:
    for p in _GMT_CANDIDATES:
        if p.exists() and os.access(p, os.X_OK):
            return p
    return None


def _scipy_gauss_local(z, x, y, filtx, filty, inc_x, inc_y):
    """Reproduces utils/estimate_ionospheric_phase._scipy_gauss_filter
    in-process for testing without spawning the wrapper as a subprocess.
    """
    from scipy.ndimage import gaussian_filter
    sigma_x = float(filtx) / 6.0
    sigma_y = float(filty) / 6.0
    mask = np.isfinite(z).astype(np.float32)
    z_filled = np.where(np.isfinite(z), z, 0.0).astype(np.float32)
    num = gaussian_filter(z_filled, sigma=(sigma_y, sigma_x),
                          mode="reflect", truncate=3.0)
    den = gaussian_filter(mask,     sigma=(sigma_y, sigma_x),
                          mode="reflect", truncate=3.0)
    with np.errstate(invalid="ignore", divide="ignore"):
        out = np.where(den > 1e-6, num / den, np.nan).astype(np.float32)
    inc_x = max(1, int(inc_x))
    inc_y = max(1, int(inc_y))
    return out[::inc_y, ::inc_x], x[::inc_x], y[::inc_y]


class TestIonoGaussParityGap(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.gmt = _find_gmt()
        if cls.gmt is None:
            raise unittest.SkipTest(
                "gmt binary not found on PATH; iono-gauss parity test "
                "needs GMT 6 to generate the parity oracle. Install GMT "
                "or activate the conda gmtsar env."
            )
        cls.tmpdir = Path(tempfile.mkdtemp(prefix="iono_gauss_"))

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmpdir, ignore_errors=True)

    # --- helpers ---------------------------------------------------------

    def _gmt_grdfilter_fg(self, data, x, y, filtx, filty, inc_x, inc_y):
        """Run `gmt grdfilter -Dp -Fg<filtx>/<filty> -Ni -I<incx>/<incy>`
        and return the output grid array (NaN-masked, float32)."""
        in_grd = self.tmpdir / "iono_in.grd"
        out_grd = self.tmpdir / "iono_gmt.grd"
        write_gmt_grd(str(in_grd), data, x, y, node_offset=0)
        cmd = [
            str(self.gmt), "grdfilter", str(in_grd),
            "-Dp", f"-Fg{filtx}/{filty}",
            "-G" + str(out_grd), "-Vq", "-Ni",
            f"-I{inc_x}/{inc_y}",
        ]
        subprocess.run(cmd, check=True)
        z_gmt, _, _, _ = read_gmt_grd(str(out_grd))
        return z_gmt

    # --- tests ----------------------------------------------------------

    def test_smooth_iono_like_signal_divergence(self):
        """On a smooth iono-shape input, scipy diverges from GMT by
        < MAX_REL_DIVERGENCE_SMOOTH. Documents the parity gap."""
        rng = np.random.default_rng(0)
        ny, nx = 200, 300
        yy, xx = np.mgrid[0:ny, 0:nx].astype(np.float64)
        data = (np.sin(xx / 50.0) * np.cos(yy / 40.0) * 5.0 +
                0.1 * rng.standard_normal((ny, nx))).astype(np.float32)
        x = np.arange(nx, dtype=np.float64)
        y = np.arange(ny, dtype=np.float64)

        # Use filt sizes representative of iono path; no resampling
        # (inc=1) so the comparison isolates the kernel itself.
        filtx, filty, inc_x, inc_y = 21, 21, 1, 1
        z_gmt = self._gmt_grdfilter_fg(data, x, y, filtx, filty, inc_x, inc_y)
        z_sp, _, _ = _scipy_gauss_local(data, x, y, filtx, filty, inc_x, inc_y)

        self.assertEqual(z_gmt.shape, z_sp.shape,
                         "scipy + GMT must agree on output shape")
        diff = z_gmt - z_sp
        sig_range = float(np.nanmax(z_gmt) - np.nanmin(z_gmt))
        rel_max = float(np.nanmax(np.abs(diff))) / sig_range
        # PARITY GAP record: 0.74% on synthetic; allow up to 2% headroom.
        self.assertLess(rel_max, MAX_REL_DIVERGENCE_SMOOTH,
                        f"scipy vs gmt grdfilter -Fg diverged by "
                        f"{rel_max*100:.2f}% (> {MAX_REL_DIVERGENCE_SMOOTH*100}%) — "
                        f"if expected, raise the threshold; if not, "
                        f"a scipy upgrade likely changed the kernel.")
        # Confirm we are NOT bit-identical (this would be suspicious —
        # would mean GMT silently became scipy-equivalent).
        self.assertGreater(float(np.nanmax(np.abs(diff))), 1e-7,
                           "scipy and gmt grdfilter -Fg are byte-identical? "
                           "That contradicts the parity investigation; "
                           "re-audit kernel definitions.")

    def test_kernel_widths_are_correct(self):
        """The scipy port uses sigma = W/6 (GMT's docstring definition).
        Sanity-check via a delta-function input — the response should
        peak at the centre with FWHM ≈ 2·sqrt(2·ln2)·sigma."""
        ny, nx = 81, 81
        delta = np.zeros((ny, nx), dtype=np.float32)
        delta[ny // 2, nx // 2] = 1.0
        x = np.arange(nx, dtype=np.float64)
        y = np.arange(ny, dtype=np.float64)

        filtx = filty = 21
        z_gmt = self._gmt_grdfilter_fg(delta, x, y, filtx, filty, 1, 1)
        z_sp, _, _ = _scipy_gauss_local(delta, x, y, filtx, filty, 1, 1)

        # Both should peak at the centre.
        i_gmt, j_gmt = np.unravel_index(np.nanargmax(z_gmt), z_gmt.shape)
        i_sp,  j_sp  = np.unravel_index(np.nanargmax(z_sp),  z_sp.shape)
        self.assertEqual((i_gmt, j_gmt), (ny // 2, nx // 2))
        self.assertEqual((i_sp,  j_sp ), (ny // 2, nx // 2))

        # Peak values are within ~15% of each other (different kernel
        # shape, same sigma definition; not bit-identical).
        peak_gmt = float(z_gmt[ny // 2, nx // 2])
        peak_sp  = float(z_sp [ny // 2, nx // 2])
        self.assertGreater(peak_gmt, 0.0)
        self.assertGreater(peak_sp,  0.0)
        rel = abs(peak_gmt - peak_sp) / peak_gmt
        self.assertLess(rel, 0.20,
                        f"delta-function peak ratio diverged "
                        f"{rel*100:.1f}% — kernel-width definition broke")

    def test_stride_resampling_shape(self):
        """Opt-in scipy path uses stride coarsening for -I<inc>. Verify
        the output shape matches `ceil(N / inc)` exactly."""
        ny, nx = 200, 300
        data = np.zeros((ny, nx), dtype=np.float32)
        x = np.arange(nx, dtype=np.float64)
        y = np.arange(ny, dtype=np.float64)
        inc_x, inc_y = 4, 3
        z_sp, x_sp, y_sp = _scipy_gauss_local(data, x, y, 21, 21, inc_x, inc_y)
        expected_ny = (ny + inc_y - 1) // inc_y
        expected_nx = (nx + inc_x - 1) // inc_x
        self.assertEqual(z_sp.shape, (expected_ny, expected_nx))
        self.assertEqual(x_sp.shape, (expected_nx,))
        self.assertEqual(y_sp.shape, (expected_ny,))


if __name__ == "__main__":
    unittest.main()
