#!/usr/bin/env python3
"""test_gmtsar_lib_run — regression test for project_rules.md Rule 1:

    "gmtsar_lib.run() raises on rc=127 (command not found). Do not
    weaken this."

rc=127 means the shell couldn't even find the command (per POSIX shell
convention) -- never a benign gmtsar-binary warning, so it must fail
loudly instead of printing WARN and letting the pipeline march on with
no work done.
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

_UTILS = Path(__file__).resolve().parent.parent.parent / "utils"
sys.path.insert(0, str(_UTILS))

from gmtsar_lib import run  # noqa: E402


class TestRunRaisesOn127(unittest.TestCase):
    def test_command_not_found_raises(self):
        with self.assertRaises(RuntimeError):
            run("this_command_definitely_does_not_exist_xyz123")

    def test_other_nonzero_rc_does_not_raise(self):
        # rc=1 (or any non-127 non-zero) stays lenient -- only prints WARN.
        run("false")  # rc=1; must not raise


if __name__ == "__main__":
    unittest.main(verbosity=2)
