#!/usr/bin/env python3
"""test_no_dangling_module_paths — regression guard (project_rules.md Rule 8).

2026-07-13: archiving bin_py/SAT_llt2rat_py's old variant broke
bin_py/SAT_baseline_py and bin_py/tests/test_vector.py, both of which load
a sibling script via importlib.SourceFileLoader with a HARDCODED path
string, not a normal `import`. No existing test exercised SAT_baseline_py
(it's not itself a "port under test"), so nothing caught the dangling
path until a real end-to-end sweep ran SAT_baseline_py as a subprocess.

This test greps every tracked *.py / extension-less bin_py script for the
`_HERE (.parent)? / "some_name"` -> SourceFileLoader(...) pattern and
asserts the target file actually exists on disk -- so any future
git mv/archive of a file breaks this test immediately, in milliseconds,
instead of surfacing an hour into a real sweep.
"""
from __future__ import annotations

import re
import unittest
from pathlib import Path

_REPO_PY_ROOT = Path(__file__).resolve().parents[2]  # gmtsar/python/
_SCAN_DIRS = [_REPO_PY_ROOT / "bin_py", _REPO_PY_ROOT / "utils"]

# Matches: _MOD = _HERE / "name"   or   _MOD = _HERE.parent / "name"
_PATTERN = re.compile(
    r'^\s*_\w+\s*=\s*_HERE(?P<parent>\.parent)?\s*/\s*"(?P<name>[^"]+)"',
    re.MULTILINE,
)


def _iter_candidate_files():
    for d in _SCAN_DIRS:
        if not d.is_dir():
            continue
        for p in d.rglob("*"):
            if p.is_dir() or p.name.startswith("."):
                continue
            if p.suffix not in ("", ".py"):
                continue
            try:
                text = p.read_text(errors="ignore")
            except OSError:
                continue
            if "SourceFileLoader" in text or "spec_from_loader" in text:
                yield p, text


class TestNoDanglingModulePaths(unittest.TestCase):
    def test_source_file_loader_targets_exist(self):
        checked = 0
        missing = []
        for path, text in _iter_candidate_files():
            for m in _PATTERN.finditer(text):
                checked += 1
                base = path.parent if m.group("parent") else path.parent
                # _HERE is the loading file's own directory; _HERE.parent
                # is one level up from that (mirrors the two real usages:
                # bin_py/SAT_baseline_py uses _HERE directly,
                # bin_py/tests/test_vector.py uses _HERE.parent).
                if m.group("parent"):
                    base = path.parent.parent
                target = base / m.group("name")
                if not target.exists():
                    missing.append(f"{path}: SourceFileLoader target {target} does not exist")
        self.assertGreater(checked, 0, "no SourceFileLoader path patterns found -- scan is stale, update the regex")
        self.assertEqual(missing, [], "dangling hardcoded module path(s):\n" + "\n".join(missing))


if __name__ == "__main__":
    unittest.main()
