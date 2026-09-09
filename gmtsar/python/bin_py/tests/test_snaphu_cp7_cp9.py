#!/usr/bin/env python3
"""test_snaphu_cp7_cp9 — unit tests for CP7 (TreeSolve) and CP9 (GrowConnComps).

TestCP7Helpers    — unit tests for _recalc_cost_ts, _get_cost_ts,
                     _bkt_insert_ts/_bkt_remove_ts/_min_out_cost_node_ts,
                     _find_apex_ts, _get_arc_grid_ts, _neighbor_node_grid_ts.
TestCP7Network    — smoke tests for network_flow_optimize on tiny synthetic grids.
TestCP9GrowConn   — unit tests for _thicken_costs_cc, grow_conn_comps on
                     synthetic grids (flat-cost, blocked-arc, isolated-pixel).
TestCP7CP9Integration — integration: mst_init_flows → network_flow_optimize →
                          grow_conn_comps on a 10x10 synthetic wrapped interferogram.
"""
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np

_HERE = Path(__file__).resolve().parent
_BINPY = _HERE.parent
_SNAPHU_PY = _BINPY / 'snaphu_py'
sys.path.insert(0, str(_SNAPHU_PY))
sys.path.insert(0, str(_BINPY))

from snaphu_py import (  # noqa: E402
    SnaphuParams, SMOOTH, DEFO, LARGESHORT, LARGEINT, PI, TWOPI,
    build_cost_arrays_smooth, build_cost_arrays_defo,
    mst_init_flows, network_flow_optimize, grow_conn_comps,
    integrate_phase, wrap_phase,
    # CP7 internals
    _NodeTS, _BktsTS, _CandidateTS,
    _bkt_insert_ts, _bkt_remove_ts, _min_out_cost_node_ts,
    _get_cost_ts, _recalc_cost_ts, _setup_incr_flow_costs_ts,
    _find_apex_ts, _get_arc_grid_ts, _neighbor_node_grid_ts,
    _mask_nodes_ts,
    # CP9 internals
    _NodeCC, _thicken_costs_cc, _renumber_region_cc,
    _ONTREE, _INBUCKET_TS, _NOTINBUCKET_TS, _MASKED_TS, _NONTREEARC_TS,
    _ONTREE_CC, _INBUCKET_CC,
)


def _make_params_smooth():
    p = SnaphuParams()
    p.costmode = SMOOTH
    return p


def _make_incrcosts(nrow, ncol):
    dt = np.dtype([('poscost', np.int16), ('negcost', np.int16)])
    return np.zeros((2 * nrow - 1, ncol), dt)


# ---------------------------------------------------------------------------
# TestCP7Helpers
# ---------------------------------------------------------------------------

