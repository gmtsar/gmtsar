"""snaphu_solver_cy.py — Cython-extension wrapper for the snaphu TreeSolve kernel.

Mirrors the interface of network_flow_optimize_numba() in snaphu_solver_numba.py
but calls _snaphu_solver_kernel.tree_solve_kernel_cy() instead of the @njit kernel.

Import chain:
    network_flow_optimize_cy (this file)
      → tree_solve_kernel_cy (_snaphu_solver_kernel.pyx, compiled .so)
      → Python-level outer loop (SetupIncrFlowCosts, SelectSources, etc.)

Fallback:
    If the extension is not built, imports fail loudly — this file does NOT
    fall back to the numba solver.  The caller (snaphu_py.py or the user)
    decides which solver to use.

Parity spec: same as snaphu_solver_numba.py — float32-exact vs C binary
             on 30x30, 64x64, 256x256 ALOS_haiti real patches.
"""
from __future__ import annotations

import math
import numpy as np

# Hard import — no fallback.  If the extension isn't built, fail loudly.
try:
    from _snaphu_solver_kernel import (
        tree_solve_kernel_cy,
        setup_incr_flow_costs_cy,
    )
    _CY_OK = True
except ImportError as _e:
    _CY_OK = False
    _CY_IMPORT_ERROR = _e

# Re-use the SoA setup helpers from the numba module (Python-level, no numba needed).
from snaphu_solver_numba import (
    _build_node_arrays,
    _select_sources_py,
    _evaluate_total_cost_smooth_np,
    _max_nonmask_flow,
    VERYFAR, MASKED_VAL, LARGESHORT,
)

# ---------------------------------------------------------------------------
# C-exact constants (verbatim)
# ---------------------------------------------------------------------------
VERYFAR_P     = int(VERYFAR)
MASKED_P      = int(MASKED_VAL)
LARGESHORT_I  = int(LARGESHORT)


