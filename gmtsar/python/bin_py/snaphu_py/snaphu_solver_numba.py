"""snaphu_solver_numba.py — SoA + numba JIT rewrite of the snaphu TreeSolve
network-flow solver.

C reference: snaphu/src/snaphu_solver.c  (TreeSolve, AddNewNode,
             CheckArcReducedCost, FindApex, InitTree, PruneTree,
             MinOutCostNode/ClosestNode, NonDegenUpdateChildren,
             DischargeTree, ClipFlow, GetCost, ReCalcCost,
             NeighborNodeGrid, GetArcGrid, GetArcNumLims, InitBuckets,
             BucketInsert, BucketRemove)

Correctness spec: the scalar-object port in snaphu_py.py (_tree_solve_ts
and friends) — already bit-identical to C on 30×30 real data.

Design principles
-----------------
1. Struct-of-Arrays (SoA) mirroring nodeT:
     node_row[i], node_col[i]   : int32  — grid position
     node_next[i]               : int32  — thread next (flat index, -1=NULL)
     node_prev[i]               : int32  — thread prev (flat index, -1=NULL)
     node_pred[i]               : int32  — parent in tree (flat index, -1=NULL)
     node_level[i]              : int64
     node_group[i]              : int64
     node_incost[i]             : int64
     node_outcost[i]            : int64

   Flat index: node_id(r, c) = r*nc + c  for 0 ≤ r < ni, 0 ≤ c < nc.
   Ground node: id = ni*nc  (GROUND_ID).

2. Buckets: SoA doubly-linked list, same pointers as thread (C reuses
   node->next / node->prev for the bucket list when a node is INBUCKET).
   Bucket heads: bkt_head[b] = flat node index of first node in bucket b
   (or -1).  b is the bucket *index* = cost - bkt_minind.

3. Apexes: flat int32 array (narc,) containing flat node index of apex
   (-1 for NULL/on-tree, -2 for NONTREEARC sentinel).

4. Candidate bag: fixed-size flat arrays (structured), grown by doubling.

5. All hot-path functions decorated @njit(cache=True).  Cold setup
   (array allocation, source selection, bucket init) stays in Python.

6. calc_cost_smooth / calc_cost_defo: these must be called from within
   the @njit kernel.  We port them as @njit helper functions using the
   exact C formulas from snaphu_cost.c (no scipy).

Node-group sentinel constants (from snaphu.h — VERBATIM):
  INBUCKET  = -2
  NOTINBUCKET = -3   (unused in this port; nodes not in bucket have group ≥ 0
                       or PRUNED/MASKED)
  PRUNED    = -4
  MASKED    = -5
  GROUNDROW = -2     (row of the ground node)
  VERYFAR   = LARGEINT = 2000000000

Arc sentinel:
  NONTREEARC_ID = -2  (stored in apex array to mean "arc not yet in tree")
  NULL_ID       = -1

C GetArcNumLims / NeighborNodeGrid / GetArcGrid are inlined inside the
@njit TreeSolve kernel so numba can see the full control flow.

C ReCalcCost / GetCost / CalcCost are also inlined.

Port status: Stage (a) — SoA + numba TreeSolve, runs on 30×30 real data.
"""

from __future__ import annotations

import math
import sys
from typing import Tuple

import numpy as np

# ---------------------------------------------------------------------------
# Import numba conditionally so the module remains importable even without it.
# ---------------------------------------------------------------------------
try:
    import numba as nb
    from numba import njit, types
    _NUMBA_OK = True
except ImportError:
    _NUMBA_OK = False
    # Provide a no-op decorator so the rest of the module parses.
    def njit(*a, **kw):
        def _dec(fn):
            return fn
        return _dec

# ---------------------------------------------------------------------------
# C-exact constants (USE VERBATIM — never substitute math equivalents)
# ---------------------------------------------------------------------------
LARGESHORT    = np.int64(32000)
LARGEINT      = np.int64(2_000_000_000)
VERYFAR       = np.int64(2_000_000_000)   # = LARGEINT
PI            = 3.14159265358979323846
TWOPI         = 6.28318530717958647692
TOPO          = 1   # costmode sentinels (snaphu_py.py — VERBATIM)
DEFO          = 2
SMOOTH        = 3

# Node-group sentinels (snaphu.h — VERBATIM)
INBUCKET_VAL  = np.int64(-2)
PRUNED_VAL    = np.int64(-4)
MASKED_VAL    = np.int64(-5)
ONTREE_VAL    = np.int64(-1)   # group value for on-tree node (group set to 1+ in C)

# Apex array sentinels
NULL_ID       = np.int32(-1)    # NULL pointer
NONTREEARC_ID = np.int32(-2)    # arc not yet in tree (NONTREEARC)

# Bucket sentinel
BKT_EMPTY     = np.int32(-1)    # no node in bucket

# Misc
MAXGROUPBASE  = np.int64(2_000_000_000)   # LARGEINT

# ---------------------------------------------------------------------------
# SoA node array dtype helpers
# ---------------------------------------------------------------------------

def _make_node_arrays(nnodes: int):
    """Allocate all SoA node arrays.  Returns a dict of int32/int64 arrays.

    nnodes = ni*nc + 1  (interior nodes + ground node).
    """
    INF = int(VERYFAR)
    d = {
        'row':     np.empty(nnodes, dtype=np.int32),
        'col':     np.empty(nnodes, dtype=np.int32),
        'next':    np.full(nnodes, -1, dtype=np.int32),
        'prev':    np.full(nnodes, -1, dtype=np.int32),
        'pred':    np.full(nnodes, -1, dtype=np.int32),
        'level':   np.zeros(nnodes, dtype=np.int64),
        'group':   np.zeros(nnodes, dtype=np.int64),
        'incost':  np.full(nnodes, INF, dtype=np.int64),
        'outcost': np.full(nnodes, INF, dtype=np.int64),
    }
    return d


def _build_node_arrays(ni: int, nc: int, mag: np.ndarray) -> dict:
    """Build SoA arrays for all interior nodes + ground.

    Node layout: flat index i = r*nc + c  for (r, c) in [0,ni)×[0,nc).
    Ground: index GROUND_ID = ni*nc.
    Sets initial group (MASKED or 0) via _grid_node_mask_status logic.

    mag shape: (nrow, ncol) = (ni+1, nc+1).
    """
    nnodes = ni * nc + 1
    nds = _make_node_arrays(nnodes)
    ground_id = ni * nc

    INF = int(VERYFAR)
    nrow = ni + 1
    ncol = nc + 1

    for r in range(ni):
        for c in range(nc):
            idx = r * nc + c
            nds['row'][idx] = r
            nds['col'][idx] = c
            nds['incost'][idx] = INF
            nds['outcost'][idx] = INF
            # GridNodeMaskStatus: MASKED if all four surrounding pixels == 0
            if (mag[r, c] or mag[r, c+1] or mag[r+1, c] or mag[r+1, c+1]):
                nds['group'][idx] = 0
            else:
                nds['group'][idx] = int(MASKED_VAL)

    # Ground node
    nds['row'][ground_id] = -2   # GROUNDROW
    nds['col'][ground_id] = -2   # GROUNDCOL
    nds['incost'][ground_id] = INF
    nds['outcost'][ground_id] = INF
    # GroundMaskStatus
    ground_masked = True
    for r_g in range(nrow):
        if mag[r_g, 0] or mag[r_g, ncol-1]:
            ground_masked = False; break
    if ground_masked:
        for c_g in range(ncol):
            if mag[0, c_g] or mag[nrow-1, c_g]:
                ground_masked = False; break
    nds['group'][ground_id] = int(MASKED_VAL) if ground_masked else 0

    return nds, ground_id


# ---------------------------------------------------------------------------
# Arc index helper (flat arc index for apexes / iscandidate arrays)
# ---------------------------------------------------------------------------

def _arc_flat_shape(nrow: int, ncol: int):
    """Total arcs = (nrow-1)*ncol + nrow*(ncol-1).
    Layout: row-arcs rows 0..nrow-2 (width ncol), col-arcs rows nrow-1..2*nrow-2 (width ncol-1).
    We use the 2D (2*nrow-1, ncol) layout of the existing port for apexes
    and iscandidate, but store them as flat int32 / int8 arrays shaped (2*nrow-1, ncol).
    So flat index = arcrow * ncol + arccol.  The numba kernel accesses them this way.
    """
    return (2 * nrow - 1, ncol)


# ---------------------------------------------------------------------------
# Numba-jittable cost kernel helpers
# ---------------------------------------------------------------------------
# We port CalcCostSmooth and CalcCostDefo from snaphu_cost.c inline.
# Only the SMOOTH path (costmode=SMOOTH) is used by GMTSAR for standard
# deformation interferograms.  DEFO is included for completeness.
#
# snaphu_cost.c CalcCostSmooth (line ~310):
#   poscost = (float - flow*nshortcycle + 0.5) ^2 / sigsq  - offset^2/sigsq
#           → converted to integer via floor
# The incremental cost is the marginal cost of one more unit of flow:
#   incr_pos = CalcCost(flow) - CalcCost(flow-1) ≈ d/dflow[cost(flow)]
#   incr_neg = CalcCost(flow) - CalcCost(flow+1)
#
# We implement the exact C formulas (snaphu_cost.c:CalcCostSmooth lines 313-380,
# SetupIncrFlowCosts lines 3476-3530).

