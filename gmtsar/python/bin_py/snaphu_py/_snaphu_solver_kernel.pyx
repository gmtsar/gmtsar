# _snaphu_solver_kernel.pyx — Cython port of the snaphu TreeSolve hot-kernel.
#
# C reference: snaphu/src/snaphu_solver.c  (TreeSolve, AddNewNode,
#              CheckArcReducedCost, FindApex, MinOutCostNode,
#              BucketInsert, BucketRemove, NonDegenUpdateChildren,
#              PruneTree, SetupIncrFlowCosts, GetCost, ReCalcCost)
#
# Parity spec: float32-exact vs C binary on 30x30, 64x64, 256x256 real
#              ALOS_haiti patches (same tolerance as numba port).
#
# Design:
#   SoA arrays mirror the numba port (snaphu_solver_numba.py) exactly.
#   All arrays are flat 1-D typed memoryviews (int32[::1], int64[::1],
#   int16[::1], int8[::1]).  No Python objects inside cdef functions.
#   The hot inner loops (MinOutCostNode, AddNewNode, FindApex,
#   NonDegenUpdateChildren, PruneTree, the tree-grow and candidate-pivot
#   loops) are all cdef nogil — zero Python overhead on the critical path.
#
#   Bucket array: bkt_head[b] = flat node index of first node in bucket b.
#   b = abs_index - bkt_minind.  Size = bkt_maxind - bkt_minind + 1.
#
#   Candidate double-buffer: arrays A and B, each of length narc_total.
#   bag/list alternation exactly mirrors the C candidatebag/candidatelist swap.
#
# Compile flags: -O2 -march=native
#   No -ffp-contract=off needed: this extension does only integer arithmetic.
#
# Python entry point: network_flow_optimize_cy(phase, costs, flows, params, mag)
#   — drop-in replacement for network_flow_optimize_numba().
#
# C source constants (verbatim from snaphu.h — do NOT substitute equivalents):
#   LARGEINT  = 2_000_000_000
#   LARGESHORT = 32000
#   INBUCKET   = -2
#   PRUNED     = -4
#   MASKED     = -5
#   NONTREEARC = -2  (apex array sentinel for "arc not yet in tree")
#   NULL_APEX  = -1  (apex array sentinel for "arc is tree arc, apex = NULL")
#
# cython: language_level=3

cimport cython
import numpy as np
cimport numpy as np
from libc.math cimport ceil, abs as cabs, floor
from libc.stdlib cimport qsort
from libc.string cimport memset

# ---------------------------------------------------------------------------
# C-level type aliases
# ---------------------------------------------------------------------------
ctypedef np.int32_t   I32
ctypedef np.int64_t   I64
ctypedef np.int16_t   I16
ctypedef np.int8_t    I8

# ---------------------------------------------------------------------------
# Constants (verbatim from snaphu.h)
# ---------------------------------------------------------------------------
cdef I64 LARGEINT   = 2_000_000_000
cdef I64 LARGESHORT = 32000
cdef I64 INBUCKET   = -2
cdef I64 PRUNED     = -4
cdef I64 MASKED     = -5
cdef I32 NONTREEARC = -2   # apex sentinel for "not a tree arc"
cdef I32 NULL_APEX  = -1   # apex sentinel for "tree arc, apex=NULL"

# ---------------------------------------------------------------------------
# Cost kernel helpers (C-exact integer arithmetic, no fp)
# ---------------------------------------------------------------------------

