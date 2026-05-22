#!/usr/bin/env python3
"""test_stage_cache — unit tests for tests/stage_cache.py (Mira #52).

Covers the invariants we need stage_cache to enforce:

  * Default OFF — `is_enabled()` False without `GMTSAR_STAGE_CACHE=1`.
  * Hit/miss semantics — key match → hit, key change → miss.
  * Cascade — parent_key change propagates to child stage key.
  * Crash-safety — exception inside `cached_stage` block → no sentinel.
  * Corrupt sentinel — treated as miss, never raised.
  * Atomic write — sentinel either fully written or absent.
  * Invalidate — removes the right files, returns count.

Run with:
    python3 -m pytest tests/test_stage_cache.py -v
"""
from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import sys
_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE))

import stage_cache as sc  # noqa: E402


class TestIsEnabled(unittest.TestCase):
    def test_default_off(self):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("GMTSAR_STAGE_CACHE", None)
            self.assertFalse(sc.is_enabled())

    def test_explicit_one_enables(self):
        with patch.dict(os.environ, {"GMTSAR_STAGE_CACHE": "1"}):
            self.assertTrue(sc.is_enabled())

    def test_truthy_variants_do_not_enable(self):
        # Defensive: only literal "1" enables.
        for v in ("0", "yes", "true", "on", ""):
            with patch.dict(os.environ, {"GMTSAR_STAGE_CACHE": v}):
                self.assertFalse(
                    sc.is_enabled(),
                    msg=f"value {v!r} should NOT enable the cache")


class TestComputeCacheKey(unittest.TestCase):
    def setUp(self):
        self.td = tempfile.mkdtemp()
        self.f1 = Path(self.td) / "in1.dat"
        self.f1.write_bytes(b"hello")
        self.f2 = Path(self.td) / "in2.dat"
        self.f2.write_bytes(b"world")

    def tearDown(self):
        import shutil
        shutil.rmtree(self.td, ignore_errors=True)

    def test_key_is_deterministic(self):
        k1 = sc.compute_cache_key("P2P1", [self.f1], [self.f2], {"x": 1})
        k2 = sc.compute_cache_key("P2P1", [self.f1], [self.f2], {"x": 1})
        self.assertEqual(k1, k2)
        # And it's 64 hex chars.
        self.assertEqual(len(k1), 64)
        int(k1, 16)  # not raising = valid hex

    def test_key_changes_with_stage_name(self):
        k1 = sc.compute_cache_key("P2P1", [self.f1])
        k2 = sc.compute_cache_key("P2P2", [self.f1])
        self.assertNotEqual(k1, k2)

    def test_key_changes_with_input_size(self):
        k1 = sc.compute_cache_key("P2P1", [self.f1])
        self.f1.write_bytes(b"hello bigger")
        k2 = sc.compute_cache_key("P2P1", [self.f1])
        self.assertNotEqual(k1, k2)

    def test_key_changes_with_config_value(self):
        k1 = sc.compute_cache_key("P2P1", [self.f1], (), {"x": 1})
        k2 = sc.compute_cache_key("P2P1", [self.f1], (), {"x": 2})
        self.assertNotEqual(k1, k2)

    def test_key_invariant_to_input_order(self):
        k1 = sc.compute_cache_key("P2P1", [self.f1, self.f2])
        k2 = sc.compute_cache_key("P2P1", [self.f2, self.f1])
        self.assertEqual(k1, k2,
                         "key must be input-order invariant (we sort)")

    def test_missing_file_keeps_key_deterministic(self):
        ghost = Path(self.td) / "absent.dat"
        k1 = sc.compute_cache_key("P2P1", [ghost])
        k2 = sc.compute_cache_key("P2P1", [ghost])
        self.assertEqual(k1, k2,
                         "missing files must produce deterministic keys, "
                         "not raise")

    def test_parent_key_cascades(self):
        k_no_parent = sc.compute_cache_key("P2P2", [self.f1])
        k_with_parent = sc.compute_cache_key(
            "P2P2", [self.f1], parent_key="a" * 64)
        self.assertNotEqual(k_no_parent, k_with_parent,
                            "parent_key must alter the child key")
        # And changing parent_key changes the child key again.
        k2 = sc.compute_cache_key(
            "P2P2", [self.f1], parent_key="b" * 64)
        self.assertNotEqual(k_with_parent, k2)


