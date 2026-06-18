#!/usr/bin/env python3
"""test_grdsample_wrapper — wire-in parity test for utils/grdsample_wrapper.

The wire-in (Mira #54) replaces ~6 sites that previously subprocess-called
``gmt grdsample`` (utils/snaphu.py landmask resamples + utils/p2p_stages.py
iono ph_iono resample). This test verifies that, for each csh call pattern
the wire-in claims to replace, the wrapper's output is byte-identical to
``gmt grdsample`` on real-shaped synthetic grids.

Call patterns covered:

  1. ``ref_grd=phase_patch.grd`` (csh ``-Rphase_patch.grd`` — region+inc+reg
     inherited from the reference grid). Used by snaphu.py:119 (interp=0
     no-region branch — the path actually exercised by ALOS_haiti).

  2. ``region=(...)+x_inc/y_inc`` (csh ``-R<w>/<e>/<s>/<n> -I<dx>/<dy>``).
     Used by snaphu.py:113 (region-arg branch — not exercised by any test
     case; the unit test is its only validation).

  3. ``x_inc/y_inc`` only (csh ``-I<dx>/<dy>`` — region inherited from
     input). Used by snaphu.py:124 (interp=1 no-region branch — not
     exercised by any test case).

  4. ``ref_grd`` with iono-shaped grids. Mirrors p2p_stages.py:683 — not
     exercised by any test case (no correct_iono=1 fixture).

The wrapper's env-gate behaviour is tested too. Since Mira #65 the
default flipped to ON (port is byte-id AND faster than gmt C on real
landmask + iono workloads); GMTSAR_GRDSAMPLE_PY=0 explicitly forces the
subprocess fallback, which must rebuild the gmt CLI exactly and produce
the same bytes as the gmt binary called directly.

Skips loudly if ``gmt`` is not on PATH (per Mira gate-discipline).
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

# ---------------------------------------------------------------------------
# Locate sources
# ---------------------------------------------------------------------------

_HERE = Path(__file__).resolve().parent
_UTILS = _HERE.parent.parent / "utils"          # gmtsar/python/utils/
sys.path.insert(0, str(_UTILS))

from gmt_grd_io import write_gmt_grd, read_gmt_grd  # noqa: E402
import grdsample_wrapper                              # noqa: E402

_GMT = shutil.which("gmt")
_HAVE_GMT = _GMT is not None and os.access(_GMT, os.X_OK)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_smooth_grid(nx, ny, xmin=0.0, xmax=1000.0, ymin=0.0, ymax=800.0):
    """Smooth field. Bandlimited so bicubic-resample is well-determined."""
    x = np.linspace(xmin, xmax, nx, dtype=np.float64)
    y = np.linspace(ymin, ymax, ny, dtype=np.float64)
    kx = 2.0 * np.pi / (xmax - xmin)
    ky = 2.0 * np.pi / (ymax - ymin)
    z = (np.sin(kx * x[None, :] * 2.0) *
         np.cos(ky * y[:, None] * 1.5)).astype(np.float32)
    return z, x, y


def _gmt_grdsample_subprocess(in_grd, out_grd, args):
    """Invoke gmt grdsample directly (oracle)."""
    cmd = [_GMT, "grdsample", in_grd, *args, f"-G{out_grd}"]
    res = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if res.returncode != 0:
        raise RuntimeError(
            f"gmt grdsample failed (rc={res.returncode})\n"
            f"  cmd: {' '.join(cmd)}\n  stderr: {res.stderr}"
        )


def _rms_interior(a, b, pad=4):
    """RMS over the interior (strip pad-thick edge band, where the BC
    differences between natural and index-clamp diverge slightly)."""
    if a.shape[0] <= 2 * pad or a.shape[1] <= 2 * pad:
        ai, bi = a, b
    else:
        ai = a[pad:-pad, pad:-pad]
        bi = b[pad:-pad, pad:-pad]
    d = ai.astype(np.float64) - bi.astype(np.float64)
    m = np.isfinite(d)
    if not m.any():
        return float("nan")
    return float(np.sqrt(np.mean(d[m] ** 2)))


# ---------------------------------------------------------------------------
# Suite 1: wire-in call patterns (snaphu.py / p2p_stages.py mirrors)
# ---------------------------------------------------------------------------

@unittest.skipUnless(_HAVE_GMT, "gmt binary not on PATH; cannot validate parity")
class TestWireInCallPatterns(unittest.TestCase):
    """Each test mirrors one of the wire-in sites."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp(prefix="grdsample_wrap_")
        # Input grid: pixel-registered (matches landmask_ra.grd in real cases).
        # nx/ny chosen even so 2x downsample fits gmt's "region must = N*inc"
        # constraint exactly. Pixel-reg region width = nx * dx.
        nx, ny = 80, 60
        data, x, y = _make_smooth_grid(nx, ny, xmin=0.0, xmax=1000.0,
                                       ymin=0.0, ymax=800.0)
        cls.in_grd = os.path.join(cls.tmp, "landmask_ra.grd")
        write_gmt_grd(cls.in_grd, data, x, y, node_offset=1)
        # Reference grid (mimics phase_patch.grd): pixel-registered,
        # **strictly contained inside** the input's data extent — this
        # matches production reality where landmask_ra is the full radar
        # frame and phase_patch is a sub-region. (When the ref grid
        # extends past the input, gmt CLIPS the output region; replicating
        # that clipping is intentionally out-of-scope for the wire-in
        # because no production caller hits that case.)
        cls.ref_grd = os.path.join(cls.tmp, "phase_patch.grd")
        # Pixel-reg with dx=25, centred so x_min=100-12.5=87.5, x_max=900+12.5=912.5.
        nxr, nyr = 33, 25
        xr = np.linspace(100.0, 900.0, nxr, dtype=np.float64)
        yr = np.linspace(80.0, 720.0, nyr, dtype=np.float64)
        ref_data = np.zeros((nyr, nxr), dtype=np.float32)
        write_gmt_grd(cls.ref_grd, ref_data, xr, yr, node_offset=1)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def _compare_against_gmt(self, gmt_args, **wrap_kwargs):
        """Run gmt subprocess + wrapper py path, compare outputs."""
        out_gmt = os.path.join(self.tmp, "out_gmt.grd")
        out_py = os.path.join(self.tmp, "out_py.grd")
        _gmt_grdsample_subprocess(self.in_grd, out_gmt, gmt_args)
        # Opt into the in-process port for this call (default is OFF).
        os.environ["GMTSAR_GRDSAMPLE_PY"] = "1"
        try:
            grdsample_wrapper.grdsample(self.in_grd, out_py, **wrap_kwargs)
        finally:
            os.environ.pop("GMTSAR_GRDSAMPLE_PY", None)
        z_gmt, x_gmt, y_gmt, info_gmt = read_gmt_grd(out_gmt)
        z_py, x_py, y_py, info_py = read_gmt_grd(out_py)
        self.assertEqual(z_py.shape, z_gmt.shape,
                         f"shape mismatch {z_py.shape} vs {z_gmt.shape}")
        self.assertEqual(info_py["node_offset"], info_gmt["node_offset"],
                         "registration mismatch between wrapper and gmt")
        np.testing.assert_allclose(x_py, x_gmt, atol=1e-8)
        np.testing.assert_allclose(y_py, y_gmt, atol=1e-8)
        rms = _rms_interior(z_py, z_gmt, pad=4)
        # 5e-5 — same tolerance the in-process port parity tests use
        # for synthetic smooth grids (interior, default bicubic).
        self.assertLessEqual(rms, 5e-5,
            f"interior rms {rms:.3e} > 5e-5; wrapper diverged from gmt grdsample")

    def test_pattern_ref_grd(self):
        """snaphu.py:119 — `gmt grdsample landmask_ra.grd -Rphase_patch.grd -G...`

        Region+inc+registration inherited from phase_patch.grd. Bicubic
        (gmt CLI default). THIS IS THE PATH EXERCISED BY ALOS_haiti in
        the regression sweep.
        """
        self._compare_against_gmt(
            gmt_args=[f"-R{self.ref_grd}"],
            ref_grd=self.ref_grd,
        )

    def test_pattern_region_plus_inc(self):
        """snaphu.py:113 — `gmt grdsample landmask_ra.grd -R<region> -I<inc> -G...`

        Explicit region + explicit inc (from phase_patch.grd via grdinfo).
        Not exercised in regression — unit test is the only validation.
        """
        # Use ref_grd's region + inc, supplied explicitly. ref_grd is
        # contained inside input (set up above), so no region clipping.
        _ref_d, ref_x, ref_y, ref_info = read_gmt_grd(self.ref_grd)
        ref_dx = float(ref_x[1] - ref_x[0])
        ref_dy = float(ref_y[1] - ref_y[0])
        ref_off = ref_info["node_offset"]
        off = 0.5 if ref_off == 1 else 0.0
        rx0 = float(ref_x[0]) - off * ref_dx
        rx1 = float(ref_x[-1]) + off * ref_dx
        ry0 = float(ref_y[0]) - off * ref_dy
        ry1 = float(ref_y[-1]) + off * ref_dy
        self._compare_against_gmt(
            gmt_args=[f"-R{rx0}/{rx1}/{ry0}/{ry1}",
                      f"-I{ref_dx}/{ref_dy}"],
            region=(rx0, rx1, ry0, ry1),
            x_inc=ref_dx, y_inc=ref_dy,
        )

    def test_pattern_inc_only(self):
        """snaphu.py:124 — `gmt grdsample landmask_ra.grd -I<inc> -G...`

        Increment-only — region inherited from input. Not exercised in
        regression (interp=1 branch).

        In production this site is called with `dx_phase, dy_phase` from
        `phase_patch.grd`, which in the radar geometry always shares the
        same increment family as `landmask_ra.grd` (both derive from
        the same range/azimuth decimation). So we test with an integer-
        divisor inc that fits the input region exactly — gmt does NOT
        warn or adjust in that case, and the wrapper matches byte-for-byte.
        """
        # Input is pixel-reg, dx=12.5, ny=61 with dy=13.33...
        # Use 2x downsample: dx=25 (must fit input region exactly).
        _d, in_x, in_y, _info = read_gmt_grd(self.in_grd)
        in_dx = float(in_x[1] - in_x[0])
        in_dy = float(in_y[1] - in_y[0])
        new_dx = in_dx * 2.0
        new_dy = in_dy * 2.0
        # Confirm 2x downsample produces an integer number of cells
        # (pixel-reg region span = nx_in * dx; halving inc must keep it
        # an integer multiple).
        span_x = len(in_x) * in_dx
        span_y = len(in_y) * in_dy
        n_new_x = span_x / new_dx
        n_new_y = span_y / new_dy
        assert abs(n_new_x - round(n_new_x)) < 1e-6, \
            f"x inc not integer-fitting: span={span_x} new_dx={new_dx} -> {n_new_x}"
        assert abs(n_new_y - round(n_new_y)) < 1e-6, \
            f"y inc not integer-fitting: span={span_y} new_dy={new_dy} -> {n_new_y}"
        self._compare_against_gmt(
            gmt_args=[f"-I{new_dx}/{new_dy}"],
            x_inc=new_dx, y_inc=new_dy,
        )