@cython.boundscheck(False)
@cython.wraparound(False)
@cython.cdivision(True)
cdef void _calc_cost_smooth_incr(
        I16 offset_s, I16 sigsq_s,
        I64 flow, I64 nflow, I64 nshortcycle,
        I64 *poscost_out, I64 *negcost_out) noexcept nogil:
    """Mirrors CalcCostSmooth() + ReCalcCost() from snaphu_cost.c."""
    cdef I64 offset, sigsq, idz1, idz2pos, idz2neg
    cdef I64 cost1, poscost, negcost, nflowsq
    offset = <I64>offset_s
    sigsq  = <I64>sigsq_s
    if sigsq <= 0:
        sigsq = 1
    if sigsq == LARGESHORT:
        poscost_out[0] = 0; negcost_out[0] = 0
        return
    idz1    = flow * nshortcycle + offset
    if idz1 < 0: idz1 = -idz1
    idz2pos = (flow + nflow) * nshortcycle + offset
    if idz2pos < 0: idz2pos = -idz2pos
    idz2neg = (flow - nflow) * nshortcycle + offset
    if idz2neg < 0: idz2neg = -idz2neg
    cost1   = (idz1 * idz1) // sigsq
    poscost = (idz2pos * idz2pos) // sigsq - cost1
    negcost = (idz2neg * idz2neg) // sigsq - cost1
    nflowsq = nflow * nflow
    if poscost > 0:
        poscost = (poscost + nflowsq - 1) // nflowsq
    else:
        poscost = -((-poscost) // nflowsq)
    if negcost > 0:
        negcost = (negcost + nflowsq - 1) // nflowsq
    else:
        negcost = -((-negcost) // nflowsq)
    poscost_out[0] = poscost
    negcost_out[0] = negcost


@cython.boundscheck(False)
@cython.wraparound(False)
@cython.cdivision(True)
cdef void _calc_cost_defo_incr(
        I16 offset_s, I16 sigsq_s, I16 dzmax_s, I16 laycost_s,
        I64 flow, I64 nflow, I64 nshortcycle,
        I64 *poscost_out, I64 *negcost_out) noexcept nogil:
    """Mirrors CalcCostDefo() from snaphu_cost.c."""
    cdef I64 offset, sigsq, dzmax, laycost_v, NOCOSTSHELF_V
    cdef I64 idz1, idz2pos, idz2neg, idz1_sh, idz2pos_sh, idz2neg_sh
    cdef I64 cost1, poscost, negcost, nflowsq, layfalloffconst
    offset    = <I64>offset_s; sigsq = <I64>sigsq_s
    dzmax     = <I64>dzmax_s;  laycost_v = <I64>laycost_s
    NOCOSTSHELF_V = -32000
    if sigsq <= 0: sigsq = 1
    if sigsq == LARGESHORT:
        poscost_out[0] = 0; negcost_out[0] = 0
        return
    layfalloffconst = 2
    idz1    = flow * nshortcycle + offset
    if idz1 < 0: idz1 = -idz1
    idz2pos = (flow + nflow) * nshortcycle + offset
    if idz2pos < 0: idz2pos = -idz2pos
    idz2neg = (flow - nflow) * nshortcycle + offset
    if idz2neg < 0: idz2neg = -idz2neg
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
    if poscost > 0:
        poscost = (poscost + nflowsq - 1) // nflowsq
    else:
        poscost = -((-poscost) // nflowsq)
    if negcost > 0:
        negcost = (negcost + nflowsq - 1) // nflowsq
    else:
        negcost = -((-negcost) // nflowsq)
    poscost_out[0] = poscost
    negcost_out[0] = negcost


@cython.boundscheck(False)
@cython.wraparound(False)
@cython.cdivision(True)
cdef void _recalc_cost_cy(
        I64 costmode,
        I16[::1] costs_off, I16[::1] costs_sig,
        I16[::1] costs_dzm, I16[::1] costs_lay,
        I16[::1] incr_pos, I16[::1] incr_neg,
        I64 arc_flat, I64 flow, I64 nflow, I64 nshortcycle) noexcept nogil:
    """Recompute incrcosts for one arc, clip to ±LARGESHORT. In-place."""
    cdef I64 pc, nc_
    if costmode == 3:   # SMOOTH
        _calc_cost_smooth_incr(costs_off[arc_flat], costs_sig[arc_flat],
                               flow, nflow, nshortcycle, &pc, &nc_)
    else:   # DEFO
        _calc_cost_defo_incr(costs_off[arc_flat], costs_sig[arc_flat],
                              costs_dzm[arc_flat], costs_lay[arc_flat],
                              flow, nflow, nshortcycle, &pc, &nc_)
    if pc > LARGESHORT:  pc = LARGESHORT
    elif pc < -LARGESHORT: pc = -LARGESHORT
    if nc_ > LARGESHORT:  nc_ = LARGESHORT
    elif nc_ < -LARGESHORT: nc_ = -LARGESHORT
    incr_pos[arc_flat] = <I16>pc
    incr_neg[arc_flat] = <I16>nc_


@cython.boundscheck(False)
@cython.wraparound(False)
cdef I64 _get_cost_cy(I16[::1] incr_pos, I16[::1] incr_neg,
                      I64 arc_flat, I64 arcdir) noexcept nogil:
    if arcdir > 0:
        return <I64>incr_pos[arc_flat]
    else:
        return <I64>incr_neg[arc_flat]


# ---------------------------------------------------------------------------
# Arc geometry helpers
# ---------------------------------------------------------------------------

@cython.boundscheck(False)
@cython.wraparound(False)
cdef void _get_arc_num_lims_cy(I32 fromrow, I64 ngroundarcs,
                                I64 *arcnum_out, I64 *upperarcnum_out) noexcept nogil:
    """Mirrors GetArcNumLims()."""
    if fromrow < 0:
        arcnum_out[0]      = -1
        upperarcnum_out[0] = ngroundarcs - 1
    else:
        arcnum_out[0]      = -5
        upperarcnum_out[0] = -1


@cython.boundscheck(False)
@cython.wraparound(False)
cdef void _neighbor_node_grid_cy(
        I32 row, I32 col, I64 arcnum, I64 ngroundarcs,
        I64 ni, I64 nc, I64 ground_id,
        I64 *nb_id_out, I64 *arcrow_out, I64 *arccol_out, I64 *arcdir_out
) noexcept nogil:
    """Mirrors NeighborNodeGrid(). Returns (nb_id, arcrow, arccol, arcdir)."""
    cdef I64 r, c, an, r2, ac2, ac3, nrow
    nrow = ni + 1
    if row < 0:
        an = arcnum
        if an < ni:
            arcrow_out[0]  = an
            arccol_out[0]  = 0
            arcdir_out[0]  = 1
            nb_id_out[0]   = an * nc
        elif an < 2 * ni:
            r2 = an - ni
            arcrow_out[0]  = r2
            arccol_out[0]  = nc
            arcdir_out[0]  = -1
            nb_id_out[0]   = r2 * nc + (nc - 1)
        elif an < 2 * ni + nc - 2:
            ac2 = an - 2 * ni + 1
            arcrow_out[0]  = ni
            arccol_out[0]  = ac2
            arcdir_out[0]  = 1
            nb_id_out[0]   = ac2
        else:
            ac3 = an - (2 * ni + nc - 3)
            arcrow_out[0]  = 2 * ni
            arccol_out[0]  = ac3
            arcdir_out[0]  = -1
            nb_id_out[0]   = (ni - 1) * nc + ac3
        return
    r = <I64>row; c = <I64>col
    if arcnum == -4:   # right
        arcrow_out[0] = r; arccol_out[0] = c + 1; arcdir_out[0] = 1
        nb_id_out[0] = ground_id if (c == nc - 1) else (r * nc + c + 1)
    elif arcnum == -3:   # down
        arcrow_out[0] = nrow + r; arccol_out[0] = c; arcdir_out[0] = 1
        nb_id_out[0] = ground_id if (r == ni - 1) else ((r + 1) * nc + c)
    elif arcnum == -2:   # left
        arcrow_out[0] = r; arccol_out[0] = c; arcdir_out[0] = -1
        nb_id_out[0] = ground_id if (c == 0) else (r * nc + c - 1)
    else:   # -1: up
        arcrow_out[0] = ni + r; arccol_out[0] = c; arcdir_out[0] = -1
        nb_id_out[0] = ground_id if (r == 0) else ((r - 1) * nc + c)


@cython.boundscheck(False)
@cython.wraparound(False)
cdef void _get_arc_grid_cy(
        I32 from_row, I32 from_col, I32 to_row, I32 to_col,
        I64 ni, I64 nc, I64 ground_id, I64 from_id, I64 to_id,
        I64 *arcrow_out, I64 *arccol_out, I64 *arcdir_out) noexcept nogil:
    """Mirrors GetArcGrid()."""
    cdef I64 fr, fc, tr, tc, nrow
    fr = <I64>from_row; fc = <I64>from_col
    tr = <I64>to_row;   tc = <I64>to_col
    nrow = ni + 1
    if fr == tr:
        if fc == tc - 1:
            arcrow_out[0] = fr; arccol_out[0] = tc; arcdir_out[0] = 1
        else:
            arcrow_out[0] = fr; arccol_out[0] = fc; arcdir_out[0] = -1
    elif fr == tr - 1:
        arcrow_out[0] = tr + nrow - 1; arccol_out[0] = fc; arcdir_out[0] = 1
    elif fr == tr + 1:
        arcrow_out[0] = fr + nrow - 1; arccol_out[0] = fc; arcdir_out[0] = -1
    elif from_id == ground_id:
        if fc < nc - 1 and tc == fc + 1:
            arcrow_out[0] = tr; arccol_out[0] = tc; arcdir_out[0] = -1
        elif fc > 0 and tc == fc - 1:
            arcrow_out[0] = tr; arccol_out[0] = tc; arcdir_out[0] = 1
        elif tr < ni - 1 and tr == fr + 1:
            arcrow_out[0] = tr + 1 + nrow - 1; arccol_out[0] = tc; arcdir_out[0] = -1
        else:
            arcrow_out[0] = tr + nrow - 1; arccol_out[0] = tc; arcdir_out[0] = 1
    elif to_id == ground_id:
        if fc < nc - 1 and tc == fc + 1:
            arcrow_out[0] = fr; arccol_out[0] = fc + 1; arcdir_out[0] = 1
        elif fc > 0 and tc == fc - 1:
            arcrow_out[0] = fr; arccol_out[0] = fc; arcdir_out[0] = -1
        elif fr < ni - 1 and fr + 1 == tr:
            arcrow_out[0] = fr + 1 + nrow - 1; arccol_out[0] = fc; arcdir_out[0] = 1
        else:
            arcrow_out[0] = fr + nrow - 1; arccol_out[0] = fc; arcdir_out[0] = -1
    elif fc == 0:
        arcrow_out[0] = fr; arccol_out[0] = 0; arcdir_out[0] = -1
    elif fc == nc - 1:
        arcrow_out[0] = fr; arccol_out[0] = nc; arcdir_out[0] = 1
    elif fr == 0:
        arcrow_out[0] = nrow - 1; arccol_out[0] = fc; arcdir_out[0] = -1
    elif fr == ni - 1:
        arcrow_out[0] = 2 * (nrow - 1); arccol_out[0] = fc; arcdir_out[0] = 1
    elif tc == 0:
        arcrow_out[0] = tr; arccol_out[0] = 0; arcdir_out[0] = 1
    elif tc == nc - 1:
        arcrow_out[0] = tr; arccol_out[0] = nc; arcdir_out[0] = -1
    elif tr == 0:
        arcrow_out[0] = nrow - 1; arccol_out[0] = tc; arcdir_out[0] = 1
    else:
        arcrow_out[0] = 2 * (nrow - 1); arccol_out[0] = tc; arcdir_out[0] = -1


# ---------------------------------------------------------------------------
# Bucket operations
# ---------------------------------------------------------------------------

@cython.boundscheck(False)
@cython.wraparound(False)
cdef void _bkt_insert_cy(
        I32[::1] node_next, I32[::1] node_prev, I64[::1] node_group,
        I32[::1] bkt_head,
        I64 nid, I64 ind, I64 bkt_minind) noexcept nogil:
    """BucketInsert: prepend node nid into bucket at absolute index ind."""
    cdef I64 b, old_head
    b = ind - bkt_minind
    old_head = <I64>bkt_head[b]
    node_next[nid] = <I32>old_head
    node_prev[nid] = -1
    if old_head >= 0:
        node_prev[old_head] = <I32>nid
    bkt_head[b] = <I32>nid
    node_group[nid] = INBUCKET


@cython.boundscheck(False)
@cython.wraparound(False)
cdef void _bkt_remove_cy(
        I32[::1] node_next, I32[::1] node_prev,
        I32[::1] bkt_head,
        I64 nid, I64 ind, I64 bkt_minind) noexcept nogil:
    """BucketRemove: remove node nid from bucket at absolute index ind."""
    cdef I64 b, prv, nxt
    b = ind - bkt_minind
    prv = <I64>node_prev[nid]
    nxt = <I64>node_next[nid]
    if prv >= 0:
        node_next[prv] = <I32>nxt
    else:
        bkt_head[b] = <I32>nxt
    if nxt >= 0:
        node_prev[nxt] = <I32>prv
    node_next[nid] = -1
    node_prev[nid] = -1


@cython.boundscheck(False)
@cython.wraparound(False)
cdef I64 _min_out_cost_node_cy(
        I32[::1] node_next, I32[::1] node_prev, I64[::1] node_group,
        I32[::1] bkt_head,
        I64 *bkt_curr_ptr,
        I64 bkt_maxind, I64 bkt_minind) noexcept nogil:
    """MinOutCostNode: pop cheapest node from bucket priority queue.

    Returns node_id, or -1 if exhausted.  Updates *bkt_curr_ptr in place.
    The curr pointer scans upward monotonically (Dijkstra-style amortized O(1)).
    """
    cdef I64 curr, b, head
    curr = bkt_curr_ptr[0]
    while curr <= bkt_maxind:
        b = curr - bkt_minind
        head = <I64>bkt_head[b]
        if head >= 0:
            _bkt_remove_cy(node_next, node_prev, bkt_head, head, curr, bkt_minind)
            node_group[head] = 1   # mark on-tree
            bkt_curr_ptr[0] = curr
            return head
        curr += 1
    bkt_curr_ptr[0] = curr
    return -1


# ---------------------------------------------------------------------------
# AddNewNode
# ---------------------------------------------------------------------------

@cython.boundscheck(False)
@cython.wraparound(False)
cdef void _add_new_node_cy(
        I64 from_id, I64 to_id, I64 arcdir, I64 arcrow, I64 arccol,
        I64 nflow,
        I64[::1] node_outcost, I32[::1] node_pred, I64[::1] node_group,
        I32[::1] node_next, I32[::1] node_prev,
        I16[::1] incr_pos, I16[::1] incr_neg,
        I32[::1] bkt_head,
        I64 *bkt_curr_ptr,
        I64 bkt_minind, I64 bkt_maxind,
        I64 narc_row) noexcept nogil:
    """Mirrors AddNewNode() in snaphu_solver.c:986."""
    cdef I64 arc_flat, newoutcost, oc_to, clamped
    arc_flat = arcrow * narc_row + arccol
    newoutcost = node_outcost[from_id] + _get_cost_cy(incr_pos, incr_neg, arc_flat, arcdir)
    oc_to = node_outcost[to_id]
    if newoutcost < oc_to or <I64>node_pred[to_id] == from_id:
        if node_group[to_id] == INBUCKET:
            if oc_to < bkt_maxind:
                if oc_to > bkt_minind:
                    _bkt_remove_cy(node_next, node_prev, bkt_head, to_id, oc_to, bkt_minind)
                else:
                    _bkt_remove_cy(node_next, node_prev, bkt_head, to_id, bkt_minind, bkt_minind)
            else:
                _bkt_remove_cy(node_next, node_prev, bkt_head, to_id, bkt_maxind, bkt_minind)
        node_outcost[to_id] = newoutcost
        node_pred[to_id] = <I32>from_id
        if newoutcost < bkt_maxind:
            clamped = newoutcost if newoutcost > bkt_minind else bkt_minind
        else:
            clamped = bkt_maxind
        _bkt_insert_cy(node_next, node_prev, node_group, bkt_head, to_id, clamped, bkt_minind)
        if clamped < bkt_curr_ptr[0]:
            bkt_curr_ptr[0] = clamped


# ---------------------------------------------------------------------------
# FindApex
# ---------------------------------------------------------------------------

@cython.boundscheck(False)
@cython.wraparound(False)
cdef I64 _find_apex_cy(
        I64 from_id, I64 to_id,
        I64[::1] node_level, I32[::1] node_pred) noexcept nogil:
    """FindApex: deepest common ancestor. Returns -11111 on cycling guard."""
    cdef I64 f, t, guard
    f = from_id; t = to_id; guard = 0
    while node_level[f] > node_level[t]:
        guard += 1
        if guard > 200000: return -11111
        f = <I64>node_pred[f]
    while node_level[t] > node_level[f]:
        guard += 1
        if guard > 200000: return -11111
        t = <I64>node_pred[t]
    while f != t:
        guard += 1
        if guard > 200000: return -11111
        f = <I64>node_pred[f]
        t = <I64>node_pred[t]
    return f


# ---------------------------------------------------------------------------
# CheckArcReducedCost
# ---------------------------------------------------------------------------

@cython.boundscheck(False)
@cython.wraparound(False)
cdef void _check_arc_reduced_cost_cy(
        I64 from_id, I64 to_id, I64 apex_id,
        I64 arcrow, I64 arccol, I64 arcdir,
        I64[::1] node_outcost, I64[::1] node_incost,
        I16[::1] incr_pos, I16[::1] incr_neg,
        I8[::1] iscandidate,
        I32[::1] cand_from, I32[::1] cand_to,
        I64[::1] cand_violation,
        I32[::1] cand_arcrow, I32[::1] cand_arccol,
        I8[::1]  cand_arcdir,
        I64 *cand_n_ptr, I64 cand_cap,
        I64 narc_row) noexcept nogil:
    """Mirrors CheckArcReducedCost(). Appends to candidate arrays."""
    cdef I64 arc_flat, apexcost, fwd, rev, violation
    cdef I64 fr_used, to_used, ad_used, n
    arc_flat = arcrow * narc_row + arccol
    if iscandidate[arc_flat]:
        return
    if apex_id == -1 or apex_id == -2:
        return
    apexcost = node_outcost[apex_id] + node_incost[apex_id]
    fwd = _get_cost_cy(incr_pos, incr_neg, arc_flat, arcdir)
    violation = fwd + node_outcost[from_id] + node_incost[to_id] - apexcost
    fr_used = from_id; to_used = to_id; ad_used = arcdir
    if violation < 0:
        ad_used = arcdir * 2
    else:
        rev = _get_cost_cy(incr_pos, incr_neg, arc_flat, -arcdir)
        violation = rev + node_outcost[to_id] + node_incost[from_id] - apexcost
        if violation < 0:
            ad_used = arcdir * (-2)
            fr_used = to_id; to_used = from_id
        else:
            violation = fwd + node_outcost[from_id] - node_outcost[to_id]
            if violation >= 0:
                violation = rev + node_outcost[to_id] - node_outcost[from_id]
                if violation < 0:
                    ad_used = -arcdir
                    fr_used = to_id; to_used = from_id
                else:
                    return
    if violation >= 0:
        return
    n = cand_n_ptr[0]
    if n < cand_cap:
        cand_from[n]      = <I32>fr_used
        cand_to[n]        = <I32>to_used
        cand_violation[n] = violation
        cand_arcrow[n]    = <I32>arcrow
        cand_arccol[n]    = <I32>arccol
        cand_arcdir[n]    = <I8>ad_used
        cand_n_ptr[0]     = n + 1
        iscandidate[arc_flat] = 1


# ---------------------------------------------------------------------------
# SetupIncrFlowCosts (Python-callable)
# ---------------------------------------------------------------------------

@cython.boundscheck(False)
@cython.wraparound(False)
@cython.cdivision(True)
def setup_incr_flow_costs_cy(
        I64 costmode,
        np.ndarray[I16, ndim=1] costs_off,
        np.ndarray[I16, ndim=1] costs_sig,
        np.ndarray[I16, ndim=1] costs_dzm,
        np.ndarray[I16, ndim=1] costs_lay,
        np.ndarray[I16, ndim=1] incr_pos,
        np.ndarray[I16, ndim=1] incr_neg,
        np.ndarray[I16, ndim=2] flows,
        I64 nflow, I64 nrow, I64 ncol, I64 nshortcycle):
    """SetupIncrFlowCosts for all arcs (Python entry point)."""
    cdef I64 arcrow, arccol, arc_flat, maxcol, fl
    cdef I16[::1] c_off = costs_off
    cdef I16[::1] c_sig = costs_sig
    cdef I16[::1] c_dzm = costs_dzm
    cdef I16[::1] c_lay = costs_lay
    cdef I16[::1] ip    = incr_pos
    cdef I16[::1] in_   = incr_neg
    cdef I16[:, ::1] fl_view = flows
    for arcrow in range(2 * nrow - 1):
        maxcol = ncol if arcrow < nrow - 1 else ncol - 1
        for arccol in range(maxcol):
            arc_flat = arcrow * ncol + arccol
            fl = fl_view[arcrow, arccol]
            _recalc_cost_cy(costmode, c_off, c_sig, c_dzm, c_lay,
                             ip, in_, arc_flat, <I64>fl, nflow, nshortcycle)


# ---------------------------------------------------------------------------
# NonDegenUpdateChildren
# ---------------------------------------------------------------------------

@cython.boundscheck(False)
@cython.wraparound(False)
cdef void _non_degen_update_children_cy(
        I64 startnode, I64 lastnode, I64 nextonpath,
        I64 dgroup, I64 ngroundarcs,
        I64 ni, I64 nc, I64 ground_id, I64 narc_row,
        I32[::1] node_row, I32[::1] node_col,
        I32[::1] node_pred, I32[::1] node_next,
        I64[::1] node_level, I64[::1] node_group,
        I64[::1] node_outcost, I64[::1] node_incost,
        I16[::1] incr_pos, I16[::1] incr_neg,
        I32[::1] apex_arr) noexcept nogil:
    """Mirrors NonDegenUpdateChildren() in snaphu_solver.c:2383."""
    cdef I64 nd1, nd2, ar2, ac2, ad2, af2, doutcost, dincost
    cdef I64 nd2_oc_new, nd2_ic_new, pathgroup, g1_c, startlevel_c
    cdef I64 nd2_c, arcnum_c, upper_c, nb_c
    cdef I64 _nduc_guard
    pathgroup = node_group[lastnode]
    nd1 = startnode
    while nd1 != lastnode:
        nd2 = nextonpath
        _get_arc_grid_cy(node_row[<I64>node_pred[nd2]], node_col[<I64>node_pred[nd2]],
                         node_row[nd2], node_col[nd2],
                         ni, nc, ground_id, <I64>node_pred[nd2], nd2,
                         &ar2, &ac2, &ad2)
        af2 = ar2 * narc_row + ac2
        doutcost = (node_outcost[nd1] - node_outcost[nd2]
                    + _get_cost_cy(incr_pos, incr_neg, af2, ad2))
        nd2_oc_new = node_outcost[nd2] + doutcost
        dincost  = (node_incost[nd1] - node_incost[nd2]
                    + _get_cost_cy(incr_pos, incr_neg, af2, -ad2))
        nd2_ic_new = node_incost[nd2] + dincost
        node_outcost[nd2] = nd2_oc_new
        node_incost[nd2]  = nd2_ic_new
        node_group[nd2]   = node_group[nd1] + dgroup
        nd1 = nd2
        _get_arc_num_lims_cy(node_row[nd1], ngroundarcs, &arcnum_c, &upper_c)
        while arcnum_c < upper_c:
            arcnum_c += 1
            _neighbor_node_grid_cy(node_row[nd1], node_col[nd1],
                                   arcnum_c, ngroundarcs, ni, nc, ground_id,
                                   &nb_c, &ar2, &ac2, &ad2)
            if <I64>node_pred[nb_c] == nd1 and node_group[nb_c] > 0:
                if node_group[nb_c] == pathgroup:
                    nextonpath = nb_c
                else:
                    startlevel_c = node_level[nb_c]
                    g1_c   = node_group[nd1]
                    nd2_c  = nb_c
                    _nduc_guard = 0
                    while True:
                        _nduc_guard += 1
                        if _nduc_guard > 10000000:
                            return
                        node_group[nd2_c]   = g1_c
                        node_incost[nd2_c]  += dincost
                        node_outcost[nd2_c] += doutcost
                        nd2_c = <I64>node_next[nd2_c]
                        if node_level[nd2_c] <= startlevel_c:
                            break


# ---------------------------------------------------------------------------
# _check_leaf_kernel_cy and PruneTree
# ---------------------------------------------------------------------------

@cython.boundscheck(False)
@cython.wraparound(False)
cdef bint _check_leaf_cy(
        I64 nid,
        I32[::1] node_row, I32[::1] node_col,
        I32[::1] node_pred, I64[::1] node_group,
        I16[::1] incr_pos, I16[::1] flows_flat,
        I64 ngroundarcs, I64 ni, I64 nc, I64 ground_id, I64 narc_row,
        I64 prunecostthresh) noexcept nogil:
    cdef I64 arcnum, upper, nb_id, ar, ac, ad, pred_id, af
    _get_arc_num_lims_cy(node_row[nid], ngroundarcs, &arcnum, &upper)
    while arcnum < upper:
        arcnum += 1
        _neighbor_node_grid_cy(node_row[nid], node_col[nid],
                               arcnum, ngroundarcs, ni, nc, ground_id,
                               &nb_id, &ar, &ac, &ad)
        if node_group[nb_id] > 0 and nb_id != <I64>node_pred[nid]:
            return False
    if node_pred[nid] < 0:
        return False
    pred_id = <I64>node_pred[nid]
    _get_arc_grid_cy(node_row[pred_id], node_col[pred_id],
                     node_row[nid], node_col[nid],
                     ni, nc, ground_id, pred_id, nid,
                     &ar, &ac, &ad)
    af = ar * narc_row + ac
    if flows_flat[af] != 0:
        return False
    return <I64>incr_pos[af] >= prunecostthresh


@cython.boundscheck(False)
@cython.wraparound(False)
cdef I64 _prune_tree_cy(
        I64 source_id,
        I32[::1] node_row, I32[::1] node_col,
        I32[::1] node_next, I32[::1] node_prev,
        I32[::1] node_pred, I64[::1] node_level,
        I64[::1] node_group, I64[::1] node_incost, I64[::1] node_outcost,
        I16[::1] incr_pos, I16[::1] incr_neg, I16[::1] flows_flat,
        I64 ngroundarcs, I64 prunecostthresh,
        I64 ni, I64 nc, I64 ground_id, I64 narc_row) noexcept nogil:
    """Prune leaf nodes from spanning tree. Mirrors PruneTree()."""
    cdef I64 nd1, nxt, prv, npruned
    npruned = 0
    nd1 = <I64>node_next[source_id]
    while nd1 != source_id:
        nxt = <I64>node_next[nd1]
        if _check_leaf_cy(nd1, node_row, node_col, node_pred, node_group,
                          incr_pos, flows_flat, ngroundarcs, ni, nc,
                          ground_id, narc_row, prunecostthresh):
            prv = <I64>node_prev[nd1]
            node_next[prv]  = <I32>nxt
            node_prev[nxt]  = <I32>prv
            node_group[nd1] = PRUNED
            npruned += 1
        nd1 = nxt
    return npruned


# ---------------------------------------------------------------------------
# Insertion-sort for candidate list (mirrors C's qsort(CandidateCompare))
# ---------------------------------------------------------------------------

@cython.boundscheck(False)
@cython.wraparound(False)
cdef void _insertion_sort_candidates_cy(
        I32[::1] lf, I32[::1] lt, I64[::1] lv,
        I32[::1] la_r, I32[::1] la_c, I8[::1] la_d,
        I64 nL) noexcept nogil:
    """Sort candidate list: augmenting arcs (|arcdir|>1) first, then by violation."""
    cdef I64 i, j, kf, kt, kv, kr, kc, key_aug, j_aug
    cdef I8 kd, jd
    cdef bint j_big
    for i in range(1, nL):
        kf = lf[i]; kt = lt[i]; kv = lv[i]
        kr = la_r[i]; kc = la_c[i]; kd = la_d[i]
        key_aug = 1 if (kd > 1 or kd < -1) else 0
        j = i - 1
        while j >= 0:
            jd = la_d[j]
            j_aug = 1 if (jd > 1 or jd < -1) else 0
            j_big = (j_aug < key_aug) or (j_aug == key_aug and lv[j] > kv)
            if not j_big:
                break
            lf[j+1] = lf[j]; lt[j+1] = lt[j]; lv[j+1] = lv[j]
            la_r[j+1] = la_r[j]; la_c[j+1] = la_c[j]; la_d[j+1] = la_d[j]
            j -= 1
        lf[j+1] = <I32>kf; lt[j+1] = <I32>kt; lv[j+1] = kv
        la_r[j+1] = <I32>kr; la_c[j+1] = <I32>kc; la_d[j+1] = kd


# ---------------------------------------------------------------------------
# The core TreeSolve kernel (Python-callable)
# ---------------------------------------------------------------------------

@cython.boundscheck(False)
@cython.wraparound(False)
@cython.cdivision(True)
def tree_solve_kernel_cy(
        # node SoA — all 1-D
        np.ndarray[I32, ndim=1] node_row,
        np.ndarray[I32, ndim=1] node_col,
        np.ndarray[I32, ndim=1] node_next,
        np.ndarray[I32, ndim=1] node_prev,
        np.ndarray[I32, ndim=1] node_pred,
        np.ndarray[I64, ndim=1] node_level,
        np.ndarray[I64, ndim=1] node_group,
        np.ndarray[I64, ndim=1] node_incost,
        np.ndarray[I64, ndim=1] node_outcost,
        I64 ground_id,
        # arc arrays
        np.ndarray[I16, ndim=1] incr_pos,
        np.ndarray[I16, ndim=1] incr_neg,
        np.ndarray[I16, ndim=2] flows,   # (2*nrow-1, ncol) int16
        # cost arrays
        I64 costmode,
        np.ndarray[I16, ndim=1] costs_off,
        np.ndarray[I16, ndim=1] costs_sig,
        np.ndarray[I16, ndim=1] costs_dzm,
        np.ndarray[I16, ndim=1] costs_lay,
        # apex / iscandidate
        np.ndarray[I32, ndim=1] apex_arr,
        np.ndarray[I8, ndim=1] iscandidate,
        # candidate double-buffer (A and B)
        np.ndarray[I32, ndim=1] cand_from_A,
        np.ndarray[I32, ndim=1] cand_to_A,
        np.ndarray[I64, ndim=1] cand_viol_A,
        np.ndarray[I32, ndim=1] cand_ar_A,
        np.ndarray[I32, ndim=1] cand_ac_A,
        np.ndarray[I8, ndim=1] cand_ad_A,
        np.ndarray[I32, ndim=1] cand_from_B,
        np.ndarray[I32, ndim=1] cand_to_B,
        np.ndarray[I64, ndim=1] cand_viol_B,
        np.ndarray[I32, ndim=1] cand_ar_B,
        np.ndarray[I32, ndim=1] cand_ac_B,
        np.ndarray[I8, ndim=1] cand_ad_B,
        # bucket
        np.ndarray[I32, ndim=1] bkt_head,
        I64 bkt_minind, I64 bkt_maxind,
        # scalar params
        I64 nflow, I64 nshortcycle,
        I64 nconnected,
        I64 ni, I64 nc,
        I64 ngroundarcs,
        I64 source_id,
        double maxnewnodeconst,
        I64 nmajorprune, I64 prunecostthresh,
):
    """Core TreeSolve kernel — Python entry point calling cdef nogil implementation."""
    # Build typed memoryviews (zero-copy)
    cdef I32[::1] v_node_row   = node_row
    cdef I32[::1] v_node_col   = node_col
    cdef I32[::1] v_node_next  = node_next
    cdef I32[::1] v_node_prev  = node_prev
    cdef I32[::1] v_node_pred  = node_pred
    cdef I64[::1] v_node_level = node_level
    cdef I64[::1] v_node_group = node_group
    cdef I64[::1] v_node_incost  = node_incost
    cdef I64[::1] v_node_outcost = node_outcost
    cdef I16[::1] v_incr_pos   = incr_pos
    cdef I16[::1] v_incr_neg   = incr_neg
    cdef I16[:, ::1] v_flows   = flows
    cdef I16[::1] v_costs_off  = costs_off
    cdef I16[::1] v_costs_sig  = costs_sig
    cdef I16[::1] v_costs_dzm  = costs_dzm
    cdef I16[::1] v_costs_lay  = costs_lay
    cdef I32[::1] v_apex_arr   = apex_arr
    cdef I8[::1]  v_iscandidate = iscandidate
    cdef I32[::1] v_cf_A = cand_from_A, v_ct_A = cand_to_A
    cdef I64[::1] v_cv_A = cand_viol_A
    cdef I32[::1] v_car_A = cand_ar_A, v_cac_A = cand_ac_A
    cdef I8[::1]  v_cad_A = cand_ad_A
    cdef I32[::1] v_cf_B = cand_from_B, v_ct_B = cand_to_B
    cdef I64[::1] v_cv_B = cand_viol_B
    cdef I32[::1] v_car_B = cand_ar_B, v_cac_B = cand_ac_B
    cdef I8[::1]  v_cad_B = cand_ad_B
    cdef I32[::1] v_bkt_head = bkt_head

    # Flat flows view (for _check_leaf — needs flat indexing of flows)
    # flows is 2D (2*nrow-1, ncol), we view it as 1D for flat indexing
    cdef I16[::1] v_flows_flat = flows.ravel()

    return _tree_solve_kernel_cy(
        v_node_row, v_node_col, v_node_next, v_node_prev, v_node_pred,
        v_node_level, v_node_group, v_node_incost, v_node_outcost,
        ground_id,
        v_incr_pos, v_incr_neg, v_flows, v_flows_flat,
        costmode,
        v_costs_off, v_costs_sig, v_costs_dzm, v_costs_lay,
        v_apex_arr, v_iscandidate,
        v_cf_A, v_ct_A, v_cv_A, v_car_A, v_cac_A, v_cad_A,
        v_cf_B, v_ct_B, v_cv_B, v_car_B, v_cac_B, v_cad_B,
        v_bkt_head,
        bkt_minind, bkt_maxind,
        nflow, nshortcycle, nconnected, ni, nc, ngroundarcs,
        source_id, maxnewnodeconst, nmajorprune, prunecostthresh,
    )


@cython.boundscheck(False)
@cython.wraparound(False)
@cython.cdivision(True)
cdef I64 _tree_solve_kernel_cy(
        # node SoA
        I32[::1] node_row, I32[::1] node_col,
        I32[::1] node_next, I32[::1] node_prev,
        I32[::1] node_pred,
        I64[::1] node_level, I64[::1] node_group,
        I64[::1] node_incost, I64[::1] node_outcost,
        I64 ground_id,
        # arc arrays
        I16[::1] incr_pos, I16[::1] incr_neg,
        I16[:, ::1] flows,          # 2D for flows[arcrow, arccol]
        I16[::1] flows_flat,        # flat view for _check_leaf
        # cost arrays
        I64 costmode,
        I16[::1] costs_off, I16[::1] costs_sig,
        I16[::1] costs_dzm, I16[::1] costs_lay,
        # apex / iscandidate
        I32[::1] apex_arr, I8[::1] iscandidate,
        # candidate double-buffer
        I32[::1] cf_A, I32[::1] ct_A, I64[::1] cv_A,
        I32[::1] car_A, I32[::1] cac_A, I8[::1] cad_A,
        I32[::1] cf_B, I32[::1] ct_B, I64[::1] cv_B,
        I32[::1] car_B, I32[::1] cac_B, I8[::1] cad_B,
        # bucket
        I32[::1] bkt_head,
        I64 bkt_minind, I64 bkt_maxind,
        # params
        I64 nflow, I64 nshortcycle,
        I64 nconnected, I64 ni, I64 nc,
        I64 ngroundarcs, I64 source_id,
        double maxnewnodeconst,
        I64 nmajorprune, I64 prunecostthresh,
) noexcept:
    """Full TreeSolve logic — Cython C-level, all typed locals."""

    cdef I64 ncol, narc_row, cand_cap
    cdef I64 bkt_curr
    cdef I64 sid, arcnum, upperarcnum
    cdef I64 to_id, from_id, to_tmp, arcrow, arccol, arcdir, arc_flat
    cdef I64 groupcounter, ipivots, inondegen, treesize, nmajor
    cdef I64 maxnewnodes, nnewnodes, npruned
    cdef I64 cand_n_bag, cand_n_lst, buf_sel
    cdef I64 nL, i_sort, i_nd, i_cand, ad_val
    cdef I64 outcostto, apex_id, apex_sum, cyclecost, violation
    cdef I64 leavingchild, leavingparent, cycleapex
    cdef I64 fromgroup, fromside, firstfromnode, firsttonode
    cdef I64 node1, node2, mntpt, oldmntpt, root, skipthread, nd1, nd2
    cdef I64 arcrow1, arccol1, arcdir1, arcrow2, arccol2, arcdir2
    cdef I64 dlevel, doutcost, dincost, startlevel
    cdef I64 apexlistbase, apexlistlen
    cdef I64 prv_root, nxt_nd1, nxt_mnt
    cdef I64 ar_en, ac_en, ar_lv, ac_lv
    cdef I64 grp_nb, grp2
    cdef I64 _aug_iter, _remount_guard, _thr1_guard, _thr2_guard
    cdef I64 _asc_outer, _asc_inner, _cand_iter_guard, _cand_max_iter
    cdef I64 arcnum2, upperarcnum2, arcrow_n, arccol_n, arcdir_n, arc_flat_n
    cdef I64 arcnum3, upper3, tmpnd, ar3, ac3, ad3, af3
    cdef I64 arcnum4, upper4, ar2, ac2, ad2, af4, ap2, idx_al4, ap6
    cdef I64 arcnum6, upper6, ar6, ac6, ad6, af6, grp6
    cdef I64 new_apex4, tmpnd2, g_guard
    cdef I64 g1, idx_al
    cdef I64 first_scan_done_to, first_scan_done_from
    # Apexlist as a fixed-size stack array.
    # C uses dynamic realloc; we use a fixed-size local buffer.
    # Capped at 65536 (safe for grids up to ~8192x8192).
    cdef I64 APEXLIST_CAP = 65536
    cdef I64 apexlist[65536]
    cdef I64 nxt_from
    cdef I64 ar_mn, ac_mn, ad_mn, af_mn
    cdef I64 new_f, new_f2
    cdef I64 startlevel6
    cdef I32[::1] lf, lt, la_r, la_c
    cdef I64[::1] lv
    cdef I8[::1]  la_d

    ncol = nc + 1
    narc_row = ncol
    cand_cap = <I64>len(cf_A)

    bkt_curr = bkt_maxind

    # ---- InitTree ----
    sid = source_id
    node_group[sid]   = 1
    node_outcost[sid] = 0
    node_incost[sid]  = 0
    node_pred[sid]    = -1
    node_prev[sid]    = <I32>sid
    node_next[sid]    = <I32>sid
    node_level[sid]   = 0

    _get_arc_num_lims_cy(node_row[sid], ngroundarcs, &arcnum, &upperarcnum)
    while arcnum < upperarcnum:
        arcnum += 1
        _neighbor_node_grid_cy(node_row[sid], node_col[sid],
                               arcnum, ngroundarcs, ni, nc, ground_id,
                               &to_id, &arcrow, &arccol, &arcdir)
        if node_group[to_id] != PRUNED and node_group[to_id] != MASKED:
            _add_new_node_cy(sid, to_id, arcdir, arcrow, arccol,
                             nflow, node_outcost, node_pred, node_group,
                             node_next, node_prev, incr_pos, incr_neg,
                             bkt_head, &bkt_curr, bkt_minind, bkt_maxind, narc_row)

    # ---- candidate double-buffer init ----
    cand_n_bag = 0
    cand_n_lst = 0
    buf_sel    = 0   # 0 → bag=A, lst=B;  1 → bag=B, lst=A

    groupcounter = 2
    ipivots      = 0
    inondegen    = 0
    treesize     = 1
    nmajor       = 0
    maxnewnodes  = <I64>ceil(float(nconnected) * maxnewnodeconst)
    npruned      = 0

    # C has no cycling guard; 100x nconnected is a safety cap
    # against true infinite cycling.  10x was too tight for some patches;
    # 10000x causes multi-hour runtimes on hard instances.
    _cand_max_iter = nconnected * 100

    # ---- outer loop: grow spanning tree ----
    while treesize < nconnected:

        nnewnodes = 0
        while nnewnodes < maxnewnodes and treesize < nconnected:

            to_id = _min_out_cost_node_cy(node_next, node_prev, node_group,
                                          bkt_head, &bkt_curr, bkt_maxind, bkt_minind)
            if to_id < 0:
                break

            from_id = <I64>node_pred[to_id]
            _get_arc_grid_cy(node_row[from_id], node_col[from_id],
                             node_row[to_id], node_col[to_id],
                             ni, nc, ground_id, from_id, to_id,
                             &arcrow2, &arccol2, &arcdir2)
            arc_flat = arcrow2 * narc_row + arccol2

            node_group[to_id]   = 1
            node_level[to_id]   = node_level[from_id] + 1
            node_incost[to_id]  = (node_incost[from_id]
                                   + _get_cost_cy(incr_pos, incr_neg, arc_flat, -arcdir2))
            nxt_from = <I64>node_next[from_id]
            node_next[to_id]    = <I32>nxt_from
            node_prev[to_id]    = <I32>from_id
            node_prev[nxt_from] = <I32>to_id
            node_next[from_id]  = <I32>to_id

            # Scan new node's neighbours
            _get_arc_num_lims_cy(node_row[to_id], ngroundarcs, &arcnum2, &upperarcnum2)
            while arcnum2 < upperarcnum2:
                arcnum2 += 1
                _neighbor_node_grid_cy(node_row[to_id], node_col[to_id],
                                       arcnum2, ngroundarcs, ni, nc, ground_id,
                                       &nd2, &arcrow_n, &arccol_n, &arcdir_n)
                arc_flat_n = arcrow_n * narc_row + arccol_n
                grp_nb = node_group[nd2]
                if grp_nb > 0:
                    if nd2 != <I64>node_pred[to_id]:
                        arc_flat_n = arcrow_n * narc_row + arccol_n
                        cycleapex = _find_apex_cy(to_id, nd2, node_level, node_pred)
                        if cycleapex == -11111:
                            return -11111
                        apex_arr[arc_flat_n] = <I32>cycleapex
                        if buf_sel == 0:
                            _check_arc_reduced_cost_cy(
                                to_id, nd2, cycleapex, arcrow_n, arccol_n, arcdir_n,
                                node_outcost, node_incost, incr_pos, incr_neg, iscandidate,
                                cf_A, ct_A, cv_A, car_A, cac_A, cad_A,
                                &cand_n_bag, cand_cap, narc_row)
                        else:
                            _check_arc_reduced_cost_cy(
                                to_id, nd2, cycleapex, arcrow_n, arccol_n, arcdir_n,
                                node_outcost, node_incost, incr_pos, incr_neg, iscandidate,
                                cf_B, ct_B, cv_B, car_B, cac_B, cad_B,
                                &cand_n_bag, cand_cap, narc_row)
                    else:
                        apex_arr[arc_flat_n] = NULL_APEX
                elif grp_nb != PRUNED and grp_nb != MASKED:
                    _add_new_node_cy(to_id, nd2, arcdir_n, arcrow_n, arccol_n,
                                     nflow, node_outcost, node_pred, node_group,
                                     node_next, node_prev, incr_pos, incr_neg,
                                     bkt_head, &bkt_curr, bkt_minind, bkt_maxind, narc_row)

            nnewnodes += 1
            treesize  += 1

        # ---- inner loop: process candidate list ----
        _cand_iter_guard = 0
        while cand_n_bag > 0:
            _cand_iter_guard += 1
            if _cand_iter_guard > _cand_max_iter:
                return -9999

            # Swap bag ↔ list
            cand_n_lst = cand_n_bag
            cand_n_bag = 0
            buf_sel    = 1 - buf_sel

            # Select correct list arrays (now lst = old bag, new bag = other)
            if buf_sel == 0:
                lf = cf_A; lt = ct_A; lv = cv_A; la_r = car_A; la_c = cac_A; la_d = cad_A
            else:
                lf = cf_B; lt = ct_B; lv = cv_B; la_r = car_B; la_c = cac_B; la_d = cad_B

            nL = cand_n_lst

            # Sort (insertion sort — matches C's qsort(CandidateCompare))
            _insertion_sort_candidates_cy(lf, lt, lv, la_r, la_c, la_d, nL)

            # Normalize arcdir to ±1
            for i_nd in range(nL):
                ad_val = <I64>la_d[i_nd]
                if ad_val > 1:   la_d[i_nd] = 1
                elif ad_val < -1: la_d[i_nd] = -1

            # Process candidates
            for i_cand in range(nL):
                from_id = <I64>lf[i_cand]
                to_id   = <I64>lt[i_cand]
                arcdir  = <I64>la_d[i_cand]
                arcrow  = <I64>la_r[i_cand]
                arccol  = <I64>la_c[i_cand]
                arc_flat = arcrow * narc_row + arccol

                iscandidate[arc_flat] = 0

                apex_id = <I64>apex_arr[arc_flat]
                if apex_id == -2:   # NONTREEARC
                    continue

                outcostto = (node_outcost[from_id]
                             + _get_cost_cy(incr_pos, incr_neg, arc_flat, arcdir))
                if apex_id == -1:
                    apex_sum = 0
                else:
                    apex_sum = node_outcost[apex_id] + node_incost[apex_id]
                cyclecost = outcostto + node_incost[to_id] - apex_sum

                if not (outcostto < node_outcost[to_id] or cyclecost < 0):
                    to_tmp = to_id; to_id = from_id; from_id = to_tmp
                    arcdir = -arcdir
                    outcostto = (node_outcost[from_id]
                                 + _get_cost_cy(incr_pos, incr_neg, arc_flat, arcdir))
                    cyclecost = outcostto + node_incost[to_id] - apex_sum

                if not (outcostto < node_outcost[to_id] or cyclecost < 0):
                    continue

                # group counter overflow guard
                groupcounter += 1
                if groupcounter > LARGEINT:
                    for i_nd in range(<I64>len(node_group)):
                        if node_group[i_nd] > 0:
                            node_group[i_nd] = 1
                    groupcounter = 2

                leavingchild = -1
                fromside     = 1   # True

                # ---- augmenting pivot ----
                if cyclecost < 0:
                    _aug_iter = 0
                    while True:
                        _aug_iter += 1
                        if _aug_iter > nconnected * 10:
                            return -8888
                        fromside     = 1
                        node1        = from_id
                        node2        = to_id
                        leavingchild = -1

                        flows[arcrow, arccol] = <I16>(<I64>flows[arcrow, arccol] + arcdir * nflow)
                        _recalc_cost_cy(costmode, costs_off, costs_sig, costs_dzm, costs_lay,
                                        incr_pos, incr_neg, arc_flat,
                                        <I64>flows[arcrow, arccol], nflow, nshortcycle)
                        violation = _get_cost_cy(incr_pos, incr_neg, arc_flat, arcdir)

                        while node_level[node1] > node_level[node2]:
                            _get_arc_grid_cy(
                                node_row[<I64>node_pred[node1]], node_col[<I64>node_pred[node1]],
                                node_row[node1], node_col[node1],
                                ni, nc, ground_id, <I64>node_pred[node1], node1,
                                &arcrow1, &arccol1, &arcdir1)
                            af3 = arcrow1 * narc_row + arccol1
                            new_f = <I64>flows[arcrow1, arccol1] + arcdir1 * nflow
                            flows[arcrow1, arccol1] = <I16>new_f
                            _recalc_cost_cy(costmode, costs_off, costs_sig, costs_dzm, costs_lay,
                                            incr_pos, incr_neg, af3,
                                            <I64>flows[arcrow1, arccol1], nflow, nshortcycle)
                            if leavingchild < 0 and flows[arcrow1, arccol1] == 0:
                                leavingchild = node1
                            violation += _get_cost_cy(incr_pos, incr_neg, af3, arcdir1)
                            node_group[node1] = groupcounter + 1
                            node1 = <I64>node_pred[node1]

                        while node_level[node2] > node_level[node1]:
                            _get_arc_grid_cy(
                                node_row[<I64>node_pred[node2]], node_col[<I64>node_pred[node2]],
                                node_row[node2], node_col[node2],
                                ni, nc, ground_id, <I64>node_pred[node2], node2,
                                &arcrow2, &arccol2, &arcdir2)
                            af4 = arcrow2 * narc_row + arccol2
                            new_f2 = <I64>flows[arcrow2, arccol2] - arcdir2 * nflow
                            flows[arcrow2, arccol2] = <I16>new_f2
                            _recalc_cost_cy(costmode, costs_off, costs_sig, costs_dzm, costs_lay,
                                            incr_pos, incr_neg, af4,
                                            <I64>flows[arcrow2, arccol2], nflow, nshortcycle)
                            if flows[arcrow2, arccol2] == 0:
                                leavingchild = node2; fromside = 0
                            violation += _get_cost_cy(incr_pos, incr_neg, af4, -arcdir2)
                            node_group[node2] = groupcounter
                            node2 = <I64>node_pred[node2]

                        while node1 != node2:
                            _get_arc_grid_cy(
                                node_row[<I64>node_pred[node1]], node_col[<I64>node_pred[node1]],
                                node_row[node1], node_col[node1],
                                ni, nc, ground_id, <I64>node_pred[node1], node1,
                                &arcrow1, &arccol1, &arcdir1)
                            _get_arc_grid_cy(
                                node_row[<I64>node_pred[node2]], node_col[<I64>node_pred[node2]],
                                node_row[node2], node_col[node2],
                                ni, nc, ground_id, <I64>node_pred[node2], node2,
                                &arcrow2, &arccol2, &arcdir2)
                            af3 = arcrow1 * narc_row + arccol1
                            af4 = arcrow2 * narc_row + arccol2
                            flows[arcrow1, arccol1] = <I16>(<I64>flows[arcrow1, arccol1] + arcdir1 * nflow)
                            flows[arcrow2, arccol2] = <I16>(<I64>flows[arcrow2, arccol2] - arcdir2 * nflow)
                            _recalc_cost_cy(costmode, costs_off, costs_sig, costs_dzm, costs_lay,
                                            incr_pos, incr_neg, af3,
                                            <I64>flows[arcrow1, arccol1], nflow, nshortcycle)
                            _recalc_cost_cy(costmode, costs_off, costs_sig, costs_dzm, costs_lay,
                                            incr_pos, incr_neg, af4,
                                            <I64>flows[arcrow2, arccol2], nflow, nshortcycle)
                            violation += (_get_cost_cy(incr_pos, incr_neg, af3, arcdir1)
                                          + _get_cost_cy(incr_pos, incr_neg, af4, -arcdir2))
                            if flows[arcrow2, arccol2] == 0:
                                leavingchild = node2; fromside = 0
                            elif leavingchild < 0 and flows[arcrow1, arccol1] == 0:
                                leavingchild = node1
                            node_group[node1] = groupcounter + 1
                            node_group[node2] = groupcounter
                            node1 = <I64>node_pred[node1]
                            node2 = <I64>node_pred[node2]

                        if violation >= 0:
                            break
                    inondegen += 1

                # ---- degenerate pivot ----
                else:
                    fromside     = 0
                    node1        = from_id
                    node2        = to_id
                    leavingchild = -1

                    while node_level[node1] > node_level[node2]:
                        node_group[node1] = groupcounter + 1
                        node1 = <I64>node_pred[node1]

                    while node_level[node2] > node_level[node1]:
                        if outcostto < node_outcost[node2]:
                            leavingchild = node2
                            _get_arc_grid_cy(
                                node_row[<I64>node_pred[node2]], node_col[<I64>node_pred[node2]],
                                node_row[node2], node_col[node2],
                                ni, nc, ground_id, <I64>node_pred[node2], node2,
                                &arcrow2, &arccol2, &arcdir2)
                            outcostto += _get_cost_cy(incr_pos, incr_neg,
                                                      arcrow2 * narc_row + arccol2, -arcdir2)
                        else:
                            outcostto = LARGEINT
                        node_group[node2] = groupcounter
                        node2 = <I64>node_pred[node2]

                    while node1 != node2:
                        if outcostto < node_outcost[node2]:
                            leavingchild = node2
                            _get_arc_grid_cy(
                                node_row[<I64>node_pred[node2]], node_col[<I64>node_pred[node2]],
                                node_row[node2], node_col[node2],
                                ni, nc, ground_id, <I64>node_pred[node2], node2,
                                &arcrow2, &arccol2, &arcdir2)
                            outcostto += _get_cost_cy(incr_pos, incr_neg,
                                                      arcrow2 * narc_row + arccol2, -arcdir2)
                        else:
                            outcostto = LARGEINT
                        node_group[node1] = groupcounter + 1
                        node_group[node2] = groupcounter
                        node1 = <I64>node_pred[node1]
                        node2 = <I64>node_pred[node2]

                # cycleapex = node1 = node2
                cycleapex = node1

                if leavingchild < 0:
                    fromside      = 1
                    leavingparent = from_id
                else:
                    leavingparent = <I64>node_pred[leavingchild]

                if fromside:
                    groupcounter += 1
                    fromgroup     = groupcounter - 1
                    to_tmp = to_id; to_id = from_id; from_id = to_tmp
                else:
                    fromgroup = groupcounter + 1

                # ---- NonDegenUpdateChildren (augmenting only) ----
                if cyclecost < 0:
                    firstfromnode = -1
                    firsttonode   = -1
                    _get_arc_num_lims_cy(node_row[cycleapex], ngroundarcs, &arcnum3, &upper3)
                    while arcnum3 < upper3:
                        arcnum3 += 1
                        _neighbor_node_grid_cy(node_row[cycleapex], node_col[cycleapex],
                                              arcnum3, ngroundarcs, ni, nc, ground_id,
                                              &tmpnd, &ar3, &ac3, &ad3)
                        _get_arc_grid_cy(node_row[cycleapex], node_col[cycleapex],
                                         node_row[tmpnd], node_col[tmpnd],
                                         ni, nc, ground_id, cycleapex, tmpnd,
                                         &ar3, &ac3, &ad3)
                        af3 = ar3 * narc_row + ac3
                        if (node_group[tmpnd] == groupcounter
                                and <I64>apex_arr[af3] == -1):
                            firsttonode = tmpnd
                            if firstfromnode >= 0:
                                break
                        elif (node_group[tmpnd] == fromgroup
                              and <I64>apex_arr[af3] == -1):
                            firstfromnode = tmpnd
                            if firsttonode >= 0:
                                break

                    node_group[cycleapex] = groupcounter + 2

                    if firsttonode >= 0:
                        _non_degen_update_children_cy(
                            cycleapex, leavingparent, firsttonode,
                            0, ngroundarcs, ni, nc, ground_id, narc_row,
                            node_row, node_col, node_pred, node_next, node_level,
                            node_group, node_outcost, node_incost,
                            incr_pos, incr_neg, apex_arr)

                    if firstfromnode >= 0:
                        _non_degen_update_children_cy(
                            cycleapex, from_id, firstfromnode,
                            1, ngroundarcs, ni, nc, ground_id, narc_row,
                            node_row, node_col, node_pred, node_next, node_level,
                            node_group, node_outcost, node_incost,
                            incr_pos, incr_neg, apex_arr)

                    groupcounter  = node_group[from_id]
                    apexlistbase  = node_group[cycleapex]
                    fromgroup     = node_group[cycleapex]

                else:
                    node_group[cycleapex] = fromgroup
                    groupcounter  += 2
                    apexlistbase   = groupcounter + 1

                # ---- Remount subtree ----
                if leavingchild < 0:
                    skipthread = to_id
                else:
                    root     = from_id
                    oldmntpt = to_id

                    # 1. Remount loop
                    nd1 = root
                    _remount_guard = 0
                    while oldmntpt != leavingparent:
                        _remount_guard += 1
                        if _remount_guard > nconnected * 4:
                            return -3333
                        mntpt    = root
                        root     = oldmntpt
                        oldmntpt = <I64>node_pred[root]
                        node_pred[root] = <I32>mntpt

                        _get_arc_grid_cy(node_row[mntpt], node_col[mntpt],
                                         node_row[root], node_col[root],
                                         ni, nc, ground_id, mntpt, root,
                                         &ar_mn, &ac_mn, &ad_mn)
                        af_mn = ar_mn * narc_row + ac_mn

                        dlevel   = node_level[mntpt] - node_level[root] + 1
                        doutcost = (node_outcost[mntpt] - node_outcost[root]
                                    + _get_cost_cy(incr_pos, incr_neg, af_mn, ad_mn))
                        dincost  = (node_incost[mntpt] - node_incost[root]
                                    + _get_cost_cy(incr_pos, incr_neg, af_mn, -ad_mn))

                        groupcounter += 1
                        nd1 = root
                        startlevel = node_level[root]
                        _thr1_guard = 0
                        while True:
                            _thr1_guard += 1
                            if _thr1_guard > nconnected * 4:
                                return -6666
                            node_level[nd1]   += dlevel
                            node_outcost[nd1] += doutcost
                            node_incost[nd1]  += dincost
                            node_group[nd1]    = groupcounter
                            if node_level[<I64>node_next[nd1]] <= startlevel:
                                break
                            nd1 = <I64>node_next[nd1]

                        # Rewire threads
                        prv_root = <I64>node_prev[root]
                        nxt_nd1  = <I64>node_next[nd1]
                        nxt_mnt  = <I64>node_next[mntpt]
                        if prv_root == mntpt:
                            nxt_mnt = nxt_nd1

                        node_next[prv_root] = <I32>nxt_nd1
                        node_prev[nxt_nd1]  = <I32>prv_root
                        node_next[nd1]      = <I32>nxt_mnt
                        node_prev[nxt_mnt]  = <I32>nd1
                        node_next[mntpt]    = <I32>root
                        node_prev[root]     = <I32>mntpt

                    # 2. skipthread
                    skipthread = <I64>node_next[nd1]

                    # 3. Reset apex for entering/leaving arcs
                    _get_arc_grid_cy(node_row[from_id], node_col[from_id],
                                     node_row[to_id], node_col[to_id],
                                     ni, nc, ground_id, from_id, to_id,
                                     &ar_en, &ac_en, &arcdir1)
                    apex_arr[ar_en * narc_row + ac_en] = NULL_APEX

                    _get_arc_grid_cy(node_row[leavingparent], node_col[leavingparent],
                                     node_row[leavingchild], node_col[leavingchild],
                                     ni, nc, ground_id, leavingparent, leavingchild,
                                     &ar_lv, &ac_lv, &arcdir1)
                    apex_arr[ar_lv * narc_row + ac_lv] = <I32>cycleapex

                    # 4. Build apexlist
                    apexlistlen = groupcounter - apexlistbase + 2
                    if apexlistlen < 1:
                        apexlistlen = 1
                    if apexlistlen > APEXLIST_CAP:
                        apexlistlen = APEXLIST_CAP
                    nd2 = leavingchild
                    for g1 in range(groupcounter, apexlistbase - 1, -1):
                        idx_al = g1 - apexlistbase
                        if 0 <= idx_al < apexlistlen:
                            apexlist[idx_al] = nd2
                        if <I64>node_pred[nd2] >= 0:
                            nd2 = <I64>node_pred[nd2]

                    # 5. Scan remounted subtree from 'to'
                    nd1 = to_id
                    startlevel = node_level[to_id]
                    _thr2_guard = 0
                    while True:
                        _thr2_guard += 1
                        if _thr2_guard > nconnected * 4:
                            return -4444
                        _get_arc_num_lims_cy(node_row[nd1], ngroundarcs, &arcnum4, &upper4)
                        while arcnum4 < upper4:
                            arcnum4 += 1
                            _neighbor_node_grid_cy(node_row[nd1], node_col[nd1],
                                                  arcnum4, ngroundarcs, ni, nc, ground_id,
                                                  &nd2, &ar2, &ac2, &ad2)
                            af4 = ar2 * narc_row + ac2
                            grp2 = node_group[nd2]
                            if grp2 > 0:
                                ap2 = <I64>apex_arr[af4]
                                if (grp2 < node_group[nd1]
                                        and ap2 != -2 and ap2 != -1):
                                    idx_al4 = grp2 - apexlistbase
                                    if 0 <= idx_al4 < apexlistlen:
                                        apex_arr[af4] = <I32>apexlist[idx_al4]
                                    else:
                                        if 0 <= ap2 < <I64>len(node_level):
                                            if node_level[ap2] > node_level[cycleapex]:
                                                apex_arr[af4] = <I32>cycleapex
                                            elif ap2 == cycleapex:
                                                tmpnd2 = nd2
                                                g_guard = 0
                                                while node_group[tmpnd2] != fromgroup:
                                                    g_guard += 1
                                                    if g_guard > nconnected * 4:
                                                        return -2222
                                                    tmpnd2 = <I64>node_pred[tmpnd2]
                                                apex_arr[af4] = <I32>tmpnd2

                                    new_apex4 = <I64>apex_arr[af4]
                                    if new_apex4 >= 0:
                                        if buf_sel == 0:
                                            _check_arc_reduced_cost_cy(
                                                nd1, nd2, new_apex4, ar2, ac2, ad2,
                                                node_outcost, node_incost,
                                                incr_pos, incr_neg, iscandidate,
                                                cf_A, ct_A, cv_A, car_A, cac_A, cad_A,
                                                &cand_n_bag, cand_cap, narc_row)
                                        else:
                                            _check_arc_reduced_cost_cy(
                                                nd1, nd2, new_apex4, ar2, ac2, ad2,
                                                node_outcost, node_incost,
                                                incr_pos, incr_neg, iscandidate,
                                                cf_B, ct_B, cv_B, car_B, cac_B, cad_B,
                                                &cand_n_bag, cand_cap, narc_row)
                            elif grp2 != PRUNED and grp2 != MASKED:
                                _add_new_node_cy(nd1, nd2, ad2, ar2, ac2, nflow,
                                                 node_outcost, node_pred, node_group,
                                                 node_next, node_prev,
                                                 incr_pos, incr_neg, bkt_head, &bkt_curr,
                                                 bkt_minind, bkt_maxind, narc_row)

                        nd1 = <I64>node_next[nd1]
                        if node_level[nd1] <= startlevel:
                            break

                # ---- Augmenting cycle children scan ----
                if cyclecost < 0:
                    first_scan_done_to   = 1 if firsttonode < 0 else 0
                    first_scan_done_from = 1 if firstfromnode < 0 else 0
                    _asc_outer = 0
                    while True:
                        _asc_outer += 1
                        if _asc_outer > 3:
                            return -7777
                        if (first_scan_done_to == 0
                                and node_pred[firsttonode] == <I32>cycleapex):
                            nd1 = firsttonode
                            first_scan_done_to = 1
                        elif (first_scan_done_from == 0
                              and node_pred[firstfromnode] == <I32>cycleapex):
                            nd1 = firstfromnode
                            first_scan_done_from = 1
                        else:
                            break
                        startlevel6 = node_level[nd1]

                        _asc_inner = 0
                        while True:
                            _asc_inner += 1
                            if _asc_inner > nconnected * 4:
                                return -5555
                            _get_arc_num_lims_cy(node_row[nd1], ngroundarcs, &arcnum6, &upper6)
                            while arcnum6 < upper6:
                                arcnum6 += 1
                                _neighbor_node_grid_cy(node_row[nd1], node_col[nd1],
                                                      arcnum6, ngroundarcs, ni, nc, ground_id,
                                                      &nd2, &ar6, &ac6, &ad6)
                                af6 = ar6 * narc_row + ac6
                                grp6 = node_group[nd2]
                                if grp6 > 0:
                                    ap6 = <I64>apex_arr[af6]
                                    if (ap6 != -1
                                            and (grp6 != node_group[nd1]
                                                 or node_group[nd1] == apexlistbase)):
                                        if buf_sel == 0:
                                            _check_arc_reduced_cost_cy(
                                                nd1, nd2, ap6, ar6, ac6, ad6,
                                                node_outcost, node_incost,
                                                incr_pos, incr_neg, iscandidate,
                                                cf_A, ct_A, cv_A, car_A, cac_A, cad_A,
                                                &cand_n_bag, cand_cap, narc_row)
                                        else:
                                            _check_arc_reduced_cost_cy(
                                                nd1, nd2, ap6, ar6, ac6, ad6,
                                                node_outcost, node_incost,
                                                incr_pos, incr_neg, iscandidate,
                                                cf_B, ct_B, cv_B, car_B, cac_B, cad_B,
                                                &cand_n_bag, cand_cap, narc_row)
                                elif grp6 != PRUNED and grp6 != MASKED:
                                    _add_new_node_cy(nd1, nd2, ad6, ar6, ac6, nflow,
                                                     node_outcost, node_pred, node_group,
                                                     node_next, node_prev,
                                                     incr_pos, incr_neg, bkt_head, &bkt_curr,
                                                     bkt_minind, bkt_maxind, narc_row)

                            nd1 = <I64>node_next[nd1]
                            if nd1 == to_id:
                                nd1 = skipthread
                            if node_level[nd1] <= startlevel6:
                                break

                ipivots += 1

        # Prune periodically
        nmajor += 1
        if nmajorprune > 0 and nmajor % nmajorprune == 0:
            npruned += _prune_tree_cy(
                source_id, node_row, node_col, node_next, node_prev,
                node_pred, node_level, node_group, node_incost, node_outcost,
                incr_pos, incr_neg, flows_flat, ngroundarcs, prunecostthresh,
                ni, nc, ground_id, narc_row)

    return inondegen