@njit(cache=True)
def _calc_cost_smooth_incr(offset_s: np.int16, sigsq_s: np.int16,
                            flow: np.int64, nflow: np.int64,
                            nshortcycle: np.int64) -> Tuple[np.int64, np.int64]:
    """Return (poscost, negcost) for SMOOTH mode.

    Mirrors CalcCost() + ReCalcCost() from snaphu_cost.c.
    offset, sigsq are int16 raw from the costs array (smoothcostT).
    poscost = cost to increase flow by nflow
    negcost = cost to decrease flow by nflow
    Uses C-exact integer arithmetic.
    """
    # Mirrors CalcCostSmooth() in snaphu_cost.c:
    # idz1    = abs(flow * nshortcycle + offset)
    # idz2pos = abs((flow + nflow) * nshortcycle + offset)
    # idz2neg = abs((flow - nflow) * nshortcycle + offset)
    # cost1   = idz1^2 // sigsq
    # poscost = idz2pos^2 // sigsq - cost1  (then divided by nflow^2, ceiling/floor)
    # negcost = idz2neg^2 // sigsq - cost1

    offset = np.int64(offset_s)
    sigsq  = np.int64(sigsq_s)
    if sigsq <= 0:
        sigsq = np.int64(1)

    # Guard: LARGESHORT sigsq means disconnected arc (cost = 0)
    if sigsq == np.int64(32000):
        return np.int64(0), np.int64(0)

    idz1    = flow * nshortcycle + offset
    if idz1 < np.int64(0): idz1 = -idz1
    idz2pos = (flow + nflow) * nshortcycle + offset
    if idz2pos < np.int64(0): idz2pos = -idz2pos
    idz2neg = (flow - nflow) * nshortcycle + offset
    if idz2neg < np.int64(0): idz2neg = -idz2neg

    cost1   = (idz1 * idz1) // sigsq
    poscost = (idz2pos * idz2pos) // sigsq - cost1
    negcost = (idz2neg * idz2neg) // sigsq - cost1

    nflowsq = nflow * nflow
    if poscost > np.int64(0):
        poscost = (poscost + nflowsq - np.int64(1)) // nflowsq   # ceiling
    else:
        poscost = -((-poscost) // nflowsq)                        # floor (neg)
    if negcost > np.int64(0):
        negcost = (negcost + nflowsq - np.int64(1)) // nflowsq
    else:
        negcost = -((-negcost) // nflowsq)

    return poscost, negcost


@njit(cache=True)
def _calc_cost_defo_incr(offset_s: np.int16, sigsq_s: np.int16,
                          dzmax_s: np.int16, laycost_s: np.int16,
                          flow: np.int64, nflow: np.int64,
                          nshortcycle: np.int64) -> Tuple[np.int64, np.int64]:
    """Return (poscost, negcost) for DEFO mode.

    Mirrors CalcCostDefo() from snaphu_cost.c (lines ~390-460).
    Shelf cost structure: quadratic below dzmax, constant above.
    """
    # Mirrors CalcCostDefo() in snaphu_cost.c — same abs/offset sign as SMOOTH.
    offset     = np.int64(offset_s)
    sigsq      = np.int64(sigsq_s)
    dzmax      = np.int64(dzmax_s)
    laycost_v  = np.int64(laycost_s)
    NOCOSTSHELF_V = np.int64(-32000)   # NOCOSTSHELF = -LARGESHORT

    if sigsq <= 0:
        sigsq = np.int64(1)
    if sigsq == np.int64(32000):
        return np.int64(0), np.int64(0)

    layfalloffconst = np.int64(2)   # params.layfalloffconst default=2; passed as int

    idz1    = flow * nshortcycle + offset
    if idz1 < np.int64(0): idz1 = -idz1
    idz2pos = (flow + nflow) * nshortcycle + offset
    if idz2pos < np.int64(0): idz2pos = -idz2pos
    idz2neg = (flow - nflow) * nshortcycle + offset
    if idz2neg < np.int64(0): idz2neg = -idz2neg

    # cost1
    if idz1 > dzmax:
        idz1_sh = idz1 - dzmax
        cost1 = (idz1_sh * idz1_sh) // (layfalloffconst * sigsq) + laycost_v
    else:
        cost1 = (idz1 * idz1) // sigsq
        if laycost_v != NOCOSTSHELF_V and cost1 > laycost_v:
            cost1 = laycost_v

    # poscost
    if idz2pos > dzmax:
        idz2pos_sh = idz2pos - dzmax
        poscost = (idz2pos_sh * idz2pos_sh) // (layfalloffconst * sigsq) + laycost_v - cost1
    else:
        poscost = (idz2pos * idz2pos) // sigsq
        if laycost_v != NOCOSTSHELF_V and poscost > laycost_v:
            poscost = laycost_v - cost1
        else:
            poscost -= cost1

    # negcost
    if idz2neg > dzmax:
        idz2neg_sh = idz2neg - dzmax
        negcost = (idz2neg_sh * idz2neg_sh) // (layfalloffconst * sigsq) + laycost_v - cost1
    else:
        negcost = (idz2neg * idz2neg) // sigsq
        if laycost_v != NOCOSTSHELF_V and negcost > laycost_v:
            negcost = laycost_v - cost1
        else:
            negcost -= cost1

    nflowsq = nflow * nflow
    if poscost > np.int64(0):
        poscost = (poscost + nflowsq - np.int64(1)) // nflowsq
    else:
        poscost = -((-poscost) // nflowsq)
    if negcost > np.int64(0):
        negcost = (negcost + nflowsq - np.int64(1)) // nflowsq
    else:
        negcost = -((-negcost) // nflowsq)

    return poscost, negcost


@njit(cache=True)
def _recalc_cost(costmode: np.int64,
                 costs_off: np.ndarray,   # shape (narc,) int16 'offset'
                 costs_sig: np.ndarray,   # shape (narc,) int16 'sigsq'
                 costs_dzm: np.ndarray,   # shape (narc,) int16 'dzmax'   (DEFO only)
                 costs_lay: np.ndarray,   # shape (narc,) int16 'laycost' (DEFO only)
                 incr_pos: np.ndarray,    # shape (narc,) int16 writable
                 incr_neg: np.ndarray,    # shape (narc,) int16 writable
                 arc_flat: np.int64,
                 flow: np.int64,
                 nflow: np.int64,
                 nshortcycle: np.int64) -> None:
    """Recompute incrcosts for one arc, clip to ±LARGESHORT. In-place."""
    LS = np.int64(32000)  # LARGESHORT
    if costmode == np.int64(3):   # SMOOTH = 3
        pc, nc_ = _calc_cost_smooth_incr(
            costs_off[arc_flat], costs_sig[arc_flat],
            flow, nflow, nshortcycle)
    else:   # DEFO = 2
        pc, nc_ = _calc_cost_defo_incr(
            costs_off[arc_flat], costs_sig[arc_flat],
            costs_dzm[arc_flat], costs_lay[arc_flat],
            flow, nflow, nshortcycle)

    if pc > LS:  pc = LS
    elif pc < -LS: pc = -LS
    if nc_ > LS:  nc_ = LS
    elif nc_ < -LS: nc_ = -LS
    incr_pos[arc_flat] = np.int16(pc)
    incr_neg[arc_flat] = np.int16(nc_)


@njit(cache=True)
def _get_cost(incr_pos: np.ndarray, incr_neg: np.ndarray,
              arc_flat: np.int64, arcdir: np.int64) -> np.int64:
    """GetCost: return poscost (arcdir>0) or negcost (arcdir<0)."""
    if arcdir > 0:
        return np.int64(incr_pos[arc_flat])
    else:
        return np.int64(incr_neg[arc_flat])


# ---------------------------------------------------------------------------
# Arc geometry helpers (inlined into the kernel)
# ---------------------------------------------------------------------------
# C NeighborNodeGrid (arcnum ∈ {-4,-3,-2,-1} for interior; 0..ngroundarcs-1 for ground)
# C GetArcGrid: returns (arcrow, arccol, arcdir) given (from_id, to_id)
#
# Both are compiled as @njit helpers called from the main kernel.
# We pass ni, nc (= nrow-1, ncol-1) since nrow = ni+1, ncol = nc+1.

@njit(cache=True)
def _get_arc_num_lims(fromrow: np.int32, ngroundarcs: np.int64
                      ) -> Tuple[np.int64, np.int64]:
    """Return (arcnum_start, upperarcnum). Mirrors GetArcNumLims()."""
    if fromrow < 0:
        return np.int64(-1), ngroundarcs - np.int64(1)
    else:
        return np.int64(-5), np.int64(-1)


@njit(cache=True)
def _neighbor_node_grid(row: np.int32, col: np.int32,
                        arcnum: np.int64, ngroundarcs: np.int64,
                        ni: np.int64, nc: np.int64,
                        ground_id: np.int64,
                        ) -> Tuple[np.int64, np.int64, np.int64, np.int64]:
    """Return (neighbor_flat_id, arcrow, arccol, arcdir).
    
    Mirrors NeighborNodeGrid() in snaphu_solver.c:2094.
    row, col: of the current node (-2,-2 for ground).
    ni = nrow-1, nc = ncol-1.
    """
    ncol = nc + np.int64(1)
    nrow = ni + np.int64(1)

    if row < 0:
        # Ground node: perimeter arcs
        an = arcnum
        if an < ni:
            arcrow = an;            arccol = np.int64(0);    arcdir = np.int64(1)
            nb_id  = an * nc + np.int64(0)   # nodes[arcnum][0]
        elif an < np.int64(2) * ni:
            r2 = an - ni
            arcrow = r2;            arccol = nc;             arcdir = np.int64(-1)
            nb_id  = r2 * nc + (nc - np.int64(1))  # nodes[r2][nc-1]
        elif an < np.int64(2) * ni + nc - np.int64(2):
            ac2 = an - np.int64(2) * ni + np.int64(1)
            arcrow = ni;            arccol = ac2;            arcdir = np.int64(1)
            nb_id  = np.int64(0) * nc + ac2             # nodes[0][arccol]
        else:
            ac3 = an - (np.int64(2) * ni + nc - np.int64(3))
            arcrow = np.int64(2) * ni;   arccol = ac3;    arcdir = np.int64(-1)
            nb_id  = (ni - np.int64(1)) * nc + ac3      # nodes[ni-1][arccol]
        return nb_id, arcrow, arccol, arcdir

    else:
        # Interior node
        r = np.int64(row)
        c = np.int64(col)

        if arcnum == np.int64(-4):   # right
            arcrow = r; arccol = c + np.int64(1); arcdir = np.int64(1)
            if c == nc - np.int64(1):
                nb_id = ground_id
            else:
                nb_id = r * nc + (c + np.int64(1))
        elif arcnum == np.int64(-3):   # down
            arcrow = nrow + r; arccol = c; arcdir = np.int64(1)
            if r == ni - np.int64(1):
                nb_id = ground_id
            else:
                nb_id = (r + np.int64(1)) * nc + c
        elif arcnum == np.int64(-2):   # left
            arcrow = r; arccol = c; arcdir = np.int64(-1)
            if c == np.int64(0):
                nb_id = ground_id
            else:
                nb_id = r * nc + (c - np.int64(1))
        else:   # -1: up
            arcrow = ni + r; arccol = c; arcdir = np.int64(-1)
            if r == np.int64(0):
                nb_id = ground_id
            else:
                nb_id = (r - np.int64(1)) * nc + c
        return nb_id, arcrow, arccol, arcdir


@njit(cache=True)
def _get_arc_grid(from_row: np.int32, from_col: np.int32,
                  to_row: np.int32, to_col: np.int32,
                  ni: np.int64, nc: np.int64,
                  ground_id: np.int64,
                  from_id: np.int64, to_id: np.int64,
                  ) -> Tuple[np.int64, np.int64, np.int64]:
    """Return (arcrow, arccol, arcdir). Mirrors GetArcGrid() in snaphu_solver.c."""
    fr = np.int64(from_row); fc = np.int64(from_col)
    tr = np.int64(to_row);   tc = np.int64(to_col)
    nrow = ni + np.int64(1)

    if fr == tr:
        if fc == tc - np.int64(1):
            return fr, tc, np.int64(1)
        else:   # fc == tc + 1
            return fr, fc, np.int64(-1)
    elif fr == tr - np.int64(1):
        return tr + nrow - np.int64(1), fc, np.int64(1)
    elif fr == tr + np.int64(1):
        return fr + nrow - np.int64(1), fc, np.int64(-1)
    elif from_id == ground_id:
        # from is ground; deduce arc from perimeter position of 'to'
        if fc < nc - np.int64(1) and tc == fc + np.int64(1):
            return tr, tc, np.int64(-1)
        elif fc > np.int64(0) and tc == fc - np.int64(1):
            return tr, tc, np.int64(1)
        elif tr < ni - np.int64(1) and tr == fr + np.int64(1):
            return tr + np.int64(1) + nrow - np.int64(1), tc, np.int64(-1)
        else:
            return tr + nrow - np.int64(1), tc, np.int64(1)
    elif to_id == ground_id:
        # to is ground
        if fc < nc - np.int64(1) and tc == fc + np.int64(1):
            return fr, fc + np.int64(1), np.int64(1)
        elif fc > np.int64(0) and tc == fc - np.int64(1):
            return fr, fc, np.int64(-1)
        elif fr < ni - np.int64(1) and fr + np.int64(1) == tr:
            return fr + np.int64(1) + nrow - np.int64(1), fc, np.int64(1)
        else:
            return fr + nrow - np.int64(1), fc, np.int64(-1)
    # Perimeter / ground arcs (fallback — mirror scalar port's GetArcGrid_ts)
    elif fc == np.int64(0):
        return fr, np.int64(0), np.int64(-1)
    elif fc == nc - np.int64(1):
        return fr, nc, np.int64(1)
    elif fr == np.int64(0):
        return nrow - np.int64(1), fc, np.int64(-1)
    elif fr == ni - np.int64(1):
        return np.int64(2) * (nrow - np.int64(1)), fc, np.int64(1)
    elif tc == np.int64(0):
        return tr, np.int64(0), np.int64(1)
    elif tc == nc - np.int64(1):
        return tr, nc, np.int64(-1)
    elif tr == np.int64(0):
        return nrow - np.int64(1), tc, np.int64(1)
    else:
        return np.int64(2) * (nrow - np.int64(1)), tc, np.int64(-1)


# ---------------------------------------------------------------------------
# Bucket operations (@njit)
# ---------------------------------------------------------------------------

@njit(cache=True)
def _bkt_insert(node_next: np.ndarray, node_prev: np.ndarray,
                node_group: np.ndarray,
                bkt_head: np.ndarray,
                nid: np.int64, ind: np.int64, bkt_minind: np.int64) -> None:
    """Prepend node nid into bucket at absolute index ind.
    C BucketInsert: node inserted at HEAD of doubly-linked list in bucket.
    """
    b = ind - bkt_minind
    old_head = np.int64(bkt_head[b])
    node_next[nid] = np.int32(old_head)
    node_prev[nid] = np.int32(-1)
    if old_head >= np.int64(0):
        node_prev[old_head] = np.int32(nid)
    bkt_head[b] = np.int32(nid)
    node_group[nid] = np.int64(-2)   # INBUCKET


@njit(cache=True)
def _bkt_remove(node_next: np.ndarray, node_prev: np.ndarray,
                bkt_head: np.ndarray,
                nid: np.int64, ind: np.int64, bkt_minind: np.int64) -> None:
    """Remove node nid from bucket at absolute index ind."""
    b = ind - bkt_minind
    prv = np.int64(node_prev[nid])
    nxt = np.int64(node_next[nid])
    if prv >= np.int64(0):
        node_next[prv] = np.int32(nxt)
    else:
        bkt_head[b] = np.int32(nxt)
    if nxt >= np.int64(0):
        node_prev[nxt] = np.int32(prv)
    node_next[nid] = np.int32(-1)
    node_prev[nid] = np.int32(-1)


@njit(cache=True)
def _min_out_cost_node(node_next: np.ndarray, node_prev: np.ndarray,
                       node_group: np.ndarray,
                       bkt_head: np.ndarray,
                       bkt_curr: np.int64,
                       bkt_maxind: np.int64,
                       bkt_minind: np.int64,
                       ) -> Tuple[np.int64, np.int64]:
    """MinOutCostNode: pop cheapest node from bucket priority queue.

    Returns (node_id, new_bkt_curr).  node_id = -1 if exhausted.
    """
    curr = bkt_curr
    while curr <= bkt_maxind:
        b = curr - bkt_minind
        head = np.int64(bkt_head[b])
        if head >= np.int64(0):
            _bkt_remove(node_next, node_prev, bkt_head, head, curr, bkt_minind)
            node_group[head] = np.int64(1)   # mark as on-tree (group=1 in C)
            return head, curr
        curr += np.int64(1)
    return np.int64(-1), curr


# ---------------------------------------------------------------------------
# AddNewNode (@njit)
# ---------------------------------------------------------------------------

@njit(cache=True)
def _add_new_node(from_id: np.int64, to_id: np.int64,
                  arcdir: np.int64, arcrow: np.int64, arccol: np.int64,
                  nflow: np.int64,
                  node_outcost: np.ndarray, node_pred: np.ndarray,
                  node_group: np.ndarray,
                  node_next: np.ndarray, node_prev: np.ndarray,
                  incr_pos: np.ndarray, incr_neg: np.ndarray,
                  bkt_head: np.ndarray,
                  bkt_curr_ref: np.ndarray,   # shape (1,) int64 scalar ref
                  bkt_minind: np.int64, bkt_maxind: np.int64,
                  ncol: np.int64) -> None:
    """Mirrors AddNewNode() in snaphu_solver.c:986."""
    arc_flat = arcrow * ncol + arccol
    newoutcost = node_outcost[from_id] + _get_cost(incr_pos, incr_neg, arc_flat, arcdir)

    oc_to = node_outcost[to_id]
    pred_to = np.int64(node_pred[to_id])
    if newoutcost < oc_to or pred_to == from_id:
        # Remove from bucket if already there
        if node_group[to_id] == np.int64(-2):   # INBUCKET
            old = oc_to
            if old < bkt_maxind:
                if old > bkt_minind:
                    _bkt_remove(node_next, node_prev, bkt_head, to_id, old, bkt_minind)
                else:
                    _bkt_remove(node_next, node_prev, bkt_head, to_id, bkt_minind, bkt_minind)
            else:
                _bkt_remove(node_next, node_prev, bkt_head, to_id, bkt_maxind, bkt_minind)

        node_outcost[to_id] = newoutcost
        node_pred[to_id] = np.int32(from_id)

        if newoutcost < bkt_maxind:
            clamped = newoutcost if newoutcost > bkt_minind else bkt_minind
        else:
            clamped = bkt_maxind
        _bkt_insert(node_next, node_prev, node_group, bkt_head, to_id, clamped, bkt_minind)
        if clamped < bkt_curr_ref[0]:
            bkt_curr_ref[0] = clamped


# ---------------------------------------------------------------------------
# FindApex (@njit)
# ---------------------------------------------------------------------------

@njit(cache=True)
def _find_apex(from_id: np.int64, to_id: np.int64,
               node_level: np.ndarray, node_pred: np.ndarray) -> np.int64:
    """Mirrors FindApex(): find deepest common ancestor."""
    f = from_id; t = to_id
    _fa_g = np.int64(0)
    while node_level[f] > node_level[t]:
        _fa_g += np.int64(1)
        if _fa_g > np.int64(200_000): return np.int64(-11111)
        f = np.int64(node_pred[f])
    while node_level[t] > node_level[f]:
        _fa_g += np.int64(1)
        if _fa_g > np.int64(200_000): return np.int64(-11111)
        t = np.int64(node_pred[t])
    while f != t:
        _fa_g += np.int64(1)
        if _fa_g > np.int64(200_000): return np.int64(-11111)
        f = np.int64(node_pred[f])
        t = np.int64(node_pred[t])
    return f


# ---------------------------------------------------------------------------
# CheckArcReducedCost — appends to candidate arrays
# ---------------------------------------------------------------------------

@njit(cache=True)
def _check_arc_reduced_cost(from_id: np.int64, to_id: np.int64,
                             apex_id: np.int64,
                             arcrow: np.int64, arccol: np.int64,
                             arcdir: np.int64,
                             node_outcost: np.ndarray,
                             node_incost: np.ndarray,
                             incr_pos: np.ndarray, incr_neg: np.ndarray,
                             iscandidate: np.ndarray,
                             # candidate arrays (flat, pre-allocated)
                             cand_from: np.ndarray,
                             cand_to: np.ndarray,
                             cand_violation: np.ndarray,
                             cand_arcrow: np.ndarray,
                             cand_arccol: np.ndarray,
                             cand_arcdir: np.ndarray,
                             cand_n_ref: np.ndarray,   # shape (1,) int64
                             cand_cap_ref: np.ndarray, # shape (1,) int64
                             ncol: np.int64) -> None:
    """Mirrors CheckArcReducedCost(). Appends to candidate arrays if violation<0."""
    arc_flat = arcrow * ncol + arccol
    if iscandidate[arc_flat]:
        return
    if apex_id == np.int64(-1) or apex_id == np.int64(-2):
        return

    apexcost = node_outcost[apex_id] + node_incost[apex_id]

    fwd = _get_cost(incr_pos, incr_neg, arc_flat, arcdir)
    violation = fwd + node_outcost[from_id] + node_incost[to_id] - apexcost

    fr_used = from_id; to_used = to_id; ad_used = arcdir

    if violation < np.int64(0):
        ad_used = arcdir * np.int64(2)
    else:
        rev = _get_cost(incr_pos, incr_neg, arc_flat, -arcdir)
        violation = rev + node_outcost[to_id] + node_incost[from_id] - apexcost
        if violation < np.int64(0):
            ad_used = arcdir * np.int64(-2)
            fr_used = to_id; to_used = from_id
        else:
            violation = fwd + node_outcost[from_id] - node_outcost[to_id]
            if violation >= np.int64(0):
                violation = rev + node_outcost[to_id] - node_outcost[from_id]
                if violation < np.int64(0):
                    ad_used = -arcdir
                    fr_used = to_id; to_used = from_id
                else:
                    return
            # else violation < 0, ad_used = arcdir already

    if violation >= np.int64(0):
        return

    # Append to candidate bag
    n = cand_n_ref[0]
    # NOTE: we cannot realloc inside @njit — caller must pre-allocate enough.
    # We use cand_cap_ref as a capacity guard; if full, we silently drop.
    # (Caller sizes cap = max_arcs; this is safe because narc is the upper bound.)
    if n < cand_cap_ref[0]:
        cand_from[n]      = np.int32(fr_used)
        cand_to[n]        = np.int32(to_used)
        cand_violation[n] = violation
        cand_arcrow[n]    = np.int32(arcrow)
        cand_arccol[n]    = np.int32(arccol)
        cand_arcdir[n]    = np.int8(ad_used)
        cand_n_ref[0]     = n + np.int64(1)
        iscandidate[arc_flat] = np.int8(1)


# ---------------------------------------------------------------------------
# SetupIncrFlowCosts (@njit) — initialise incrcosts for all arcs
# ---------------------------------------------------------------------------

@njit(cache=True)
def _setup_incr_flow_costs(costmode: np.int64,
                            costs_off: np.ndarray,
                            costs_sig: np.ndarray,
                            costs_dzm: np.ndarray,
                            costs_lay: np.ndarray,
                            incr_pos: np.ndarray,
                            incr_neg: np.ndarray,
                            flows: np.ndarray,
                            nflow: np.int64,
                            nrow: np.int64, ncol: np.int64,
                            nshortcycle: np.int64) -> None:
    """Recompute incrcosts for ALL arcs. Mirrors SetupIncrFlowCosts()."""
    for arcrow in range(np.int64(2) * nrow - np.int64(1)):
        maxcol = ncol if arcrow < nrow - np.int64(1) else ncol - np.int64(1)
        for arccol in range(maxcol):
            arc_flat = arcrow * ncol + arccol
            flow = np.int64(flows[arcrow, arccol])
            _recalc_cost(costmode, costs_off, costs_sig, costs_dzm, costs_lay,
                         incr_pos, incr_neg, arc_flat, flow, nflow, nshortcycle)


# ---------------------------------------------------------------------------
# The main TreeSolve kernel (@njit)
# ---------------------------------------------------------------------------
# This is the hot path.  All work that can be inside @njit is here.
# The kernel modifies flows, incr_pos/neg, apex_arr, iscandidate,
# and all node SoA arrays in-place.
#
# Return: (inondegen: int64)
# ---------------------------------------------------------------------------

@njit(cache=True)
def _tree_solve_kernel(
        # node SoA
        node_row: np.ndarray, node_col: np.ndarray,
        node_next: np.ndarray, node_prev: np.ndarray,
        node_pred: np.ndarray, node_level: np.ndarray,
        node_group: np.ndarray, node_incost: np.ndarray,
        node_outcost: np.ndarray,
        ground_id: np.int64,
        # arc arrays
        incr_pos: np.ndarray, incr_neg: np.ndarray,
        flows: np.ndarray,    # (2*nrow-1, ncol) int16 2D — modified in place
        # cost arrays (for ReCalcCost)
        costmode: np.int64,
        costs_off: np.ndarray, costs_sig: np.ndarray,
        costs_dzm: np.ndarray, costs_lay: np.ndarray,
        # apex/iscandidate flat arrays
        apex_arr: np.ndarray,       # (narc,) int32: flat node id or -1/NONTREEARC
        iscandidate: np.ndarray,    # (narc,) int8
        # candidate pre-allocated arrays (sized narc)
        cand_from_A: np.ndarray, cand_to_A: np.ndarray,
        cand_viol_A: np.ndarray, cand_ar_A: np.ndarray,
        cand_ac_A: np.ndarray, cand_ad_A: np.ndarray,
        cand_from_B: np.ndarray, cand_to_B: np.ndarray,
        cand_viol_B: np.ndarray, cand_ar_B: np.ndarray,
        cand_ac_B: np.ndarray, cand_ad_B: np.ndarray,
        # bucket arrays
        bkt_head: np.ndarray,   # (bkt_size,) int32
        # scalar params (passed as int64/float64 scalars)
        bkt_minind: np.int64, bkt_maxind: np.int64,
        nflow: np.int64, nshortcycle: np.int64,
        nconnected: np.int64,
        ni: np.int64, nc: np.int64,
        ngroundarcs: np.int64,
        source_id: np.int64,
        maxnewnodeconst: np.float64,
        nmajorprune: np.int64, prunecostthresh: np.int64,
) -> np.int64:
    """Core network-flow optimizer — mirrors C TreeSolve() logic.

    All pointer chasing is replaced by flat-index array indexing.
    Candidate bags are double-buffered (A and B); the one currently
    being populated is 'bag', the one being processed is 'lst'.
    Sizes tracked via cand_n_bag (shape (1,)) and cand_n_lst (shape (1,)).
    """
    ncol = nc + np.int64(1)
    narc_row = ncol   # width of flat arc array in row dimension

    # bkt_curr tracks the minimum non-empty bucket index
    bkt_curr_ref = np.zeros(1, dtype=np.int64)
    bkt_curr_ref[0] = bkt_maxind

    # ---- InitTree: place source on tree and scan its neighbours ----
    sid = source_id
    node_group[sid]   = np.int64(1)
    node_outcost[sid] = np.int64(0)
    node_incost[sid]  = np.int64(0)
    node_pred[sid]    = np.int32(-1)
    node_prev[sid]    = np.int32(sid)   # circular self-thread
    node_next[sid]    = np.int32(sid)
    node_level[sid]   = np.int64(0)

    arcnum, upperarcnum = _get_arc_num_lims(node_row[sid], ngroundarcs)
    while arcnum < upperarcnum:
        arcnum += np.int64(1)
        to_id, arcrow, arccol, arcdir = _neighbor_node_grid(
            node_row[sid], node_col[sid], arcnum, ngroundarcs, ni, nc, ground_id)
        if (node_group[to_id] != np.int64(-4)   # PRUNED
                and node_group[to_id] != np.int64(-5)):   # MASKED
            _add_new_node(sid, to_id, arcdir, arcrow, arccol,
                          nflow, node_outcost, node_pred, node_group,
                          node_next, node_prev,
                          incr_pos, incr_neg, bkt_head, bkt_curr_ref,
                          bkt_minind, bkt_maxind, narc_row)

    # ---- double-buffer candidate lists ----
    # 'bag' is the currently-accumulating list (write), 'lst' is the current
    # processing list (read).  We alternate between A and B.
    cand_n_bag = np.zeros(1, dtype=np.int64)
    cand_n_lst = np.zeros(1, dtype=np.int64)
    cap_ref = np.zeros(1, dtype=np.int64)
    cap_ref[0] = np.int64(len(cand_from_A))

    # buf_sel[0]: 0 → bag=A(accumulate), lst=B(process)
    #             1 → bag=B(accumulate), lst=A(process)
    # numba 0.65 does not support inner def/closures; use explicit if/else on buf_sel.
    buf_sel = np.zeros(1, dtype=np.int64)

    cand_n_bag[0] = np.int64(0)

    groupcounter = np.int64(2)
    ipivots      = np.int64(0)
    inondegen    = np.int64(0)
    treesize     = np.int64(1)
    nmajor       = np.int64(0)
    maxnewnodes  = np.int64(math.ceil(float(nconnected) * maxnewnodeconst))
    npruned      = np.int64(0)

    VERYFAR_L    = np.int64(2_000_000_000)
    INBUCKET_L   = np.int64(-2)
    PRUNED_L     = np.int64(-4)
    MASKED_L     = np.int64(-5)
    NONTREEARC_L = np.int64(-2)   # apex sentinel
    NULL_apex_L  = np.int64(-1)

    # ---- outer loop: grow spanning tree ----
    while treesize < nconnected:

        nnewnodes = np.int64(0)
        while nnewnodes < maxnewnodes and treesize < nconnected:
            # MinOutCostNode
            to_id, bkt_curr_ref[0] = _min_out_cost_node(
                node_next, node_prev, node_group, bkt_head,
                bkt_curr_ref[0], bkt_maxind, bkt_minind)
            if to_id < np.int64(0):
                break

            from_id = np.int64(node_pred[to_id])
            arcrow2, arccol2, arcdir2 = _get_arc_grid(
                node_row[from_id], node_col[from_id],
                node_row[to_id], node_col[to_id],
                ni, nc, ground_id, from_id, to_id)
            arc_flat2 = arcrow2 * narc_row + arccol2

            node_group[to_id]   = np.int64(1)
            node_level[to_id]   = node_level[from_id] + np.int64(1)
            node_incost[to_id]  = node_incost[from_id] + _get_cost(
                incr_pos, incr_neg, arc_flat2, -arcdir2)
            # Insert into doubly-linked thread after from_id
            nxt_from = np.int64(node_next[from_id])
            node_next[to_id]    = np.int32(nxt_from)
            node_prev[to_id]    = np.int32(from_id)
            node_prev[nxt_from] = np.int32(to_id)
            node_next[from_id]  = np.int32(to_id)

            # Scan new node's neighbours
            cur_id = to_id
            arcnum2, upperarcnum2 = _get_arc_num_lims(node_row[cur_id], ngroundarcs)
            while arcnum2 < upperarcnum2:
                arcnum2 += np.int64(1)
                nb_id, arcrow_n, arccol_n, arcdir_n = _neighbor_node_grid(
                    node_row[cur_id], node_col[cur_id],
                    arcnum2, ngroundarcs, ni, nc, ground_id)
                arc_flat_n = arcrow_n * narc_row + arccol_n

                grp_nb = node_group[nb_id]
                if grp_nb > np.int64(0):
                    pred_cur = np.int64(node_pred[cur_id])
                    if nb_id != pred_cur:
                        cx_id = _find_apex(cur_id, nb_id, node_level, node_pred)
                        if cx_id == np.int64(-11111):
                            return np.int64(-11111)  # find_apex pred cycle
                        apex_arr[arc_flat_n] = np.int32(cx_id)
                        # CheckArcReducedCost inline
                        if buf_sel[0] == np.int64(0):
                            _check_arc_reduced_cost(
                                cur_id, nb_id, cx_id,
                                arcrow_n, arccol_n, arcdir_n,
                                node_outcost, node_incost,
                                incr_pos, incr_neg, iscandidate,
                                cand_from_A, cand_to_A, cand_viol_A,
                                cand_ar_A, cand_ac_A, cand_ad_A,
                                cand_n_bag, cap_ref, narc_row)
                        else:
                            _check_arc_reduced_cost(
                                cur_id, nb_id, cx_id,
                                arcrow_n, arccol_n, arcdir_n,
                                node_outcost, node_incost,
                                incr_pos, incr_neg, iscandidate,
                                cand_from_B, cand_to_B, cand_viol_B,
                                cand_ar_B, cand_ac_B, cand_ad_B,
                                cand_n_bag, cap_ref, narc_row)
                    else:
                        apex_arr[arc_flat_n] = np.int32(-1)   # NULL
                elif grp_nb != PRUNED_L and grp_nb != MASKED_L:
                    _add_new_node(cur_id, nb_id, arcdir_n,
                                  arcrow_n, arccol_n, nflow,
                                  node_outcost, node_pred, node_group,
                                  node_next, node_prev,
                                  incr_pos, incr_neg, bkt_head, bkt_curr_ref,
                                  bkt_minind, bkt_maxind, narc_row)

            nnewnodes += np.int64(1)
            treesize  += np.int64(1)

        # ---- inner loop: process candidate list ----
        _cand_iter_guard = np.int64(0)
        # C has no cycling guard; 100× nconnected is a safety cap
        # against true infinite cycling.  10× was too tight for some patches
        # (e.g. 100x100 ALOS_haiti at r0=800 c0=500 requires >10× passes)
        # but 10000× causes multi-hour runtimes on truly hard instances.
        # 100× is a pragmatic middle ground matching observed real-data needs.
        _cand_max_iter   = nconnected * np.int64(100)
        while cand_n_bag[0] > np.int64(0):
            _cand_iter_guard += np.int64(1)
            if _cand_iter_guard > _cand_max_iter:
                # cycling detected — return sentinel -9999
                return np.int64(-9999)

            # Swap bag ↔ list
            cand_n_lst[0] = cand_n_bag[0]
            cand_n_bag[0] = np.int64(0)
            buf_sel[0]    = np.int64(1) - buf_sel[0]   # flip

            # Sort candidate list: augmenting (|arcdir|>1) first, then by violation.
            # We use a simple insertion sort (numba-compatible; list is typically small).
            nL = cand_n_lst[0]
            # Select correct list arrays
            if buf_sel[0] == np.int64(0):
                # after flip, lst is now A
                lf = cand_from_A; lt = cand_to_A; lv = cand_viol_A
                la_r = cand_ar_A; la_c = cand_ac_A; la_d = cand_ad_A
            else:
                lf = cand_from_B; lt = cand_to_B; lv = cand_viol_B
                la_r = cand_ar_B; la_c = cand_ac_B; la_d = cand_ad_B

            # Insertion sort on the list (typically ≤ hundreds of elements)
            for i_sort in range(np.int64(1), nL):
                kf = lf[i_sort]; kt = lt[i_sort]; kv = lv[i_sort]
                kr = la_r[i_sort]; kc = la_c[i_sort]; kd = la_d[i_sort]
                key_aug = np.int64(1) if (kd > np.int64(1) or kd < np.int64(-1)) else np.int64(0)
                j = i_sort - np.int64(1)
                while j >= np.int64(0):
                    jd = la_d[j]
                    jv = lv[j]
                    j_aug = np.int64(1) if (jd > np.int64(1) or jd < np.int64(-1)) else np.int64(0)
                    # j should come AFTER key? → j is "bigger" in sort order
                    # sort key: (0 if aug else 1, violation)
                    j_big = (j_aug < key_aug) or (j_aug == key_aug and jv > kv)
                    if not j_big:
                        break
                    lf[j+1] = lf[j]; lt[j+1] = lt[j]; lv[j+1] = lv[j]
                    la_r[j+1] = la_r[j]; la_c[j+1] = la_c[j]; la_d[j+1] = la_d[j]
                    j -= np.int64(1)
                lf[j+1] = kf; lt[j+1] = kt; lv[j+1] = kv
                la_r[j+1] = kr; la_c[j+1] = kc; la_d[j+1] = kd

            # Normalize arcdir to ±1
            for i_nd in range(nL):
                ad = np.int64(la_d[i_nd])
                if ad > np.int64(1):   la_d[i_nd] = np.int8(1)
                elif ad < np.int64(-1): la_d[i_nd] = np.int8(-1)

            # Process candidates
            for i_cand in range(nL):
                from_id = np.int64(lf[i_cand])
                to_id   = np.int64(lt[i_cand])
                arcdir  = np.int64(la_d[i_cand])
                arcrow  = np.int64(la_r[i_cand])
                arccol  = np.int64(la_c[i_cand])
                arc_flat = arcrow * narc_row + arccol

                iscandidate[arc_flat] = np.int8(0)

                apex_id = np.int64(apex_arr[arc_flat])
                if apex_id == NONTREEARC_L:
                    continue

                outcostto = (node_outcost[from_id]
                             + _get_cost(incr_pos, incr_neg, arc_flat, arcdir))
                if apex_id == NULL_apex_L:
                    apex_sum = np.int64(0)
                else:
                    apex_sum = node_outcost[apex_id] + node_incost[apex_id]
                cyclecost = outcostto + node_incost[to_id] - apex_sum

                if not (outcostto < node_outcost[to_id] or cyclecost < np.int64(0)):
                    from_id, to_id = to_id, from_id
                    arcdir = -arcdir
                    outcostto = (node_outcost[from_id]
                                 + _get_cost(incr_pos, incr_neg, arc_flat, arcdir))
                    cyclecost = outcostto + node_incost[to_id] - apex_sum

                if not (outcostto < node_outcost[to_id] or cyclecost < np.int64(0)):
                    continue

                # --- group counter overflow guard ---
                groupcounter += np.int64(1)
                if groupcounter > MAXGROUPBASE:
                    for _ni in range(np.int64(len(node_group))):
                        if node_group[_ni] > np.int64(0):
                            node_group[_ni] = np.int64(1)
                    groupcounter = np.int64(2)

                leavingchild = np.int64(-1)
                fromside     = True

                # ---- augmenting pivot ----
                if cyclecost < np.int64(0):
                    _aug_iter = np.int64(0)
                    while True:
                        _aug_iter += np.int64(1)
                        if _aug_iter > nconnected * np.int64(10):
                            return np.int64(-8888)  # augmenting pivot cycling
                        fromside     = True
                        node1        = from_id
                        node2        = to_id
                        leavingchild = np.int64(-1)

                        cur_flow = np.int64(flows[arcrow, arccol])
                        flows[arcrow, arccol] = np.int16(cur_flow + arcdir * nflow)
                        _recalc_cost(costmode, costs_off, costs_sig, costs_dzm, costs_lay,
                                     incr_pos, incr_neg, arc_flat,
                                     np.int64(flows[arcrow, arccol]), nflow, nshortcycle)
                        violation = _get_cost(incr_pos, incr_neg, arc_flat, arcdir)

                        while node_level[node1] > node_level[node2]:
                            ar1, ac1, ad1 = _get_arc_grid(
                                node_row[np.int64(node_pred[node1])],
                                node_col[np.int64(node_pred[node1])],
                                node_row[node1], node_col[node1],
                                ni, nc, ground_id,
                                np.int64(node_pred[node1]), node1)
                            af1 = ar1 * narc_row + ac1
                            new_f = np.int64(flows[ar1, ac1]) + ad1 * nflow
                            flows[ar1, ac1] = np.int16(new_f)
                            _recalc_cost(costmode, costs_off, costs_sig, costs_dzm, costs_lay,
                                         incr_pos, incr_neg, af1,
                                         np.int64(flows[ar1, ac1]), nflow, nshortcycle)
                            if leavingchild < np.int64(0) and flows[ar1, ac1] == np.int16(0):
                                leavingchild = node1
                            violation += _get_cost(incr_pos, incr_neg, af1, ad1)
                            node_group[node1] = groupcounter + np.int64(1)
                            node1 = np.int64(node_pred[node1])

                        while node_level[node2] > node_level[node1]:
                            ar2, ac2, ad2 = _get_arc_grid(
                                node_row[np.int64(node_pred[node2])],
                                node_col[np.int64(node_pred[node2])],
                                node_row[node2], node_col[node2],
                                ni, nc, ground_id,
                                np.int64(node_pred[node2]), node2)
                            af2 = ar2 * narc_row + ac2
                            new_f2 = np.int64(flows[ar2, ac2]) - ad2 * nflow
                            flows[ar2, ac2] = np.int16(new_f2)
                            _recalc_cost(costmode, costs_off, costs_sig, costs_dzm, costs_lay,
                                         incr_pos, incr_neg, af2,
                                         np.int64(flows[ar2, ac2]), nflow, nshortcycle)
                            if flows[ar2, ac2] == np.int16(0):
                                leavingchild = node2
                                fromside = False
                            violation += _get_cost(incr_pos, incr_neg, af2, -ad2)
                            node_group[node2] = groupcounter
                            node2 = np.int64(node_pred[node2])

                        while node1 != node2:
                            ar1, ac1, ad1 = _get_arc_grid(
                                node_row[np.int64(node_pred[node1])],
                                node_col[np.int64(node_pred[node1])],
                                node_row[node1], node_col[node1],
                                ni, nc, ground_id,
                                np.int64(node_pred[node1]), node1)
                            ar2, ac2, ad2 = _get_arc_grid(
                                node_row[np.int64(node_pred[node2])],
                                node_col[np.int64(node_pred[node2])],
                                node_row[node2], node_col[node2],
                                ni, nc, ground_id,
                                np.int64(node_pred[node2]), node2)
                            af1 = ar1 * narc_row + ac1
                            af2 = ar2 * narc_row + ac2
                            flows[ar1, ac1] = np.int16(np.int64(flows[ar1, ac1]) + ad1 * nflow)
                            flows[ar2, ac2] = np.int16(np.int64(flows[ar2, ac2]) - ad2 * nflow)
                            _recalc_cost(costmode, costs_off, costs_sig, costs_dzm, costs_lay,
                                         incr_pos, incr_neg, af1,
                                         np.int64(flows[ar1, ac1]), nflow, nshortcycle)
                            _recalc_cost(costmode, costs_off, costs_sig, costs_dzm, costs_lay,
                                         incr_pos, incr_neg, af2,
                                         np.int64(flows[ar2, ac2]), nflow, nshortcycle)
                            violation += (_get_cost(incr_pos, incr_neg, af1, ad1)
                                          + _get_cost(incr_pos, incr_neg, af2, -ad2))
                            if flows[ar2, ac2] == np.int16(0):
                                leavingchild = node2; fromside = False
                            elif leavingchild < np.int64(0) and flows[ar1, ac1] == np.int16(0):
                                leavingchild = node1
                            node_group[node1] = groupcounter + np.int64(1)
                            node_group[node2] = groupcounter
                            node1 = np.int64(node_pred[node1])
                            node2 = np.int64(node_pred[node2])

                        if violation >= np.int64(0):
                            break
                    inondegen += np.int64(1)

                # ---- degenerate pivot ----
                else:
                    fromside     = False
                    node1        = from_id
                    node2        = to_id
                    leavingchild = np.int64(-1)

                    while node_level[node1] > node_level[node2]:
                        node_group[node1] = groupcounter + np.int64(1)
                        node1 = np.int64(node_pred[node1])

                    while node_level[node2] > node_level[node1]:
                        if outcostto < node_outcost[node2]:
                            leavingchild = node2
                            ar2, ac2, ad2 = _get_arc_grid(
                                node_row[np.int64(node_pred[node2])],
                                node_col[np.int64(node_pred[node2])],
                                node_row[node2], node_col[node2],
                                ni, nc, ground_id,
                                np.int64(node_pred[node2]), node2)
                            outcostto += _get_cost(incr_pos, incr_neg,
                                                   ar2 * narc_row + ac2, -ad2)
                        else:
                            outcostto = VERYFAR_L
                        node_group[node2] = groupcounter
                        node2 = np.int64(node_pred[node2])

                    while node1 != node2:
                        if outcostto < node_outcost[node2]:
                            leavingchild = node2
                            ar2, ac2, ad2 = _get_arc_grid(
                                node_row[np.int64(node_pred[node2])],
                                node_col[np.int64(node_pred[node2])],
                                node_row[node2], node_col[node2],
                                ni, nc, ground_id,
                                np.int64(node_pred[node2]), node2)
                            outcostto += _get_cost(incr_pos, incr_neg,
                                                   ar2 * narc_row + ac2, -ad2)
                        else:
                            outcostto = VERYFAR_L
                        node_group[node1] = groupcounter + np.int64(1)
                        node_group[node2] = groupcounter
                        node1 = np.int64(node_pred[node1])
                        node2 = np.int64(node_pred[node2])

                # cycleapex = node1 (= node2)
                cycleapex = node1

                # set leaving parent / fromside
                if leavingchild < np.int64(0):
                    fromside      = True
                    leavingparent = from_id
                else:
                    leavingparent = np.int64(node_pred[leavingchild])

                if fromside:
                    groupcounter += np.int64(1)
                    fromgroup     = groupcounter - np.int64(1)
                    from_id, to_id = to_id, from_id
                else:
                    fromgroup = groupcounter + np.int64(1)

                # ---- NonDegenUpdateChildren (augmenting pivot only) ----
                if cyclecost < np.int64(0):
                    firstfromnode = np.int64(-1)
                    firsttonode   = np.int64(-1)
                    arcnum3, upper3 = _get_arc_num_lims(node_row[cycleapex], ngroundarcs)
                    while arcnum3 < upper3:
                        arcnum3 += np.int64(1)
                        tmpnd, _, _, _ = _neighbor_node_grid(
                            node_row[cycleapex], node_col[cycleapex],
                            arcnum3, ngroundarcs, ni, nc, ground_id)
                        af3 = np.int64(-1)   # placeholder; apex arc
                        # find arc to tmpnd
                        ar3, ac3, _ = _get_arc_grid(
                            node_row[cycleapex], node_col[cycleapex],
                            node_row[tmpnd], node_col[tmpnd],
                            ni, nc, ground_id, cycleapex, tmpnd)
                        af3 = ar3 * narc_row + ac3
                        if (node_group[tmpnd] == groupcounter
                                and np.int64(apex_arr[af3]) == NULL_apex_L):
                            firsttonode = tmpnd
                            if firstfromnode >= np.int64(0):
                                break
                        elif (node_group[tmpnd] == fromgroup
                              and np.int64(apex_arr[af3]) == NULL_apex_L):
                            firstfromnode = tmpnd
                            if firsttonode >= np.int64(0):
                                break

                    node_group[cycleapex] = groupcounter + np.int64(2)

                    # NonDegenUpdateChildren for 'to' subtree
                    if firsttonode >= np.int64(0):
                        _non_degen_update_children(
                            cycleapex, leavingparent, firsttonode,
                            np.int64(0), ngroundarcs, ni, nc, ground_id, narc_row,
                            node_row, node_col, node_pred, node_next, node_level,
                            node_group, node_outcost, node_incost,
                            incr_pos, incr_neg, apex_arr)

                    # NonDegenUpdateChildren for 'from' subtree
                    if firstfromnode >= np.int64(0):
                        _non_degen_update_children(
                            cycleapex, from_id, firstfromnode,
                            np.int64(1), ngroundarcs, ni, nc, ground_id, narc_row,
                            node_row, node_col, node_pred, node_next, node_level,
                            node_group, node_outcost, node_incost,
                            incr_pos, incr_neg, apex_arr)

                    groupcounter = node_group[from_id]
                    apexlistbase = node_group[cycleapex]
                    fromgroup    = node_group[cycleapex]

                else:
                    node_group[cycleapex] = fromgroup
                    groupcounter  += np.int64(2)
                    apexlistbase   = groupcounter + np.int64(1)

                # ---- Remount subtree (C snaphu_solver.c:656-821) ----
                # Order matches C exactly:
                #   1. while(oldmntpt!=leavingparent): remount + rewire threads
                #   2. skipthread = node1->next
                #   3. reset apex for entering/leaving arcs
                #   4. build apexlist using FINAL groupcounter (AFTER remount)
                #   5. scan remounted subtree from 'to'
                if leavingchild < np.int64(0):
                    skipthread = to_id
                else:
                    root     = from_id
                    oldmntpt = to_id

                    # 1. Remount loop — increments groupcounter once per step.
                    # nd1 ends pointing at the last node of the last remounted subtree.
                    nd1 = root   # dummy init; overwritten in first iteration
                    _remount_guard = np.int64(0)
                    while oldmntpt != leavingparent:
                        _remount_guard += np.int64(1)
                        if _remount_guard > nconnected * np.int64(4):
                            return np.int64(-3333)  # remount loop cycling
                        mntpt    = root
                        root     = oldmntpt
                        oldmntpt = np.int64(node_pred[root])
                        node_pred[root] = np.int32(mntpt)

                        ar_mn, ac_mn, ad_mn = _get_arc_grid(
                            node_row[mntpt], node_col[mntpt],
                            node_row[root], node_col[root],
                            ni, nc, ground_id, mntpt, root)
                        af_mn = ar_mn * narc_row + ac_mn

                        dlevel   = node_level[mntpt] - node_level[root] + np.int64(1)
                        doutcost = (node_outcost[mntpt] - node_outcost[root]
                                    + _get_cost(incr_pos, incr_neg, af_mn, ad_mn))
                        dincost  = (node_incost[mntpt] - node_incost[root]
                                    + _get_cost(incr_pos, incr_neg, af_mn, -ad_mn))

                        groupcounter += np.int64(1)
                        nd1 = root
                        startlevel = node_level[root]
                        _thr1_guard = np.int64(0)
                        while True:
                            _thr1_guard += np.int64(1)
                            if _thr1_guard > nconnected * np.int64(4):
                                return np.int64(-6666)  # thread loop 1 cycling
                            node_level[nd1]   += dlevel
                            node_outcost[nd1] += doutcost
                            node_incost[nd1]  += dincost
                            node_group[nd1]    = groupcounter
                            if node_level[np.int64(node_next[nd1])] <= startlevel:
                                break
                            nd1 = np.int64(node_next[nd1])

                        # Rewire threads (C:705-710)
                        # C executes steps sequentially, so C:step3 reads
                        # mntpt->next AFTER C:step1 may have modified it.
                        # When prv_root==mntpt, C:step1 sets mntpt->next=nxt_nd1,
                        # so C:step3 gets nxt_nd1 (not the original mntpt->next=root).
                        # Python pre-reads everything, so we must replicate this.
                        prv_root = np.int64(node_prev[root])
                        nxt_nd1  = np.int64(node_next[nd1])
                        nxt_mnt  = np.int64(node_next[mntpt])
                        if prv_root == mntpt:
                            # C:step1 sets mntpt->next=nxt_nd1 before C:step3 reads it
                            nxt_mnt = nxt_nd1

                        node_next[prv_root] = np.int32(nxt_nd1)
                        node_prev[nxt_nd1]  = np.int32(prv_root)
                        node_next[nd1]      = np.int32(nxt_mnt)
                        node_prev[nxt_mnt]  = np.int32(nd1)
                        node_next[mntpt]    = np.int32(root)
                        node_prev[root]     = np.int32(mntpt)

                    # 2. skipthread (C:713)
                    skipthread = np.int64(node_next[nd1])

                    # 3. Reset apex for entering/leaving arcs (C:715-720)
                    ar_en, ac_en, _ = _get_arc_grid(
                        node_row[from_id], node_col[from_id],
                        node_row[to_id], node_col[to_id],
                        ni, nc, ground_id, from_id, to_id)
                    apex_arr[ar_en * narc_row + ac_en] = np.int32(-1)   # NULL

                    ar_lv, ac_lv, _ = _get_arc_grid(
                        node_row[leavingparent], node_col[leavingparent],
                        node_row[leavingchild], node_col[leavingchild],
                        ni, nc, ground_id, leavingparent, leavingchild)
                    apex_arr[ar_lv * narc_row + ac_lv] = np.int32(cycleapex)

                    # 4. Build apexlist using FINAL groupcounter (AFTER remount,
                    #    C:722-735). Follow leavingchild->pred path in the NEW
                    #    tree (pred pointers already reversed by the remount loop).
                    apexlistlen = groupcounter - apexlistbase + np.int64(2)
                    if apexlistlen < np.int64(1):
                        apexlistlen = np.int64(1)
                    apexlist = np.full(apexlistlen, np.int64(-1), dtype=np.int64)
                    nd2 = leavingchild
                    for g1 in range(groupcounter, apexlistbase - np.int64(1), -np.int64(1)):
                        idx_al = g1 - apexlistbase
                        if np.int64(0) <= idx_al < apexlistlen:
                            apexlist[idx_al] = nd2
                        if np.int64(node_pred[nd2]) >= np.int64(0):
                            nd2 = np.int64(node_pred[nd2])

                    # 5. Scan remounted subtree from 'to' (C:737-821)
                    nd1 = to_id
                    startlevel = node_level[to_id]
                    _thr2_guard = np.int64(0)
                    while True:
                        _thr2_guard += np.int64(1)
                        if _thr2_guard > nconnected * np.int64(4):
                            return np.int64(-4444)  # remounted subtree scan cycling
                        arcnum4, upper4 = _get_arc_num_lims(node_row[nd1], ngroundarcs)
                        while arcnum4 < upper4:
                            arcnum4 += np.int64(1)
                            nd2, ar2, ac2, ad2 = _neighbor_node_grid(
                                node_row[nd1], node_col[nd1],
                                arcnum4, ngroundarcs, ni, nc, ground_id)
                            af4 = ar2 * narc_row + ac2
                            grp2 = node_group[nd2]
                            if grp2 > np.int64(0):
                                ap2 = np.int64(apex_arr[af4])
                                if (grp2 < node_group[nd1]
                                        and ap2 != NONTREEARC_L
                                        and ap2 != NULL_apex_L):
                                    idx_al4 = grp2 - apexlistbase
                                    if np.int64(0) <= idx_al4 < apexlistlen:
                                        apex_arr[af4] = np.int32(apexlist[idx_al4])
                                    else:
                                        if np.int64(0) <= ap2 < np.int64(len(node_level)):
                                            if node_level[ap2] > node_level[cycleapex]:
                                                apex_arr[af4] = np.int32(cycleapex)
                                            elif ap2 == cycleapex:
                                                tmpnd2 = nd2
                                                _g_guard = np.int64(0)
                                                while node_group[tmpnd2] != fromgroup:
                                                    _g_guard += np.int64(1)
                                                    if _g_guard > nconnected * np.int64(4):
                                                        return np.int64(-2222)  # fromgroup trace cycling
                                                    tmpnd2 = np.int64(node_pred[tmpnd2])
                                                apex_arr[af4] = np.int32(tmpnd2)

                                    # CheckArcReducedCost on updated apex (C:799-803)
                                    new_apex4 = np.int64(apex_arr[af4])
                                    if new_apex4 >= np.int64(0):
                                        if buf_sel[0] == np.int64(0):
                                            _check_arc_reduced_cost(
                                                nd1, nd2, new_apex4, ar2, ac2, ad2,
                                                node_outcost, node_incost,
                                                incr_pos, incr_neg, iscandidate,
                                                cand_from_A, cand_to_A, cand_viol_A,
                                                cand_ar_A, cand_ac_A, cand_ad_A,
                                                cand_n_bag, cap_ref, narc_row)
                                        else:
                                            _check_arc_reduced_cost(
                                                nd1, nd2, new_apex4, ar2, ac2, ad2,
                                                node_outcost, node_incost,
                                                incr_pos, incr_neg, iscandidate,
                                                cand_from_B, cand_to_B, cand_viol_B,
                                                cand_ar_B, cand_ac_B, cand_ad_B,
                                                cand_n_bag, cap_ref, narc_row)
                            elif grp2 != PRUNED_L and grp2 != MASKED_L:
                                _add_new_node(nd1, nd2, ad2, ar2, ac2, nflow,
                                              node_outcost, node_pred, node_group,
                                              node_next, node_prev,
                                              incr_pos, incr_neg, bkt_head, bkt_curr_ref,
                                              bkt_minind, bkt_maxind, narc_row)

                        # C:817-820: advance then check
                        nd1 = np.int64(node_next[nd1])
                        if node_level[nd1] <= startlevel:
                            break

                # ---- Augmenting cycle children scan (C:824-882) ----
                # Only when cyclecost < 0. Scans firstfromnode and firsttonode
                # subtrees, using skipthread to skip the remounted subtree.
                if cyclecost < np.int64(0):
                    # firstfromnode and firsttonode were set in the
                    # NonDegenUpdateChildren block above (lines 1208-1232).
                    # Scan up to 2 subtrees: firsttonode and firstfromnode.
                    first_scan_done_to   = firsttonode < np.int64(0)
                    first_scan_done_from = firstfromnode < np.int64(0)
                    _asc_outer = np.int64(0)
                    while True:
                        _asc_outer += np.int64(1)
                        if _asc_outer > np.int64(3):
                            return np.int64(-7777)  # aug scan outer >2 iters
                        # Pick the next subtree root (C:832-841)
                        if (not first_scan_done_to
                                and node_pred[firsttonode] == np.int32(cycleapex)):
                            nd1 = firsttonode
                            first_scan_done_to = True
                        elif (not first_scan_done_from
                                and node_pred[firstfromnode] == np.int32(cycleapex)):
                            nd1 = firstfromnode
                            first_scan_done_from = True
                        else:
                            break
                        startlevel6 = node_level[nd1]

                        # Inner descendent scan (C:845-879)
                        _asc_inner = np.int64(0)
                        while True:
                            _asc_inner += np.int64(1)
                            if _asc_inner > nconnected * np.int64(4):
                                return np.int64(-5555)  # aug scan inner cycling
                            arcnum6, upper6 = _get_arc_num_lims(node_row[nd1], ngroundarcs)
                            while arcnum6 < upper6:
                                arcnum6 += np.int64(1)
                                nd2, ar6, ac6, ad6 = _neighbor_node_grid(
                                    node_row[nd1], node_col[nd1],
                                    arcnum6, ngroundarcs, ni, nc, ground_id)
                                af6 = ar6 * narc_row + ac6
                                grp6 = node_group[nd2]
                                if grp6 > np.int64(0):
                                    ap6 = np.int64(apex_arr[af6])
                                    if (ap6 != NULL_apex_L
                                            and (grp6 != node_group[nd1]
                                                 or node_group[nd1] == apexlistbase)):
                                        if buf_sel[0] == np.int64(0):
                                            _check_arc_reduced_cost(
                                                nd1, nd2, ap6, ar6, ac6, ad6,
                                                node_outcost, node_incost,
                                                incr_pos, incr_neg, iscandidate,
                                                cand_from_A, cand_to_A, cand_viol_A,
                                                cand_ar_A, cand_ac_A, cand_ad_A,
                                                cand_n_bag, cap_ref, narc_row)
                                        else:
                                            _check_arc_reduced_cost(
                                                nd1, nd2, ap6, ar6, ac6, ad6,
                                                node_outcost, node_incost,
                                                incr_pos, incr_neg, iscandidate,
                                                cand_from_B, cand_to_B, cand_viol_B,
                                                cand_ar_B, cand_ac_B, cand_ad_B,
                                                cand_n_bag, cap_ref, narc_row)
                                elif grp6 != PRUNED_L and grp6 != MASKED_L:
                                    _add_new_node(nd1, nd2, ad6, ar6, ac6, nflow,
                                                  node_outcost, node_pred, node_group,
                                                  node_next, node_prev,
                                                  incr_pos, incr_neg, bkt_head, bkt_curr_ref,
                                                  bkt_minind, bkt_maxind, narc_row)

                            # Advance, skip remounted subtree (C:873-879)
                            nd1 = np.int64(node_next[nd1])
                            if nd1 == to_id:
                                nd1 = skipthread
                            if node_level[nd1] <= startlevel6:
                                break

                ipivots += np.int64(1)

        # Prune periodically
        nmajor += np.int64(1)
        if nmajorprune > np.int64(0) and nmajor % nmajorprune == np.int64(0):
            npruned += _prune_tree_kernel(
                source_id, node_row, node_col, node_next, node_prev,
                node_pred, node_level, node_group, node_incost, node_outcost,
                incr_pos, incr_neg, flows, ngroundarcs, prunecostthresh,
                ni, nc, ground_id, narc_row)

    return inondegen


@njit(cache=True)
def _non_degen_update_children(
        startnode: np.int64, lastnode: np.int64, nextonpath: np.int64,
        dgroup: np.int64, ngroundarcs: np.int64,
        ni: np.int64, nc: np.int64, ground_id: np.int64, narc_row: np.int64,
        node_row: np.ndarray, node_col: np.ndarray,
        node_pred: np.ndarray, node_next: np.ndarray, node_level: np.ndarray,
        node_group: np.ndarray, node_outcost: np.ndarray, node_incost: np.ndarray,
        incr_pos: np.ndarray, incr_neg: np.ndarray,
        apex_arr: np.ndarray) -> None:
    """Mirrors NonDegenUpdateChildren() in snaphu_solver.c:2383."""
    pathgroup = node_group[lastnode]
    nd1 = startnode

    while nd1 != lastnode:
        nd2 = nextonpath
        ar2, ac2, ad2 = _get_arc_grid(
            node_row[np.int64(node_pred[nd2])], node_col[np.int64(node_pred[nd2])],
            node_row[nd2], node_col[nd2],
            ni, nc, ground_id, np.int64(node_pred[nd2]), nd2)
        af2 = ar2 * narc_row + ac2

        doutcost = (node_outcost[nd1] - node_outcost[nd2]
                    + _get_cost(incr_pos, incr_neg, af2, ad2))
        nd2_oc_new = node_outcost[nd2] + doutcost
        dincost = (node_incost[nd1] - node_incost[nd2]
                   + _get_cost(incr_pos, incr_neg, af2, -ad2))
        nd2_ic_new = node_incost[nd2] + dincost

        node_outcost[nd2] = nd2_oc_new
        node_incost[nd2]  = nd2_ic_new
        node_group[nd2]   = node_group[nd1] + dgroup

        nd1 = nd2
        arcnum_c, upper_c = _get_arc_num_lims(node_row[nd1], ngroundarcs)
        while arcnum_c < upper_c:
            arcnum_c += np.int64(1)
            nb_c, _, _, _ = _neighbor_node_grid(
                node_row[nd1], node_col[nd1],
                arcnum_c, ngroundarcs, ni, nc, ground_id)
            if np.int64(node_pred[nb_c]) == nd1 and node_group[nb_c] > np.int64(0):
                if node_group[nb_c] == pathgroup:
                    nextonpath = nb_c
                else:
                    startlevel_c = node_level[nb_c]
                    g1_c = node_group[nd1]
                    nd2_c = nb_c
                    _nduc_guard = np.int64(0)
                    while True:
                        _nduc_guard += np.int64(1)
                        if _nduc_guard > np.int64(10_000_000):
                            # cycling — corrupt state but no way to signal from here
                            return
                        node_group[nd2_c]   = g1_c
                        node_incost[nd2_c]  += dincost
                        node_outcost[nd2_c] += doutcost
                        nd2_c = np.int64(node_next[nd2_c])
                        if node_level[nd2_c] <= startlevel_c:
                            break


@njit(cache=True)
def _check_leaf_kernel(nid: np.int64,
                       node_row: np.ndarray, node_col: np.ndarray,
                       node_pred: np.ndarray, node_group: np.ndarray,
                       incr_pos: np.ndarray,
                       flows: np.ndarray,
                       ngroundarcs: np.int64, ni: np.int64, nc: np.int64,
                       ground_id: np.int64, narc_row: np.int64,
                       prunecostthresh: np.int64) -> bool:
    arcnum, upper = _get_arc_num_lims(node_row[nid], ngroundarcs)
    while arcnum < upper:
        arcnum += np.int64(1)
        nb_id, _, _, _ = _neighbor_node_grid(
            node_row[nid], node_col[nid], arcnum, ngroundarcs, ni, nc, ground_id)
        if node_group[nb_id] > np.int64(0) and nb_id != np.int64(node_pred[nid]):
            return False
    if node_pred[nid] < np.int32(0):
        return False
    pred_id = np.int64(node_pred[nid])
    ar, ac, _ = _get_arc_grid(
        node_row[pred_id], node_col[pred_id],
        node_row[nid], node_col[nid],
        ni, nc, ground_id, pred_id, nid)
    af = ar * narc_row + ac
    if flows[ar, ac] != np.int16(0):
        return False
    return np.int64(incr_pos[af]) >= prunecostthresh


@njit(cache=True)
def _prune_tree_kernel(source_id: np.int64,
                       node_row: np.ndarray, node_col: np.ndarray,
                       node_next: np.ndarray, node_prev: np.ndarray,
                       node_pred: np.ndarray, node_level: np.ndarray,
                       node_group: np.ndarray,
                       node_incost: np.ndarray, node_outcost: np.ndarray,
                       incr_pos: np.ndarray, incr_neg: np.ndarray,
                       flows: np.ndarray,
                       ngroundarcs: np.int64, prunecostthresh: np.int64,
                       ni: np.int64, nc: np.int64,
                       ground_id: np.int64, narc_row: np.int64) -> np.int64:
    """Prune leaf nodes from spanning tree. Mirrors PruneTree()."""
    npruned = np.int64(0)
    nd1 = np.int64(node_next[source_id])
    while nd1 != source_id:
        nxt = np.int64(node_next[nd1])
        if _check_leaf_kernel(nd1, node_row, node_col, node_pred, node_group,
                              incr_pos, flows, ngroundarcs, ni, nc,
                              ground_id, narc_row, prunecostthresh):
            prv = np.int64(node_prev[nd1])
            node_next[prv]  = np.int32(nxt)
            node_prev[nxt]  = np.int32(prv)
            node_group[nd1] = np.int64(-4)   # PRUNED
            npruned += np.int64(1)
        nd1 = nxt
    return npruned


# ---------------------------------------------------------------------------
# ScanRegion (Python-side, called before JIT kernel)
# ---------------------------------------------------------------------------

def _scan_region_py(start_id: int, ground_id: int,
                    node_row: np.ndarray, node_col: np.ndarray,
                    node_group: np.ndarray, node_next_buf: np.ndarray,
                    ni: int, nc: int, ngroundarcs: int,
                    groupsetting: int) -> int:
    """BFS over connected region. Returns nconnected.
    Uses node_next_buf as scratch queue storage (separate from thread next).
    """
    INBUCKET_V = -2; PRUNED_V = -4; MASKED_V = -5
    queue = [start_id]
    node_group[start_id] = INBUCKET_V
    nconnected = 0
    while queue:
        nd1 = queue.pop(0)
        nconnected += 1
        arcnum = -5 if node_row[nd1] >= 0 else -1
        upper  = -1 if node_row[nd1] >= 0 else ngroundarcs - 1
        while arcnum < upper:
            arcnum += 1
            nb_id, _, _, _ = _neighbor_node_grid_py(
                int(node_row[nd1]), int(node_col[nd1]),
                arcnum, ngroundarcs, ni, nc, ground_id)
            grp2 = int(node_group[nb_id])
            if grp2 == INBUCKET_V:
                continue
            if grp2 == PRUNED_V or grp2 == MASKED_V:
                continue
            # unmarked reachable node
            if groupsetting == MASKED_V:
                node_group[nb_id] = MASKED_V
            elif groupsetting == 0:
                node_group[nb_id] = INBUCKET_V
                queue.append(nb_id)
        if groupsetting == 0:
            # Mark as visited (we'll set to 0 after)
            pass
    # Reset INBUCKET → 0
    return nconnected


def _neighbor_node_grid_py(row: int, col: int,
                            arcnum: int, ngroundarcs: int,
                            ni: int, nc: int, ground_id: int):
    """Python-side version of _neighbor_node_grid for setup."""
    ncol = nc + 1; nrow = ni + 1
    if row < 0:
        an = arcnum
        if an < ni:
            return an * nc + 0, an, 0, 1
        elif an < 2 * ni:
            r2 = an - ni
            return r2 * nc + (nc - 1), r2, nc, -1
        elif an < 2 * ni + nc - 2:
            ac2 = an - 2 * ni + 1
            return 0 * nc + ac2, ni, ac2, 1
        else:
            ac3 = an - (2 * ni + nc - 3)
            return (ni - 1) * nc + ac3, 2 * ni, ac3, -1
    else:
        r = row; c = col
        if arcnum == -4:
            return (ground_id if c == nc - 1 else r * nc + (c + 1)), r, c + 1, 1
        elif arcnum == -3:
            return (ground_id if r == ni - 1 else (r + 1) * nc + c), nrow + r, c, 1
        elif arcnum == -2:
            return (ground_id if c == 0 else r * nc + (c - 1)), r, c, -1
        else:  # -1
            return (ground_id if r == 0 else (r - 1) * nc + c), ni + r, c, -1


# ---------------------------------------------------------------------------
# SelectSources (Python-side)
# ---------------------------------------------------------------------------

def _select_sources_py(node_row: np.ndarray, node_col: np.ndarray,
                        node_group: np.ndarray,
                        node_next: np.ndarray,
                        ground_id: int, ni: int, nc: int,
                        ngroundarcs: int, nconnnodemin: int,
                        mag: np.ndarray) -> list:
    """Returns list of (source_id, nconnected)."""
    MASKED_V = -5; INBUCKET_V = -2
    nnodes = ni * nc + 1

    def reset_groups():
        for i in range(nnodes):
            if int(node_group[i]) != MASKED_V:
                node_group[i] = 0

    def sel_conn(start_id):
        # C: start->group == MASKED → skip; start->group == ONTREE → skip
        # ONTREE is the C sentinel set by ScanRegion; here we use INBUCKET_V
        # to mark already-visited nodes (equivalent to ONTREE for source selection).
        if int(node_group[start_id]) in (MASKED_V, INBUCKET_V, -1):
            return None, 0
        nconn = _bfs_scan(start_id)
        if nconn > nconnnodemin:
            return start_id, nconn
        return None, nconn

    def _bfs_scan(start_id):
        node_group[start_id] = INBUCKET_V
        queue = [start_id]; nc2 = 0
        while queue:
            nd = queue.pop(0); nc2 += 1
            arcnum = -5 if int(node_row[nd]) >= 0 else -1
            upper  = -1 if int(node_row[nd]) >= 0 else ngroundarcs - 1
            while arcnum < upper:
                arcnum += 1
                nb, _, _, _ = _neighbor_node_grid_py(
                    int(node_row[nd]), int(node_col[nd]),
                    arcnum, ngroundarcs, ni, nc, ground_id)
                grp = int(node_group[nb])
                if grp not in (MASKED_V, INBUCKET_V, -1):
                    node_group[nb] = INBUCKET_V
                    queue.append(nb)
        return nc2

    reset_groups()
    result = []

    src, nconn = sel_conn(ground_id)
    if src is not None:
        result.append((src, nconn))

    for r in range(ni):
        for c in range(nc):
            src, nconn = sel_conn(r * nc + c)
            if src is not None:
                result.append((src, nconn))

    reset_groups()
    return result


# ---------------------------------------------------------------------------
# EvaluateTotalCost and MaxNonMaskFlow (Python helpers for outer loop)
# ---------------------------------------------------------------------------
# These mirror C's EvaluateTotalCost (snaphu_solver.c:3522) and
# MaxNonMaskFlow (snaphu_solver.c:2820) exactly.

def _evaluate_total_cost_smooth(costs_off: np.ndarray, costs_sig: np.ndarray,
                                  flows: np.ndarray, nrow: int, ncol: int,
                                  nshortcycle: int) -> int:
    """EvaluateTotalCost for SMOOTH mode (C: snaphu_solver.c:3522).

    cost(arcrow, arccol) = (|flow*nshortcycle + offset|)^2 / sigsq
    Returns total as Python int.  Arcs with sigsq==LARGESHORT contribute 0.
    """
    LARGESHORT_I = int(LARGESHORT)
    ns = int(nshortcycle)
    total = 0
    # row arcs: rows 0 .. nrow-2
    for arcrow in range(nrow - 1):
        for arccol in range(ncol):
            af = arcrow * ncol + arccol
            sig = int(costs_sig[af])
            if sig == LARGESHORT_I:
                continue
            idz1 = abs(int(flows[arcrow, arccol]) * ns + int(costs_off[af]))
            total += (idz1 * idz1) // sig
    # col arcs: rows nrow-1 .. 2*nrow-2
    for arcrow in range(nrow - 1, 2 * nrow - 1):
        for arccol in range(ncol - 1):
            af = arcrow * ncol + arccol
            sig = int(costs_sig[af])
            if sig == LARGESHORT_I:
                continue
            idz1 = abs(int(flows[arcrow, arccol]) * ns + int(costs_off[af]))
            total += (idz1 * idz1) // sig
    return total


def _evaluate_total_cost_smooth_np(costs_off: np.ndarray, costs_sig: np.ndarray,
                                     flows: np.ndarray, nrow: int, ncol: int,
                                     nshortcycle: int) -> int:
    """Vectorised version of _evaluate_total_cost_smooth. Faster for large grids."""
    ns = int(nshortcycle)
    LARGESHORT_I = int(LARGESHORT)
    # Build arc arrays for row arcs and col arcs separately
    # Row arcs: flows[0:nrow-1, 0:ncol]  → flat indices 0..(nrow-1)*ncol-1
    row_arc_flat = np.arange((nrow - 1) * ncol)
    sig_r = costs_sig[row_arc_flat].astype(np.int64)
    off_r = costs_off[row_arc_flat].astype(np.int64)
    fl_r  = flows[0:nrow-1, 0:ncol].ravel().astype(np.int64)
    mask_r = (sig_r != LARGESHORT_I)
    idz_r = np.abs(fl_r * ns + off_r)
    total = int(np.sum((idz_r * idz_r // sig_r)[mask_r]))

    # Col arcs: flows[nrow-1:2*nrow-1, 0:ncol-1] → flat indices
    col_arc_rows = np.arange(nrow - 1, 2 * nrow - 1)
    col_arc_flat = (col_arc_rows[:, None] * ncol + np.arange(ncol - 1)).ravel()
    sig_c = costs_sig[col_arc_flat].astype(np.int64)
    off_c = costs_off[col_arc_flat].astype(np.int64)
    fl_c  = flows[nrow-1:2*nrow-1, 0:ncol-1].ravel().astype(np.int64)
    mask_c = (sig_c != LARGESHORT_I)
    idz_c = np.abs(fl_c * ns + off_c)
    total += int(np.sum((idz_c * idz_c // sig_c)[mask_c]))
    return total


def _max_nonmask_flow(flows: np.ndarray, mag: np.ndarray, nrow: int, ncol: int) -> int:
    """MaxNonMaskFlow (C: snaphu_solver.c:2820).

    Ignores flow on arcs adjacent to masked (mag==0) nodes.
    Row arcs: flows[r, c] for r in 0..nrow-2; mask = mag[r,c]>0 AND mag[r+1,c]>0
    Col arcs: flows[r, c] for r in nrow-1..2*nrow-2; mask = mag[r-nrow+1,c]>0 AND mag[r-nrow+1,c+1]>0
    """
    # Row arcs
    row_flows = np.abs(flows[0:nrow-1, 0:ncol].astype(np.int32))
    row_mask  = (mag[0:nrow-1, 0:ncol] > 0) & (mag[1:nrow, 0:ncol] > 0)
    mostflow = int(row_flows[row_mask].max()) if row_mask.any() else 0

    # Col arcs: flows[nrow-1:2*nrow-1, 0:ncol-1] shape (nrow, ncol-1)
    # C: mag[row-nrow+1][col] and mag[row-nrow+1][col+1] where row in [nrow-1, 2*nrow-2]
    # → mag[0:nrow, 0:ncol-1] and mag[0:nrow, 1:ncol]
    col_flows = np.abs(flows[nrow-1:2*nrow-1, 0:ncol-1].astype(np.int32))
    col_mask  = (mag[0:nrow, 0:ncol-1] > 0) & (mag[0:nrow, 1:ncol] > 0)
    if col_mask.any():
        cf_max = int(col_flows[col_mask].max())
        if cf_max > mostflow:
            mostflow = cf_max
    return mostflow


# ---------------------------------------------------------------------------
# Top-level network_flow_optimize_numba
# ---------------------------------------------------------------------------
# This is the drop-in replacement for network_flow_optimize() in snaphu_py.py.
# It keeps the same Python-side outer loop (SetupIncrFlowCosts, SelectSources,
# SetupTreeSolveNetwork) but delegates the inner TreeSolve to @njit.

def network_flow_optimize_numba(phase: np.ndarray,
                                 costs: np.ndarray,
                                 flows: np.ndarray,
                                 params,
                                 mag: np.ndarray = None) -> np.ndarray:
    """Numba-accelerated drop-in for network_flow_optimize().

    Maintains the same interface as the scalar-object port but replaces
    _tree_solve_ts with _tree_solve_kernel (@njit SoA).

    Parameters
    ----------
    phase : (nrow, ncol) float32 — used only for sizing
    costs : structured arc cost array (smoothcostT or costT dtype)
    flows : (2*nrow-1, ncol) int16 — modified in-place
    params : SnaphuParams
    mag   : (nrow, ncol) float32 — None → all-ones
    """
    if not _NUMBA_OK:
        raise ImportError("numba is required for network_flow_optimize_numba()")

    nrow, ncol = phase.shape
    ni = nrow - 1
    nc = ncol - 1

    if mag is None:
        mag = np.ones((nrow, ncol), dtype=np.float32)
    if not np.any(mag > 0):
        return flows

    # ---- InitNetwork corner arcs (from snaphu_solver.c:2568-2576) ----
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

    # Bucket extents
    NEGBF = 1.0; POSBF = 1.0
    bkt_minind = -int(round((params.maxcost + 1) * (nrow + ncol) * NEGBF))
    bkt_maxind =  int(round((params.maxcost + 1) * (nrow + ncol) * POSBF))
    bkt_size   = bkt_maxind - bkt_minind + 1

    # ---- Build SoA node arrays ----
    nds, ground_id = _build_node_arrays(ni, nc, mag)
    nnodes = ni * nc + 1

    # ---- Flat arc arrays ----
    narc_total = (2 * nrow - 1) * ncol   # upper bound (some arcs unused for ncol arcs)
    # incrcosts
    incr_pos = np.zeros(narc_total, dtype=np.int16)
    incr_neg = np.zeros(narc_total, dtype=np.int16)

    # Unpack cost arrays depending on costmode
    costmode_int = np.int64(params.costmode)
    costs_off = costs['offset'].ravel().astype(np.int16)
    costs_sig = costs['sigsq'].ravel().astype(np.int16)
    narc_costs = len(costs_off)
    if costmode_int == np.int64(2):   # DEFO = 2
        costs_dzm = costs['dzmax'].ravel().astype(np.int16)
        costs_lay = costs['laycost'].ravel().astype(np.int16)
    else:   # SMOOTH = 3; no dzmax/laycost fields
        costs_dzm = np.zeros(narc_costs, dtype=np.int16)
        costs_lay = np.zeros(narc_costs, dtype=np.int16)

    # Pad cost arrays to narc_total if needed
    if narc_costs < narc_total:
        costs_off = np.concatenate([costs_off, np.zeros(narc_total - narc_costs, np.int16)])
        costs_sig = np.concatenate([costs_sig, np.zeros(narc_total - narc_costs, np.int16)])
        costs_dzm = np.concatenate([costs_dzm, np.zeros(narc_total - narc_costs, np.int16)])
        costs_lay = np.concatenate([costs_lay, np.zeros(narc_total - narc_costs, np.int16)])

    # apex array: -2 = NONTREEARC, -1 = NULL, ≥0 = node flat id
    apex_arr     = np.full(narc_total, -2, dtype=np.int32)
    iscandidate  = np.zeros(narc_total, dtype=np.int8)

    # Candidate arrays (pre-allocated at narc_total — safe upper bound)
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

    nshortcycle = np.int64(params.nshortcycle)

    # ---- Check mostflow (C: InitNetwork:2588) ----
    # Use MaxNonMaskFlow to exclude masked arcs (matches C)
    mostflow = _max_nonmask_flow(flows, mag, nrow, ncol)
    if mostflow * int(params.nshortcycle) > int(32000):  # LARGESHORT
        raise ValueError(
            f"mostflow={mostflow} * nshortcycle={params.nshortcycle} "
            f"= {mostflow * params.nshortcycle} > LARGESHORT=32000. "
            "Reduce maxflow or nshortcycle.")

    # ---- Initial totalcost (C: InitNetwork:2653 sets INITTOTALCOST) ----
    # C initialises totalcost = INITTOTALCOST which is then set at C:InitNetwork end
    # via EvaluateTotalCost before the loop.  We evaluate it here.
    if costmode_int == np.int64(3):   # SMOOTH
        totalcost = _evaluate_total_cost_smooth_np(
            costs_off, costs_sig, flows, nrow, ncol, int(nshortcycle))
    else:
        totalcost = 0   # DEFO: no EvaluateTotalCost in this port yet
    mintotalcost = totalcost
    oldtotalcost = totalcost

    nflow = 1
    ncycle = 0
    nflowdone = 0
    notfirstloop = False
    nnondecreasedcostiter = 0
    use_maxcyclefraction = (params.maxnflowcycles == -123)

    # ---- Main optimization loop ----
    while True:
        # SetupIncrFlowCosts
        _setup_incr_flow_costs(
            costmode_int, costs_off, costs_sig, costs_dzm, costs_lay,
            incr_pos, incr_neg, flows,
            np.int64(nflow), np.int64(nrow), np.int64(ncol), nshortcycle)

        # SelectSources (Python-side)
        sourcelist = _select_sources_py(
            nds['row'], nds['col'], nds['group'], nds['next'],
            ground_id, ni, nc, ngroundarcs, params.nconnnodemin, mag)

        # SetupTreeSolveNetwork: reset node state (vectorised — avoids 3-ms Python loop)
        VERYFAR_P = int(VERYFAR)
        MASKED_P  = int(MASKED_VAL)
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
        # Corner arcs: always iscandidate=True (C lines 2577-2585)
        ncol_a = np.int64(ncol)
        nrow_a = np.int64(nrow)
        iscandidate[(nrow_a - 1) * ncol_a + 0]         = 1
        iscandidate[(2 * nrow_a - 2) * ncol_a + 0]     = 1
        iscandidate[(nrow_a - 1) * ncol_a + (ncol_a - 2)] = 1
        iscandidate[(2 * nrow_a - 2) * ncol_a + (ncol_a - 2)] = 1

        # Reset bucket
        bkt_head[:] = -1

        n = 0
        last_nconn = 1

        for source_id_py, nconnected in sourcelist:
            last_nconn = nconnected

            _ret = int(_tree_solve_kernel(
                nds['row'], nds['col'],
                nds['next'], nds['prev'],
                nds['pred'], nds['level'],
                nds['group'], nds['incost'], nds['outcost'],
                np.int64(ground_id),
                incr_pos, incr_neg, flows,
                costmode_int,
                costs_off, costs_sig, costs_dzm, costs_lay,
                apex_arr, iscandidate,
                cf_A, ct_A, cv_A, car_A, cac_A, cad_A,
                cf_B, ct_B, cv_B, car_B, cac_B, cad_B,
                bkt_head,
                np.int64(bkt_minind), np.int64(bkt_maxind),
                np.int64(nflow), nshortcycle,
                np.int64(nconnected),
                np.int64(ni), np.int64(nc),
                np.int64(ngroundarcs),
                np.int64(source_id_py),
                float(params.maxnewnodeconst),
                np.int64(params.nmajorprune),
                np.int64(params.prunecostthresh),
            ))
            if _ret < 0:
                raise RuntimeError(
                    f"_tree_solve_kernel returned cycling sentinel {_ret} "
                    f"(nflow={nflow}, nconnected={nconnected}, region={source_id_py})"
                )
            n += _ret

        ncycle += n

        # ---- EvaluateTotalCost + nnondecreasedcostiter (C: snaphu.c:646-660) ----
        # Only update after the first full loop (notfirstloop==True)
        if notfirstloop:
            oldtotalcost = totalcost
            if costmode_int == np.int64(3):   # SMOOTH
                totalcost = _evaluate_total_cost_smooth_np(
                    costs_off, costs_sig, flows, nrow, ncol, int(nshortcycle))
            # else: DEFO EvaluateTotalCost not ported; skip anti-cycling check
            if costmode_int == np.int64(3):
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

        # MaxNonMaskFlow (C: snaphu.c:672) — excludes masked arcs
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