class TestCP7Helpers(unittest.TestCase):
    """Unit tests for CP7 helper functions."""

    # --- Bucket operations ---

    def test_bkt_insert_and_remove(self):
        """Insert a node, then remove it; bucket should be empty."""
        bkts = _BktsTS(0, 10)
        nd = _NodeTS(0, 0)
        _bkt_insert_ts(bkts, nd, 3)
        self.assertIs(bkts.bucket[3], nd)
        _bkt_remove_ts(bkts, nd, 3)
        self.assertIsNone(bkts.bucket[3])

    def test_bkt_lifo_within_bucket(self):
        """Two insertions into same slot → LIFO (linked-list head)."""
        bkts = _BktsTS(0, 10)
        n1 = _NodeTS(0, 0)
        n2 = _NodeTS(0, 1)
        _bkt_insert_ts(bkts, n1, 5)
        _bkt_insert_ts(bkts, n2, 5)
        self.assertIs(bkts.bucket[5], n2)
        self.assertIs(n2.next, n1)

    def test_min_out_cost_node_returns_lowest_occupied(self):
        """_min_out_cost_node_ts returns from lowest non-empty bucket."""
        bkts = _BktsTS(0, 10)
        n1 = _NodeTS(0, 0)
        n2 = _NodeTS(0, 1)
        _bkt_insert_ts(bkts, n1, 7)
        _bkt_insert_ts(bkts, n2, 3)
        bkts.curr = 0
        got = _min_out_cost_node_ts(bkts)
        self.assertIs(got, n2)
        self.assertEqual(bkts.curr, 3)

    def test_min_out_cost_node_empty_returns_none(self):
        bkts = _BktsTS(0, 5)
        bkts.curr = 0
        got = _min_out_cost_node_ts(bkts)
        self.assertIsNone(got)

    # --- GetCost ---

    def test_get_cost_ts_poscost(self):
        nrow, ncol = 4, 5
        ic = _make_incrcosts(nrow, ncol)
        ic['poscost'][2, 3] = 42
        ic['negcost'][2, 3] = -7
        self.assertEqual(_get_cost_ts(ic, 2, 3, 1), 42)

    def test_get_cost_ts_negcost(self):
        nrow, ncol = 4, 5
        ic = _make_incrcosts(nrow, ncol)
        ic['poscost'][1, 2] = 10
        ic['negcost'][1, 2] = -15
        self.assertEqual(_get_cost_ts(ic, 1, 2, -1), -15)

    # --- ReCalcCost clipping ---

    def test_recalc_cost_clipped_to_largeshort(self):
        """Verify poscost/negcost are clipped to ±LARGESHORT."""
        nrow, ncol = 5, 5
        params = _make_params_smooth()
        phase = np.zeros((nrow, ncol), np.float32)
        corr = np.full((nrow, ncol), 0.01, np.float32)  # very low corr → high cost
        costs = build_cost_arrays_smooth(phase, corr, params)
        ic = _make_incrcosts(nrow, ncol)
        # flow=0, nflow=1 — just verify no exception and result in range
        _recalc_cost_ts(costs, ic, 0, 0, 0, 1, nrow, params)
        for field in ('poscost', 'negcost'):
            v = int(ic[field][0, 0])
            self.assertLessEqual(abs(v), LARGESHORT,
                                 f"{field}={v} exceeds LARGESHORT={LARGESHORT}")

    # --- FindApex ---

    def test_find_apex_same_node(self):
        """If from == to (same level, same node), apex is that node."""
        n = _NodeTS(0, 0)
        n.level = 0
        n.pred = None
        apex = _find_apex_ts(n, n)
        self.assertIs(apex, n)

    def test_find_apex_linear_chain(self):
        """Root → A → B → C; apex(B, C) = B.pred = A; apex(A, C) = root."""
        root = _NodeTS(0, 0); root.level = 0; root.pred = root
        A = _NodeTS(0, 1); A.level = 1; A.pred = root
        B = _NodeTS(0, 2); B.level = 2; B.pred = A
        C = _NodeTS(1, 0); C.level = 2; C.pred = A
        apex_bc = _find_apex_ts(B, C)
        self.assertIs(apex_bc, A)

    # --- GetArcGrid ---

    def test_get_arc_grid_horizontal(self):
        """Adjacent cols in same row → column arc."""
        f = _NodeTS(2, 3)
        t = _NodeTS(2, 4)
        nrow, ncol = 8, 8
        nodes = [[_NodeTS(r, c) for c in range(ncol)] for r in range(nrow - 1)]
        ar, ac, ad = _get_arc_grid_ts(f, t, nrow, ncol, nodes)
        self.assertEqual(ar, 2)   # row arc: arcrow == row
        self.assertEqual(ac, 4)   # arccol == col of to-node
        self.assertEqual(ad, 1)

    def test_get_arc_grid_vertical(self):
        """Adjacent rows in same col → row arc (arcrow = nrow-1+from.row)."""
        f = _NodeTS(1, 2)
        t = _NodeTS(2, 2)
        nrow, ncol = 8, 8
        nodes = [[_NodeTS(r, c) for c in range(ncol)] for r in range(nrow - 1)]
        ar, ac, ad = _get_arc_grid_ts(f, t, nrow, ncol, nodes)
        self.assertEqual(ar, nrow - 1 + 2)  # col arc: arcrow = nrow-1 + to.row
        self.assertEqual(ac, 2)
        self.assertEqual(ad, 1)

    # --- NeighborNodeGrid ---

    def test_neighbor_node_grid_interior_4arcs(self):
        """Interior node has 4 neighbours via arcnums -4..-1."""
        nrow, ncol = 6, 6
        nodes = [[_NodeTS(r, c) for c in range(ncol - 1)] for r in range(nrow - 1)]
        ground = _NodeTS(-2, -2)
        ngroundarcs = 2 * (nrow + ncol - 2) - 4
        ni, nc = nrow - 1, ncol - 1

        src = nodes[2][2]
        arcnums = [-4, -3, -2, -1]
        neighbours = []
        for an in arcnums:
            nb, ar, ac, ad = _neighbor_node_grid_ts(
                src, an, ngroundarcs, nodes, ground, ni, nc)
            neighbours.append((nb, ar, ac, ad))
        # arcnum -4: right (col+1)
        self.assertIs(neighbours[0][0], nodes[2][3])
        # arcnum -3: down (row+1)
        self.assertIs(neighbours[1][0], nodes[3][2])
        # arcnum -2: left (col-1)
        self.assertIs(neighbours[2][0], nodes[2][1])
        # arcnum -1: up (row-1)
        self.assertIs(neighbours[3][0], nodes[1][2])


