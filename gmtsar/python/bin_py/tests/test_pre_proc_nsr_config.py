#!/usr/bin/env python3
"""test_pre_proc_nsr_config — regression guard for _get_config() quote-stripping.

Found 2026-07-13 via a real end-to-end NISAR_Ethiopia sweep with
GMTSAR_NSR_PREPROC_PY=1 (not caught by the isolated make_slc_nsr_py.py
parity test, which never exercises this config-parsing code at all):
staged config.py values are Python string literals
(region_cut = '18000/23000/47000/53000'), and _get_config()'s naive
line.split() returned the value WITH its surrounding quote characters
still attached. The C dispatch path never noticed -- subprocess/shell
quoting silently stripped the quotes before the C binary saw its argv.
The in-process Python path has no shell in between, so the literal
leading quote broke get_range()'s _atoi() (C atoi() semantics: stops at
the first non-digit character, returns 0) -- xl silently became 0
instead of 18000, corrupting every downstream SLC/PRM dimension
(observed: num_rng_bins 23000 instead of 5000, a 4.6x-too-wide SLC).
"""
from __future__ import annotations

import importlib.util as _ilu
import importlib.machinery as _ilm
import sys
import tempfile
import unittest
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_UTILS_DIR = _HERE.parent.parent / "utils"
_MOD_PATH = _UTILS_DIR / "pre_proc_nsr"
if str(_UTILS_DIR) not in sys.path:
    sys.path.insert(0, str(_UTILS_DIR))

_spec = _ilu.spec_from_loader(
    "pre_proc_nsr_mod",
    _ilm.SourceFileLoader("pre_proc_nsr_mod", str(_MOD_PATH)),
)
_MOD = _ilu.module_from_spec(_spec)
sys.modules["pre_proc_nsr_mod"] = _MOD
_spec.loader.exec_module(_MOD)
_get_config = _MOD._get_config


class TestGetConfigQuoteStripping(unittest.TestCase):
    def _write_and_read(self, line: str, key: str):
        with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False) as f:
            f.write(line + "\n")
            path = f.name
        try:
            return _get_config(path, key)
        finally:
            Path(path).unlink()

    def test_single_quoted_value_is_stripped(self):
        val = self._write_and_read(
            "region_cut             = '18000/23000/47000/53000'", "region_cut")
        self.assertEqual(val, "18000/23000/47000/53000")
        # This is the actual bug's failure mode: a leading quote character
        # breaks C-atoi-style digit parsing and silently yields 0.
        self.assertTrue(val[0].isdigit(), "leading char must be a digit, not a quote")

    def test_double_quoted_value_is_stripped(self):
        val = self._write_and_read('SLC_factor = "1.0"', "SLC_factor")
        self.assertEqual(val, "1.0")

    def test_unquoted_value_passes_through(self):
        val = self._write_and_read("SLC_factor = 1.0", "SLC_factor")
        self.assertEqual(val, "1.0")

    def test_missing_key_returns_default(self):
        val = self._write_and_read("other_key = 'x'", "region_cut")
        self.assertEqual(val, "")

    def test_region_cut_parses_to_correct_xl_after_stripping(self):
        """End-to-end regression for the actual observed failure: xl must
        be 18000, not 0, after going through _get_config -> get_range."""
        nsr_spec = _ilu.spec_from_loader(
            "make_slc_nsr_py_mod",
            _ilm.SourceFileLoader("make_slc_nsr_py_mod",
                                   str(_HERE.parent.parent / "utils" / "make_slc_nsr_py.py")),
        )
        nsr_mod = _ilu.module_from_spec(nsr_spec)
        nsr_spec.loader.exec_module(nsr_mod)

        raw = self._write_and_read(
            "region_cut = '18000/23000/47000/53000'", "region_cut")
        xl, xh, yl, yh = nsr_mod.get_range(raw)
        self.assertEqual((xl, xh, yl, yh), (18000, 23000, 47000, 53000))
        self.assertEqual(xh - xl, 5000, "width must be 5000, not 23000 (the observed bug)")


if __name__ == "__main__":
    unittest.main()