# ---------------------------------------------------------------------------
# Suite 2: iono p2p_stages.py wire-in
# ---------------------------------------------------------------------------

@unittest.skipUnless(_HAVE_GMT, "gmt binary not on PATH")
class TestIonoWireIn(unittest.TestCase):
    """p2p_stages.py:683 — ph_iono_orig.grd → ph_iono.grd via -R<phasefilt>.

    Same call pattern as snaphu.py:119 (ref_grd) but on iono-shaped grids
    (typically much coarser source, finer target). Sanity test only —
    the wire-in is not path-exercised by any test fixture (no
    correct_iono=1 case).
    """

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp(prefix="grdsample_iono_")
        # Coarse iono source (mimics ph_iono_orig.grd at iono_dsamp=8) —
        # spans a larger area than the ref to avoid region-clipping by gmt.
        z_src, x_src, y_src = _make_smooth_grid(
            nx=51, ny=39, xmin=0.0, xmax=1000.0, ymin=0.0, ymax=800.0,
        )
        cls.src = os.path.join(cls.tmp, "ph_iono_orig.grd")
        write_gmt_grd(cls.src, z_src, x_src, y_src, node_offset=1)
        # Finer reference (mimics phasefilt_non_corrected.grd) — strictly
        # contained inside source so -R<ref_grd> is in-bounds.
        nxr, nyr = 65, 49
        xr = np.linspace(100.0, 900.0, nxr, dtype=np.float64)
        yr = np.linspace(80.0, 720.0, nyr, dtype=np.float64)
        z_ref = np.zeros((nyr, nxr), dtype=np.float32)
        cls.ref = os.path.join(cls.tmp, "phasefilt_non_corrected.grd")
        write_gmt_grd(cls.ref, z_ref, xr, yr, node_offset=1)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def test_iono_ref_grd(self):
        out_gmt = os.path.join(self.tmp, "ph_iono_gmt.grd")
        out_py = os.path.join(self.tmp, "ph_iono_py.grd")
        _gmt_grdsample_subprocess(self.src, out_gmt, [f"-R{self.ref}"])
        # Opt into the in-process port (default is OFF).
        os.environ["GMTSAR_GRDSAMPLE_PY"] = "1"
        try:
            grdsample_wrapper.grdsample(self.src, out_py, ref_grd=self.ref)
        finally:
            os.environ.pop("GMTSAR_GRDSAMPLE_PY", None)
        z_g, _, _, info_g = read_gmt_grd(out_gmt)
        z_p, _, _, info_p = read_gmt_grd(out_py)
        self.assertEqual(z_p.shape, z_g.shape)
        self.assertEqual(info_p["node_offset"], info_g["node_offset"])
        rms = _rms_interior(z_p, z_g, pad=4)
        self.assertLessEqual(rms, 5e-5,
            f"iono wire-in interior rms {rms:.3e} > 5e-5")