class TestIsCachedMarkCached(unittest.TestCase):
    def setUp(self):
        self.td = tempfile.mkdtemp()
        self._env = patch.dict(os.environ, {"GMTSAR_STAGE_CACHE": "1"})
        self._env.start()

    def tearDown(self):
        self._env.stop()
        import shutil
        shutil.rmtree(self.td, ignore_errors=True)

    def test_miss_when_disabled(self):
        with patch.dict(os.environ, {"GMTSAR_STAGE_CACHE": "0"}):
            sc.mark_cached(self.td, "P2P1", "deadbeef")
            self.assertFalse(sc.is_cached(self.td, "P2P1", "deadbeef"),
                             "disabled cache must always miss")

    def test_hit_on_exact_match(self):
        sc.mark_cached(self.td, "P2P1", "abc123")
        self.assertTrue(sc.is_cached(self.td, "P2P1", "abc123"))

    def test_miss_on_key_change(self):
        sc.mark_cached(self.td, "P2P1", "abc123")
        self.assertFalse(sc.is_cached(self.td, "P2P1", "different"))

    def test_miss_when_sentinel_missing(self):
        self.assertFalse(sc.is_cached(self.td, "P2P9999", "abc"))

    def test_miss_on_corrupt_sentinel(self):
        # Corrupt: no key= line.
        Path(self.td, ".stage_done_P2P1").write_text(
            "# garbage\nstage=P2P1\n", encoding="utf-8")
        self.assertFalse(sc.is_cached(self.td, "P2P1", "abc"))

    def test_miss_on_empty_sentinel(self):
        Path(self.td, ".stage_done_P2P1").write_text("", encoding="utf-8")
        self.assertFalse(sc.is_cached(self.td, "P2P1", "abc"))

    def test_atomic_write_no_partial(self):
        sc.mark_cached(self.td, "P2P1", "x" * 64)
        # No temp files left over.
        leftovers = list(Path(self.td).glob(".stage_done_tmp*"))
        self.assertEqual(leftovers, [],
                         "atomic write must not leave temp files behind")
        leftovers2 = [p for p in Path(self.td).iterdir()
                      if p.name.startswith(".stage_done_")
                      and p.name != ".stage_done_P2P1"]
        self.assertEqual(leftovers2, [])


class TestInvalidate(unittest.TestCase):
    def setUp(self):
        self.td = tempfile.mkdtemp()
        self._env = patch.dict(os.environ, {"GMTSAR_STAGE_CACHE": "1"})
        self._env.start()
        for i in range(1, 4):
            sc.mark_cached(self.td, f"P2P{i}", f"key{i}")

    def tearDown(self):
        self._env.stop()
        import shutil
        shutil.rmtree(self.td, ignore_errors=True)

    def test_invalidate_one(self):
        n = sc.invalidate(self.td, "P2P2")
        self.assertEqual(n, 1)
        self.assertTrue(Path(self.td, ".stage_done_P2P1").is_file())
        self.assertFalse(Path(self.td, ".stage_done_P2P2").is_file())
        self.assertTrue(Path(self.td, ".stage_done_P2P3").is_file())

    def test_invalidate_all(self):
        n = sc.invalidate(self.td)
        self.assertEqual(n, 3)
        self.assertEqual(
            list(Path(self.td).glob(".stage_done_*")), [])

    def test_invalidate_missing_returns_zero(self):
        self.assertEqual(sc.invalidate(self.td, "P2P_NEVER"), 0)