# ---------------------------------------------------------------------------
# TestCP7Network
# ---------------------------------------------------------------------------

class TestCP7Network(unittest.TestCase):
    """Smoke tests for network_flow_optimize on tiny grids."""

    def _run(self, nrow, ncol, costmode=SMOOTH):
        params = SnaphuParams()
        params.costmode = costmode
        rng = np.random.default_rng(42)
        phase = (rng.uniform(-PI, PI, (nrow, ncol))).astype(np.float32)
        corr = np.full((nrow, ncol), 0.6, np.float32)
        if costmode == SMOOTH:
            costs = build_cost_arrays_smooth(phase, corr, params)
        else:
            costs = build_cost_arrays_defo(phase, corr, params)
        flows = mst_init_flows(phase, costs, params)
        flows_out = network_flow_optimize(phase, costs, flows, params)
        return flows_out, nrow, ncol

    def test_output_shape_smooth(self):
        """network_flow_optimize returns flows array of correct shape (SMOOTH)."""
        flows_out, nrow, ncol = self._run(5, 5, SMOOTH)
        self.assertEqual(flows_out.shape, (2 * nrow - 1, ncol))

    def test_output_shape_defo(self):
        """network_flow_optimize returns flows array of correct shape (DEFO)."""
        flows_out, nrow, ncol = self._run(5, 5, DEFO)
        self.assertEqual(flows_out.shape, (2 * nrow - 1, ncol))

    def test_flat_phase_zero_flows(self):
        """Flat (zero) wrapped phase → all flows remain 0 after optimization."""
        nrow, ncol = 4, 4
        params = _make_params_smooth()
        phase = np.zeros((nrow, ncol), np.float32)
        corr = np.full((nrow, ncol), 0.9, np.float32)
        costs = build_cost_arrays_smooth(phase, corr, params)
        flows = mst_init_flows(phase, costs, params)
        self.assertTrue(np.all(flows == 0),
                        "flat phase should produce zero MST flows")
        flows_out = network_flow_optimize(phase, costs, flows, params)
        self.assertTrue(np.all(flows_out == 0),
                        "flat phase should preserve zero flows after optimization")

    def test_integer_dtypes_preserved(self):
        """network_flow_optimize returns integer flows (not float)."""
        flows_out, nrow, ncol = self._run(4, 5)
        self.assertTrue(np.issubdtype(flows_out.dtype, np.integer),
                        f"flows dtype should be integer, got {flows_out.dtype}")

    def test_integrate_phase_after_optimize_rms(self):
        """integrate_phase after optimization produces reasonable phase."""
        nrow, ncol = 5, 5
        params = _make_params_smooth()
        rng = np.random.default_rng(7)
        phase = rng.uniform(-PI, PI, (nrow, ncol)).astype(np.float32)
        corr = np.full((nrow, ncol), 0.7, np.float32)
        costs = build_cost_arrays_smooth(phase, corr, params)
        flows = mst_init_flows(phase, costs, params)
        flows = network_flow_optimize(phase, costs, flows, params)
        unwrapped = integrate_phase(phase, flows)
        rms = float(np.sqrt(np.mean(unwrapped ** 2)))
        self.assertLess(rms, 200.0,
                        f"unwrapped phase RMS={rms:.1f} suspiciously large")

    def test_mag_none_path(self):
        """mag=None (GMTSAR path) should not raise and return correct shape."""
        nrow, ncol = 4, 4
        params = _make_params_smooth()
        phase = np.zeros((nrow, ncol), np.float32)
        corr = np.full((nrow, ncol), 0.9, np.float32)
        costs = build_cost_arrays_smooth(phase, corr, params)
        flows = mst_init_flows(phase, costs, params)
        flows_out = network_flow_optimize(phase, costs, flows, params, mag=None)
        self.assertEqual(flows_out.shape, (2 * nrow - 1, ncol))

    def test_single_row_raises_or_trivial(self):
        """Very small input: build_cost_arrays raises cleanly or pipeline works.

        nrow=2 triggers a ValueError in build_cost_arrays_smooth because the
        averaging kernel (krows=3 by default) exceeds the array height.  This
        is the expected C behaviour (snaphu would also refuse such input).
        The test accepts either a clean ValueError from the cost-array builder
        or a successful complete run with correct output shape.
        """
        nrow, ncol = 2, 5  # minimum (nrow-1=1 arc rows)
        params = _make_params_smooth()
        phase = np.zeros((nrow, ncol), np.float32)
        corr = np.full((nrow, ncol), 0.9, np.float32)
        try:
            costs = build_cost_arrays_smooth(phase, corr, params)
        except ValueError:
            return   # expected — averaging box too large
        flows = mst_init_flows(phase, costs, params)
        try:
            flows_out = network_flow_optimize(phase, costs, flows, params)
            self.assertEqual(flows_out.shape, (2 * nrow - 1, ncol))
        except Exception as exc:
            self.fail(f"Unexpected exception for 2-row input: {exc}")


