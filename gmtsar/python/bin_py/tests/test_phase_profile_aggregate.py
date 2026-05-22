#!/usr/bin/env python3
"""test_phase_profile_aggregate — unit tests for the Frame-level
phase_profile aggregator (aggregate_subswath_profiles) used by
p2p_S1_TOPS_Frame to roll up F1/F2/F3 per-subswath JSONs into a single
case-root phase_profile_py.json.

Coverage:
 - Phase wall-time uses max-of-per-subswath durations (parallel
   subswaths must not over-count to the sum of subswath durations).
 - Per-binary call counts and total_sec sum across subswaths.
 - Extra phases/binaries (Frame-level merge stage) merge in cleanly.
 - Missing subswath JSONs are tolerated.
 - No subswaths AND no extras → returns None (caller bails out).
"""
from __future__ import annotations

import importlib.util
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path


_UTILS = Path(__file__).resolve().parents[2] / "utils"
sys.path.insert(0, str(_UTILS))


def _load_phase_profile():
    """Load phase_profile.py as a fresh module each time so _PHASES /
    _BINARY_TIMES module-level state doesn't leak between tests."""
    spec = importlib.util.spec_from_file_location(
        "phase_profile_test_copy", str(_UTILS / "phase_profile.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _write_subswath(d: Path, phases, binaries):
    d.mkdir(parents=True, exist_ok=True)
    with open(d / "phase_profile_py.json", "w") as f:
        json.dump({
            "side": "py", "case": None,
            "phases": phases, "binaries": binaries,
            "total_sec": sum(p["duration_sec"] for p in phases),
        }, f)


class TestAggregateSubswathProfiles(unittest.TestCase):

    def setUp(self):
        self.mod = _load_phase_profile()
        self.aggregate = self.mod.aggregate_subswath_profiles
        self.tmp = tempfile.mkdtemp(prefix="phase_agg_")

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _make_three(self, p1_durs, bin_per_subswath):
        """Build F1/F2/F3 with P2P1_preprocess having durs p1_durs[i] and
        a single 'dem2topo_ra' binary call of bin_per_subswath[i] secs."""
        for i, (dur, b) in enumerate(zip(p1_durs, bin_per_subswath), start=1):
            d = Path(self.tmp) / f"F{i}"
            _write_subswath(
                d,
                phases=[{
                    "name": "P2P1_preprocess",
                    "duration_sec": dur,
                    "start_epoch": 1000.0 + i,  # deliberately non-overlapping
                    "end_epoch":   1000.0 + i + dur,
                }],
                binaries=[{
                    "name": "dem2topo_ra",
                    "calls": 1,
                    "total_sec": b,
                    "avg_sec": b,
                    "max_sec": b,
                }],
            )
        return [str(Path(self.tmp) / f"F{i}") for i in range(1, 4)]

    def test_phase_walltime_is_max_not_sum(self):
        # Parallel subswaths: P2P1 durations [10, 20, 30]. Aggregated wall
        # should be 30 (slowest), NOT 60 (sum).
        dirs = self._make_three([10.0, 20.0, 30.0], [5.0, 5.0, 5.0])
        out = Path(self.tmp) / "phase_profile_py.json"
        agg = self.aggregate(dirs, out_path=str(out), case="case_x")
        self.assertIsNotNone(agg)
        self.assertEqual(len(agg["phases"]), 1)
        ph = agg["phases"][0]
        self.assertEqual(ph["name"], "P2P1_preprocess")
        self.assertEqual(ph["duration_sec"], 30.0)
        self.assertEqual(ph["subswath_count"], 3)
        self.assertEqual(ph["per_subswath_sec"], [10.0, 20.0, 30.0])

    def test_binary_calls_and_total_sum(self):
        dirs = self._make_three([10.0, 20.0, 30.0], [3.0, 4.0, 5.0])
        agg = self.aggregate(dirs,
                             out_path=str(Path(self.tmp) / "phase.json"))
        bs = agg["binaries"]
        self.assertEqual(len(bs), 1)
        b = bs[0]
        self.assertEqual(b["name"], "dem2topo_ra")
        self.assertEqual(b["calls"], 3)
        self.assertEqual(b["total_sec"], 12.0)
        self.assertEqual(b["max_sec"], 5.0)
        self.assertEqual(b["avg_sec"], 4.0)

    def test_extra_phases_and_extra_binaries_merge_in(self):
        dirs = self._make_three([10.0, 20.0, 30.0], [3.0, 4.0, 5.0])
        out = Path(self.tmp) / "phase.json"
        agg = self.aggregate(
            dirs, out_path=str(out),
            extra_phases=[{"name": "frame_merge", "duration_sec": 7.5,
                           "start_epoch": 9000.0, "end_epoch": 9007.5}],
            extra_binaries={"merge_unwrap_geocode_tops": [7.4]},
        )
        names = [p["name"] for p in agg["phases"]]
        self.assertEqual(names, ["P2P1_preprocess", "frame_merge"])
        # Total = max(P2P1 across subswaths)=30 + frame_merge 7.5 = 37.5
        self.assertAlmostEqual(agg["total_sec"], 37.5, places=2)
        bnames = [b["name"] for b in agg["binaries"]]
        self.assertIn("merge_unwrap_geocode_tops", bnames)
        merge_b = next(b for b in agg["binaries"]
                       if b["name"] == "merge_unwrap_geocode_tops")
        self.assertEqual(merge_b["calls"], 1)
        self.assertEqual(merge_b["total_sec"], 7.4)

    def test_missing_subswath_json_is_tolerated(self):
        # Only F1, F2 have JSONs; F3 dir doesn't exist.
        dirs = self._make_three([10.0, 20.0, 30.0], [1.0, 1.0, 1.0])
        # Wipe F3's JSON.
        os.remove(Path(dirs[2]) / "phase_profile_py.json")
        agg = self.aggregate(
            dirs, out_path=str(Path(self.tmp) / "phase.json"))
        self.assertIsNotNone(agg)
        self.assertEqual(agg["subswaths"], ["F1", "F2"])
        # Per-subswath durations now only include F1, F2.
        ph = agg["phases"][0]
        self.assertEqual(ph["per_subswath_sec"], [10.0, 20.0])
        self.assertEqual(ph["duration_sec"], 20.0)
        # Binary calls = 2 (only F1, F2).
        self.assertEqual(agg["binaries"][0]["calls"], 2)

    def test_empty_returns_none(self):
        # No subswath JSONs, no extras → don't clobber an existing file.
        dirs = [str(Path(self.tmp) / d) for d in ("F1", "F2", "F3")]
        # No mkdir, no write.
        agg = self.aggregate(
            dirs, out_path=str(Path(self.tmp) / "should_not_exist.json"))
        self.assertIsNone(agg)
        self.assertFalse((Path(self.tmp) / "should_not_exist.json").exists())

    def test_aggregated_includes_all_phase_names(self):
        # Three subswaths each have the full P2P1..P2P6 chain. The
        # aggregator must preserve all six phases with subswath_count=3
        # and correct max-duration per phase.
        phases_template = [
            ("P2P1_preprocess",  [60.0, 70.0, 50.0]),
            ("P2P2_focus_align", [ 0.1,  0.2,  0.3]),
            ("P2P3_make_topo",   [200., 180., 220.]),
            ("P2P4_intf_filter", [ 30.,  40.,  35.]),
            ("P2P5_unwrap",      [ 0.0,  0.0,  0.0]),
            ("P2P6_geocode",     [ 0.0,  0.0,  0.0]),
        ]
        for i in range(3):
            phases = [{"name": n, "duration_sec": durs[i],
                       "start_epoch": 1.0 + i, "end_epoch": 1.0 + i + durs[i]}
                      for n, durs in phases_template]
            _write_subswath(Path(self.tmp) / f"F{i+1}", phases,
                            [{"name": "pre_proc", "calls": 1,
                              "total_sec": 50.0 + i, "avg_sec": 50.0 + i,
                              "max_sec": 50.0 + i}])
        dirs = [str(Path(self.tmp) / f"F{i}") for i in range(1, 4)]
        agg = self.aggregate(dirs,
                             out_path=str(Path(self.tmp) / "phase.json"),
                             case="C")
        names = [p["name"] for p in agg["phases"]]
        self.assertEqual(names, [n for n, _ in phases_template])
        # Max-duration check on P2P3_make_topo.
        p3 = next(p for p in agg["phases"] if p["name"] == "P2P3_make_topo")
        self.assertEqual(p3["duration_sec"], 220.0)
        # Binary check: pre_proc summed.
        self.assertEqual(agg["binaries"][0]["name"], "pre_proc")
        self.assertEqual(agg["binaries"][0]["calls"], 3)
        self.assertEqual(agg["binaries"][0]["total_sec"], 50 + 51 + 52)


if __name__ == "__main__":
    unittest.main()