def network_flow_optimize_cy(phase: np.ndarray,
                              costs: np.ndarray,
                              flows: np.ndarray,
                              params,
                              mag: np.ndarray = None) -> np.ndarray:
    """Cython-kernel drop-in for network_flow_optimize_numba().

    Parameters
    ----------
    phase : (nrow, ncol) float32 — used only for sizing
    costs : structured arc cost array (smoothcostT or costT dtype)
    flows : (2*nrow-1, ncol) int16 — modified in-place
    params : SnaphuParams
    mag   : (nrow, ncol) float32 — None → all-ones
    """
    if not _CY_OK:
        raise ImportError(
            "_snaphu_solver_kernel extension not built. "
            f"Original error: {_CY_IMPORT_ERROR}. "
            "Run: python3 build_snaphu_kernel.py build_ext --inplace"
        )

    nrow, ncol = phase.shape
    ni = nrow - 1
    nc = ncol - 1

    if mag is None:
        mag = np.ones((nrow, ncol), dtype=np.float32)
    if not np.any(mag > 0):
        return flows

    # ---- InitNetwork corner arcs (snaphu_solver.c:2568-2576) ----
    flows[0, 0]          = np.int16(int(flows[0, 0]) + int(flows[nrow - 1, 0]))
    flows[nrow - 1, 0]   = np.int16(0)
    flows[0, ncol - 1]   = np.int16(int(flows[0, ncol - 1]) - int(flows[nrow - 1, ncol - 2]))
    flows[nrow - 1, ncol - 2] = np.int16(0)
    flows[nrow - 2, 0]   = np.int16(int(flows[nrow - 2, 0]) - int(flows[2 * nrow - 2, 0]))
    flows[2 * nrow - 2, 0] = np.int16(0)
    flows[nrow - 2, ncol - 1] = np.int16(
        int(flows[nrow - 2, ncol - 1]) + int(flows[2 * nrow - 2, ncol - 2]))
    flows[2 * nrow - 2, ncol - 2] = np.int16(0)

    # ngroundarcs
    if ncol > 2:
        ngroundarcs = 2 * (nrow + ncol - 2) - 4
    else:
        ngroundarcs = 2 * (nrow + ncol - 2) - 2

    # Bucket extents (verbatim from snaphu_solver.c:2610-2618)
    NEGBF = 1.0; POSBF = 1.0
    bkt_minind = -int(round((params.maxcost + 1) * (nrow + ncol) * NEGBF))
    bkt_maxind =  int(round((params.maxcost + 1) * (nrow + ncol) * POSBF))
    bkt_size   = bkt_maxind - bkt_minind + 1

    # ---- Build SoA node arrays ----
    nds, ground_id = _build_node_arrays(ni, nc, mag)
    nnodes = ni * nc + 1

    # ---- Flat arc arrays ----
    narc_total = (2 * nrow - 1) * ncol
    incr_pos = np.zeros(narc_total, dtype=np.int16)
    incr_neg = np.zeros(narc_total, dtype=np.int16)

    # Unpack cost arrays
    costmode_int = int(params.costmode)
    costs_off = costs['offset'].ravel().astype(np.int16)
    costs_sig = costs['sigsq'].ravel().astype(np.int16)
    narc_costs = len(costs_off)
    if costmode_int == 2:   # DEFO
        costs_dzm = costs['dzmax'].ravel().astype(np.int16)
        costs_lay = costs['laycost'].ravel().astype(np.int16)
    else:
        costs_dzm = np.zeros(narc_costs, dtype=np.int16)
        costs_lay = np.zeros(narc_costs, dtype=np.int16)

    # Pad cost arrays if needed
    if narc_costs < narc_total:
        pad = narc_total - narc_costs
        costs_off = np.concatenate([costs_off, np.zeros(pad, np.int16)])
        costs_sig = np.concatenate([costs_sig, np.zeros(pad, np.int16)])
        costs_dzm = np.concatenate([costs_dzm, np.zeros(pad, np.int16)])
        costs_lay = np.concatenate([costs_lay, np.zeros(pad, np.int16)])

    # apex array and iscandidate
    apex_arr    = np.full(narc_total, -2, dtype=np.int32)
    iscandidate = np.zeros(narc_total, dtype=np.int8)

    # Candidate arrays (pre-allocated at narc_total)
    cand_cap = narc_total
    def _alloc_cand():
        return (np.zeros(cand_cap, np.int32),   # from
                np.zeros(cand_cap, np.int32),   # to
                np.zeros(cand_cap, np.int64),   # violation
                np.zeros(cand_cap, np.int32),   # arcrow
                np.zeros(cand_cap, np.int32),   # arccol
                np.zeros(cand_cap, np.int8))    # arcdir
    cf_A, ct_A, cv_A, car_A, cac_A, cad_A = _alloc_cand()
    cf_B, ct_B, cv_B, car_B, cac_B, cad_B = _alloc_cand()

    # Bucket heads
    bkt_head = np.full(bkt_size, -1, dtype=np.int32)

    nshortcycle = int(params.nshortcycle)

    # ---- Check mostflow ----
    mostflow = _max_nonmask_flow(flows, mag, nrow, ncol)
    if mostflow * nshortcycle > LARGESHORT_I:
        raise ValueError(
            f"mostflow={mostflow} * nshortcycle={nshortcycle} "
            f"= {mostflow * nshortcycle} > LARGESHORT={LARGESHORT_I}. "
            "Reduce maxflow or nshortcycle.")

    # ---- Initial totalcost ----
    if costmode_int == 3:   # SMOOTH
        totalcost = _evaluate_total_cost_smooth_np(
            costs_off, costs_sig, flows, nrow, ncol, nshortcycle)
    else:
        totalcost = 0
    mintotalcost = totalcost
    oldtotalcost = totalcost

    nflow = 1
    ncycle = 0
    nflowdone = 0
    notfirstloop = False
    nnondecreasedcostiter = 0
    use_maxcyclefraction = (params.maxnflowcycles == -123)

    # Ensure flows array is C-contiguous int16 (Cython memoryview requires it)
    if not flows.flags['C_CONTIGUOUS']:
        flows = np.ascontiguousarray(flows, dtype=np.int16)

    # ---- Main optimization loop ----
    while True:
        # SetupIncrFlowCosts (via Cython)
        setup_incr_flow_costs_cy(
            costmode_int, costs_off, costs_sig, costs_dzm, costs_lay,
            incr_pos, incr_neg, flows,
            nflow, nrow, ncol, nshortcycle)

        # SelectSources (Python-side, same as numba version)
        sourcelist = _select_sources_py(
            nds['row'], nds['col'], nds['group'], nds['next'],
            ground_id, ni, nc, ngroundarcs, params.nconnnodemin, mag)

        # SetupTreeSolveNetwork: reset node state
        _masked_nodes = (nds['group'] == MASKED_P)
        nds['group'][:] = 0
        nds['group'][_masked_nodes] = MASKED_P
        nds['incost'][:] = VERYFAR_P
        nds['outcost'][:] = VERYFAR_P
        nds['pred'][:] = -1
        nds['next'][:] = -1
        nds['prev'][:] = -1
        nds['level'][:] = 0

        # Reset apex / iscandidate
        apex_arr[:] = -2   # NONTREEARC
        iscandidate[:] = 0
        # Corner arcs: always iscandidate=True
        iscandidate[(nrow - 1) * ncol + 0]           = 1
        iscandidate[(2 * nrow - 2) * ncol + 0]       = 1
        iscandidate[(nrow - 1) * ncol + (ncol - 2)]  = 1
        iscandidate[(2 * nrow - 2) * ncol + (ncol - 2)] = 1

        # Reset bucket
        bkt_head[:] = -1

        n = 0
        last_nconn = 1

        for source_id_py, nconnected in sourcelist:
            last_nconn = nconnected

            _ret = int(tree_solve_kernel_cy(
                nds['row'], nds['col'],
                nds['next'], nds['prev'],
                nds['pred'], nds['level'],
                nds['group'], nds['incost'], nds['outcost'],
                int(ground_id),
                incr_pos, incr_neg, flows,
                costmode_int,
                costs_off, costs_sig, costs_dzm, costs_lay,
                apex_arr, iscandidate,
                cf_A, ct_A, cv_A, car_A, cac_A, cad_A,
                cf_B, ct_B, cv_B, car_B, cac_B, cad_B,
                bkt_head,
                int(bkt_minind), int(bkt_maxind),
                int(nflow), int(nshortcycle),
                int(nconnected),
                int(ni), int(nc),
                int(ngroundarcs),
                int(source_id_py),
                float(params.maxnewnodeconst),
                int(params.nmajorprune),
                int(params.prunecostthresh),
            ))
            if _ret < 0:
                raise RuntimeError(
                    f"tree_solve_kernel_cy returned cycling sentinel {_ret} "
                    f"(nflow={nflow}, nconnected={nconnected}, region={source_id_py})"
                )
            n += _ret

        ncycle += n

        # EvaluateTotalCost + anti-cycling check
        if notfirstloop:
            oldtotalcost = totalcost
            if costmode_int == 3:   # SMOOTH
                totalcost = _evaluate_total_cost_smooth_np(
                    costs_off, costs_sig, flows, nrow, ncol, nshortcycle)
            if costmode_int == 3:
                if totalcost < mintotalcost:
                    mintotalcost = totalcost
                if totalcost > mintotalcost:
                    nnondecreasedcostiter += 1
                else:
                    nnondecreasedcostiter = 0

        if use_maxcyclefraction:
            maxnflowcycles_val = int(params.maxcyclefraction * last_nconn)
        else:
            maxnflowcycles_val = params.maxnflowcycles

        if n <= maxnflowcycles_val:
            nflowdone += 1
        else:
            nflowdone = 1

        mostflow = _max_nonmask_flow(flows, mag, nrow, ncol)

        if nnondecreasedcostiter >= 2 * mostflow:
            break

        if (nflowdone >= params.maxflow or nflowdone >= mostflow
                or params.p >= 1.0):
            break

        nflow += 1
        if nflow > params.maxflow or nflow > mostflow:
            nflow = 1
            notfirstloop = True

    return flows