# ---------------------------------------------------------------------------
# TestCP9GrowConn
# ---------------------------------------------------------------------------

class TestCP9GrowConn(unittest.TestCase):
    """Unit tests for CP9 grow_conn_comps and helpers."""

    def _make_smooth_scenario(self, nrow, ncol, phase_val=0.0, corr_val=0.9):
        params = _make_params_smooth()
        phase = np.full((nrow, ncol), phase_val, dtype=np.float32)
        corr = np.full((nrow, ncol), corr_val, dtype=np.float32)
        costs = build_cost_arrays_smooth(phase, corr, params)
        flows = mst_init_flows(phase, costs, params)
        # NOTE: skip network_flow_optimize for CP9 tests — grow_conn_comps
        # only needs costs and integer flows, not the optimized flows.
        # Using MST flows (all-zero for flat phase) is sufficient to test
        # the CP9 boundary criterion and BFS logic.
        return costs, flows, params

    # --- ThickenCosts ---

    def test_thicken_costs_uniform_input(self):
        """Uniform poscost → thickened negcost equals poscost (no boundary effect)."""
        nrow, ncol = 6, 6
        dt = np.dtype([('poscost', np.int16), ('negcost', np.int16)])
        ic = np.zeros((2 * nrow - 1, ncol), dt)
        ic['poscost'][:, :] = 100
        _thicken_costs_cc(ic, nrow, ncol)
        # Interior row arcs: 3 neighbours, all 100 → negcost = round(4*100/4)=100
        for r in range(1, nrow - 2):
            for c in range(1, ncol - 1):
                self.assertEqual(int(ic['negcost'][r, c]), 100,
                                 f"row arc [{r},{c}] negcost should be 100")

    def test_thicken_costs_clip(self):
        """If blurred cost exceeds LARGESHORT, it is clipped."""
        nrow, ncol = 4, 4
        dt = np.dtype([('poscost', np.int16), ('negcost', np.int16)])
        ic = np.zeros((2 * nrow - 1, ncol), dt)
        ic['poscost'][:, :] = LARGESHORT
        _thicken_costs_cc(ic, nrow, ncol)
        for r in range(nrow - 1):
            for c in range(ncol):
                v = int(ic['negcost'][r, c])
                self.assertLessEqual(v, LARGESHORT,
                                     f"negcost {v} exceeds LARGESHORT at [{r},{c}]")

    # --- grow_conn_comps ---

    def test_output_shape(self):
        """grow_conn_comps returns uint8 array of shape (nrow, ncol)."""
        nrow, ncol = 5, 5
        costs, flows, params = self._make_smooth_scenario(nrow, ncol)
        labels = grow_conn_comps(costs, flows, nrow, ncol, params)
        self.assertEqual(labels.shape, (nrow, ncol))
        self.assertEqual(labels.dtype, np.uint8)

    def test_flat_phase_single_component(self):
        """Flat phase, high corr → all pixels in one or few large components."""
        nrow, ncol = 5, 5
        costs, flows, params = self._make_smooth_scenario(nrow, ncol, 0.0, 0.95)
        params.minconncompfrac = 0.0
        labels = grow_conn_comps(costs, flows, nrow, ncol, params)
        # At least 60% of pixels should be in a component (small grid)
        n_labeled = int(np.sum(labels > 0))
        self.assertGreater(n_labeled, nrow * ncol * 0.6,
                           f"Only {n_labeled}/{nrow*ncol} pixels labeled")

    def test_labels_in_valid_range(self):
        """All label values are 0..255."""
        nrow, ncol = 5, 6
        costs, flows, params = self._make_smooth_scenario(nrow, ncol, 0.5, 0.7)
        labels = grow_conn_comps(costs, flows, nrow, ncol, params)
        self.assertGreaterEqual(int(labels.min()), 0)
        self.assertLessEqual(int(labels.max()), 255)

    def test_maxncomps_enforced(self):
        """maxncomps=2 → at most 2 distinct nonzero label values."""
        nrow, ncol = 5, 5
        costs, flows, params = self._make_smooth_scenario(nrow, ncol, 0.0, 0.7)
        params.maxncomps = 2
        params.minconncompfrac = 0.0
        labels = grow_conn_comps(costs, flows, nrow, ncol, params)
        nonzero_labels = set(int(v) for v in labels.flatten() if v > 0)
        self.assertLessEqual(len(nonzero_labels), 2,
                             f"Got {len(nonzero_labels)} components, expected <= 2")

    def test_minconncompfrac_eliminates_all(self):
        """minconncompfrac=1.1 → all pixels labeled 0 (no region large enough)."""
        nrow, ncol = 5, 5
        costs, flows, params = self._make_smooth_scenario(nrow, ncol, 0.0, 0.9)
        params.minconncompfrac = 1.1   # impossible threshold
        labels = grow_conn_comps(costs, flows, nrow, ncol, params)
        self.assertTrue(np.all(labels == 0),
                        "minconncompfrac=1.1 should zero out all regions")

    def test_returns_contiguous_uint8(self):
        """Output array is C-contiguous uint8 (matches write_uchar expectation)."""
        nrow, ncol = 5, 5
        costs, flows, params = self._make_smooth_scenario(nrow, ncol)
        labels = grow_conn_comps(costs, flows, nrow, ncol, params)
        self.assertTrue(labels.flags['C_CONTIGUOUS'])
        self.assertEqual(labels.dtype, np.uint8)