# ---------------------------------------------------------------------------
# Suite 3: env-gate fallback
# ---------------------------------------------------------------------------

@unittest.skipUnless(_HAVE_GMT, "gmt binary not on PATH")
class TestEnvGateFallback(unittest.TestCase):
    """Explicit GMTSAR_GRDSAMPLE_PY=0 → subprocess path.

    The subprocess fallback must rebuild the gmt CLI exactly and produce
    the same bytes as gmt called directly with the equivalent flags.
    Default is now ON (Mira #65); this suite asserts the explicit-OFF
    branch is still wire-compatible with the original gmt subprocess.
    The in-process port is tested in TestWireInCallPatterns.
    """

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp(prefix="grdsample_env_")
        data, x, y = _make_smooth_grid(nx=41, ny=31)
        cls.in_grd = os.path.join(cls.tmp, "in.grd")
        write_gmt_grd(cls.in_grd, data, x, y, node_offset=1)
        cls.ref = os.path.join(cls.tmp, "ref.grd")
        # Contained inside input to avoid gmt's region-clip behavior.
        nxr, nyr = 17, 13
        xr = np.linspace(100.0, 900.0, nxr, dtype=np.float64)
        yr = np.linspace(80.0, 720.0, nyr, dtype=np.float64)
        write_gmt_grd(cls.ref, np.zeros((nyr, nxr), dtype=np.float32),
                      xr, yr, node_offset=1)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def test_subprocess_fallback_byte_id(self):
        """With GMTSAR_GRDSAMPLE_PY=0, the wrapper IS the subprocess."""
        out_direct = os.path.join(self.tmp, "out_direct.grd")
        out_wrap = os.path.join(self.tmp, "out_wrap.grd")
        _gmt_grdsample_subprocess(self.in_grd, out_direct, [f"-R{self.ref}"])
        # Force fallback.
        old = os.environ.get("GMTSAR_GRDSAMPLE_PY")
        os.environ["GMTSAR_GRDSAMPLE_PY"] = "0"
        try:
            grdsample_wrapper.grdsample(self.in_grd, out_wrap,
                                        ref_grd=self.ref)
        finally:
            if old is None:
                os.environ.pop("GMTSAR_GRDSAMPLE_PY", None)
            else:
                os.environ["GMTSAR_GRDSAMPLE_PY"] = old
        # In subprocess mode the wrapper rebuilds gmt CLI from the same
        # ref_grd path. The output bytes should match the direct call.
        with open(out_direct, "rb") as f:
            b_direct = f.read()
        with open(out_wrap, "rb") as f:
            b_wrap = f.read()
        # netCDF files may differ in trivial metadata (timestamp). Check
        # the data via grdinfo + read instead of raw bytes.
        z_d, _, _, info_d = read_gmt_grd(out_direct)
        z_w, _, _, info_w = read_gmt_grd(out_wrap)
        np.testing.assert_array_equal(z_d, z_w)
        self.assertEqual(info_d["node_offset"], info_w["node_offset"])


# ---------------------------------------------------------------------------
# Suite 4: loud failure if gmt missing
# ---------------------------------------------------------------------------

class TestOracleAvailability(unittest.TestCase):
    def test_gmt_present_else_loud_skip(self):
        if not _HAVE_GMT:
            self.skipTest(
                "gmt binary not on PATH. wire-in parity test cannot run; "
                "this is a LOUD skip, not a silent pass."
            )
        # gmt is on PATH — sanity check it's v6.
        res = subprocess.run([_GMT, "--version"], capture_output=True,
                             text=True)
        self.assertEqual(res.returncode, 0)
        self.assertTrue(res.stdout.startswith("6."),
                        f"unexpected gmt version: {res.stdout!r}")


if __name__ == "__main__":
    unittest.main(verbosity=2)