class TestCachedStageContext(unittest.TestCase):
    def setUp(self):
        self.td = tempfile.mkdtemp()
        self._env = patch.dict(os.environ, {"GMTSAR_STAGE_CACHE": "1"})
        self._env.start()
        self.f = Path(self.td) / "in.dat"
        self.f.write_bytes(b"input")

    def tearDown(self):
        self._env.stop()
        import shutil
        shutil.rmtree(self.td, ignore_errors=True)

    def test_first_run_is_miss_then_hit(self):
        with sc.cached_stage(self.td, "P2P1",
                             input_paths=[self.f]) as cs:
            self.assertFalse(cs.hit)
        # Second invocation should hit (same inputs).
        with sc.cached_stage(self.td, "P2P1",
                             input_paths=[self.f]) as cs:
            self.assertTrue(cs.hit)

    def test_input_change_invalidates(self):
        with sc.cached_stage(self.td, "P2P1",
                             input_paths=[self.f]) as cs:
            self.assertFalse(cs.hit)
        # Mutate input.
        self.f.write_bytes(b"different input")
        with sc.cached_stage(self.td, "P2P1",
                             input_paths=[self.f]) as cs:
            self.assertFalse(cs.hit, "input change must invalidate cache")

    def test_exception_in_block_skips_sentinel_write(self):
        with self.assertRaises(RuntimeError):
            with sc.cached_stage(self.td, "P2P1",
                                 input_paths=[self.f]) as cs:
                self.assertFalse(cs.hit)
                raise RuntimeError("simulate stage crash")
        # No sentinel should be written.
        self.assertFalse(
            Path(self.td, ".stage_done_P2P1").is_file(),
            "exception must NOT mark stage as cached")

    def test_disabled_cache_does_not_leak_sentinel(self):
        """Regression for the 2026-05-22 bug: a run with cache disabled
        must NOT write a sentinel, because a later cache-enabled run would
        then treat that disabled run's outputs as validated and skip the
        stage. This is the silent-wrong-result trap the briefing warned of.
        """
        with patch.dict(os.environ, {"GMTSAR_STAGE_CACHE": "0"}):
            with sc.cached_stage(self.td, "P2P1",
                                 input_paths=[self.f]) as cs:
                self.assertFalse(cs.hit)
        # No sentinel should exist after a disabled-cache run.
        self.assertFalse(
            Path(self.td, ".stage_done_P2P1").is_file(),
            "disabled cache must NOT write sentinels")

    def test_cascade_invalidates_downstream(self):
        # First run: P2P1 + P2P2 both miss, both write sentinels.
        with sc.cached_stage(self.td, "P2P1",
                             input_paths=[self.f]) as cs1:
            self.assertFalse(cs1.hit)
        with sc.cached_stage(self.td, "P2P2",
                             input_paths=[self.f],
                             parent_key=cs1.parent_key) as cs2:
            self.assertFalse(cs2.hit)
        # Second run with same inputs: both hit.
        with sc.cached_stage(self.td, "P2P1",
                             input_paths=[self.f]) as cs1b:
            self.assertTrue(cs1b.hit)
        with sc.cached_stage(self.td, "P2P2",
                             input_paths=[self.f],
                             parent_key=cs1b.parent_key) as cs2b:
            self.assertTrue(cs2b.hit)
        # Mutate P2P1 input → P2P1 miss → its parent_key changes → P2P2 miss.
        self.f.write_bytes(b"changed")
        with sc.cached_stage(self.td, "P2P1",
                             input_paths=[self.f]) as cs1c:
            self.assertFalse(cs1c.hit)
        with sc.cached_stage(self.td, "P2P2",
                             input_paths=[self.f],
                             parent_key=cs1c.parent_key) as cs2c:
            self.assertFalse(cs2c.hit,
                             "downstream stage MUST miss after upstream "
                             "input changes (cascade invalidation)")


if __name__ == "__main__":
    unittest.main(verbosity=2)