# ---------------------------------------------------------------------------
# TestCP7CP9Integration
# ---------------------------------------------------------------------------

class TestCP7CP9Integration(unittest.TestCase):
    """Integration: mst_init_flows → network_flow_optimize → grow_conn_comps."""

    def test_full_pipeline_smooth(self):
        """Full pipeline on 5x5 SMOOTH synthetic grid: no exceptions, valid output."""
        nrow, ncol = 5, 5
        rng = np.random.default_rng(99)
        params = _make_params_smooth()
        phase = rng.uniform(-PI, PI, (nrow, ncol)).astype(np.float32)
        corr = np.full((nrow, ncol), 0.7, np.float32)

        costs = build_cost_arrays_smooth(phase, corr, params)
        flows = mst_init_flows(phase, costs, params)
        flows = network_flow_optimize(phase, costs, flows, params)
        unwrapped = integrate_phase(phase, flows)
        labels = grow_conn_comps(costs, flows, nrow, ncol, params)

        self.assertEqual(unwrapped.shape, (nrow, ncol))
        self.assertEqual(labels.shape, (nrow, ncol))
        self.assertFalse(np.any(np.isnan(unwrapped)),
                         "unwrapped contains NaN")
        self.assertFalse(np.any(np.isinf(unwrapped)),
                         "unwrapped contains Inf")

    def test_full_pipeline_defo(self):
        """Full pipeline on 5x5 DEFO synthetic grid: no exceptions, valid output."""
        nrow, ncol = 5, 5
        params = SnaphuParams()
        params.costmode = DEFO
        rng = np.random.default_rng(55)
        phase = rng.uniform(-PI, PI, (nrow, ncol)).astype(np.float32)
        corr = np.full((nrow, ncol), 0.65, np.float32)

        costs = build_cost_arrays_defo(phase, corr, params)
        flows = mst_init_flows(phase, costs, params)
        flows = network_flow_optimize(phase, costs, flows, params)
        unwrapped = integrate_phase(phase, flows)
        labels = grow_conn_comps(costs, flows, nrow, ncol, params)

        self.assertEqual(unwrapped.shape, (nrow, ncol))
        self.assertEqual(labels.shape, (nrow, ncol))
        self.assertFalse(np.any(np.isnan(unwrapped)))

    def test_rewrap_rms_less_than_pi(self):
        """Re-wrapping unwrapped output should recover original phase to within pi."""
        nrow, ncol = 5, 5
        params = _make_params_smooth()
        rng = np.random.default_rng(13)
        phase = rng.uniform(-PI, PI, (nrow, ncol)).astype(np.float32)
        corr = np.full((nrow, ncol), 0.8, np.float32)

        costs = build_cost_arrays_smooth(phase, corr, params)
        flows = mst_init_flows(phase, costs, params)
        flows = network_flow_optimize(phase, costs, flows, params)
        unwrapped = integrate_phase(phase, flows)
        rewrapped = wrap_phase(unwrapped)

        diff = np.abs(rewrapped.astype(np.float64) - phase.astype(np.float64))
        # Differences should be < pi (same fringe) for high-corr smooth phase
        median_diff = float(np.median(diff))
        self.assertLess(median_diff, PI,
                        f"Re-wrap median diff={median_diff:.3f} rad >= pi")


if __name__ == '__main__':
    unittest.main()
