# _surface_kernel.pyx — Cython GS-SOR kernel for gmt_surface_py (float32 version)
#
# ARITHMETIC CONTRACT — matches main's float32 Numba _iterate_once exactly:
#
#   u[]         : float (float32) — gmt_grdfloat, same as C surface.c
#   briggs_b[]  : float (float32) — stored as gmt_grdfloat in C
#   coeff_*     : double (float64)
#   status[]    : unsigned char
#
#   Unconstrained stencil sum:
#     u[node+dk] is float32, coeff is double.
#     In C (and Numba), float32 * float64 promotes to double implicitly.
#     Sum accumulates in double (u_00 is double).
#
#   Constrained Briggs sum:
#     briggs_b[k] * u[node+dk] is float32 * float32 = float32 (stays float32).
#     That float32 product is then cast to double individually (NOT as a group).
#     The 4 double values are summed in double.
#     This matches the Numba: np.float64(briggs_b[bidx,k]*u[node+d_node[pk]])
#     in main's _iterate_once lines 520-523.
#
#   u[node] write-back:
#     u_00 is double; storing into float[::1] u truncates to float32.
#     This is the key non-trivial step: each iteration's write quantises to
#     float32, so subsequent reads (GS, in-place) see float32 values.
#
#   _set_bcs:
#     u[] is float32. BC arithmetic uses double temporaries (C promotes float
#     operands to double in expressions mixed with double constants — y0c etc
#     are double). Writing result back to u[] truncates to float32 each time.
#
# C source: /tmp/gmt_src/src/surface.c lines 1047-1118 (surface_set_BCs)
#                                        lines 1078-1159 (surface_iterate)
#
# Compile flags: -O2 -march=native -ffp-contract=off
#   -ffp-contract=off prevents GCC from fusing multiply-add into FMA, which
#   would change the rounding order of the float32*float32 Briggs products
#   and break bit-identity with Numba (which also uses -ffp-contract=off via
#   LLVM's -disable-fp-elim / no-contract attribute on the float32 muls).

# cython: language_level=3
cimport cython
import numpy as np
cimport numpy as np

# C-level float and double typedefs
ctypedef float   FTYPE    # float32 = gmt_grdfloat
ctypedef double  DTYPE    # float64
ctypedef np.int64_t  ITYPE
ctypedef np.uint8_t  UTYPE


@cython.boundscheck(False)
@cython.wraparound(False)
@cython.cdivision(True)
@cython.nonecheck(False)
def iterate_once_cy(
        float[::1] u,                  # float32 grid (in-place GS-SOR), gmt_grdfloat
        unsigned char[::1] status,
        float[:, ::1] briggs_b,        # shape (N_briggs, 6), float32
        long[::1] briggs_idx_of_node,  # shape (mxmy,), int64; -1 = none
        double[::1] coeff_unc,         # 12 weights (float64), unconstrained
        double[::1] coeff_con,         # 12 weights (float64), constrained
        long[::1] d_node,              # 12 stencil offsets (int64)
        long[:, ::1] p_indices,        # (5, 4) quadrant->offset-index table
        double a0_const_2,
        double relax_old,
        double relax_new,
        long node_nw,
        int current_nx,
        int current_ny,
        int current_mx,
):
    """One full GS-SOR sweep over interior nodes.  Returns max |u_change|.

    Bit-identical to main's Numba _iterate_once (float32 version, Mira #72).
    Matches surface_iterate surface.c:1078-1159.
    """
    cdef:
        long node, row, col, bidx
        long p0, p1, p2, p3
        # Hoisted stencil offsets — C locals, kept in registers by compiler
        long dN2, dNW, dN1, dNE, dW2, dW1, dE1, dE2, dSW, dS1, dSE, dS2
        # Hoisted unconstrained weights (double)
        double cuN2, cuNW, cuN1, cuNE, cuW2, cuW1, cuE1, cuE2
        double cuSW, cuS1, cuSE, cuS2
        # Hoisted constrained weights (double)
        double ccN2, ccNW, ccN1, ccNE, ccW2, ccW1, ccE1, ccE2
        double ccSW, ccS1, ccSE, ccS2
        unsigned char stat
        double u_00, old, change, max_u_change
        # Briggs intermediate: float32 product cast to double before summing
        double sum_bk_uk
        float prod0, prod1, prod2, prod3   # float32 products (must NOT fuse to FMA)

    # Hoist offset array into C locals
    dN2 = d_node[0];  dNW = d_node[1];  dN1 = d_node[2];  dNE = d_node[3]
    dW2 = d_node[4];  dW1 = d_node[5];  dE1 = d_node[6];  dE2 = d_node[7]
    dSW = d_node[8];  dS1 = d_node[9];  dSE = d_node[10]; dS2 = d_node[11]

    # Hoist unconstrained-node weights
    cuN2 = coeff_unc[0];  cuNW = coeff_unc[1];  cuN1 = coeff_unc[2];  cuNE = coeff_unc[3]
    cuW2 = coeff_unc[4];  cuW1 = coeff_unc[5];  cuE1 = coeff_unc[6];  cuE2 = coeff_unc[7]
    cuSW = coeff_unc[8];  cuS1 = coeff_unc[9];  cuSE = coeff_unc[10]; cuS2 = coeff_unc[11]

    # Hoist constrained-node weights
    ccN2 = coeff_con[0];  ccNW = coeff_con[1];  ccN1 = coeff_con[2];  ccNE = coeff_con[3]
    ccW2 = coeff_con[4];  ccW1 = coeff_con[5];  ccE1 = coeff_con[6];  ccE2 = coeff_con[7]
    ccSW = coeff_con[8];  ccS1 = coeff_con[9];  ccSE = coeff_con[10]; ccS2 = coeff_con[11]

    max_u_change = -1.0

    for row in range(current_ny):
        node = node_nw + row * current_mx
        for col in range(current_nx):
            stat = status[node]

            if stat == 5:   # SURFACE_IS_CONSTRAINED — pinned, skip
                node += 1
                continue

            if stat == 0:   # SURFACE_IS_UNCONSTRAINED
                # u[] is float32; coeff is double.
                # float32 * float64 → double (C implicit promotion, no truncation).
                # Sum accumulates in double u_00.
                u_00 = (<double>u[node + dN2] * cuN2
                        + <double>u[node + dNW] * cuNW
                        + <double>u[node + dN1] * cuN1
                        + <double>u[node + dNE] * cuNE
                        + <double>u[node + dW2] * cuW2
                        + <double>u[node + dW1] * cuW1
                        + <double>u[node + dE1] * cuE1
                        + <double>u[node + dE2] * cuE2
                        + <double>u[node + dSW] * cuSW
                        + <double>u[node + dS1] * cuS1
                        + <double>u[node + dSE] * cuSE
                        + <double>u[node + dS2] * cuS2)
            else:           # stat in 1..4 (SURFACE_DATA_IS_IN_QUAD1..4)
                # Same float32*float64 → double promotion for stencil sum
                u_00 = (<double>u[node + dN2] * ccN2
                        + <double>u[node + dNW] * ccNW
                        + <double>u[node + dN1] * ccN1
                        + <double>u[node + dNE] * ccNE
                        + <double>u[node + dW2] * ccW2
                        + <double>u[node + dW1] * ccW1
                        + <double>u[node + dE1] * ccE1
                        + <double>u[node + dE2] * ccE2
                        + <double>u[node + dSW] * ccSW
                        + <double>u[node + dS1] * ccS1
                        + <double>u[node + dSE] * ccSE
                        + <double>u[node + dS2] * ccS2)

                bidx = briggs_idx_of_node[node]
                p0 = p_indices[stat, 0]
                p1 = p_indices[stat, 1]
                p2 = p_indices[stat, 2]
                p3 = p_indices[stat, 3]

                # CRITICAL: b[k]*u[...] must be float32*float32=float32 product
                # stored as a float variable BEFORE promotion to double.
                # This matches Numba: np.float64(briggs_b[bidx,k]*u[node+d_node[pk]])
                # where briggs_b is float32 and u is float32 → product is float32,
                # then np.float64(...) promotes to double individually.
                # -ffp-contract=off prevents the compiler from fusing these into
                # FMAs (which would keep intermediate in float80/double precision).
                prod0 = briggs_b[bidx, 0] * u[node + d_node[p0]]
                prod1 = briggs_b[bidx, 1] * u[node + d_node[p1]]
                prod2 = briggs_b[bidx, 2] * u[node + d_node[p2]]
                prod3 = briggs_b[bidx, 3] * u[node + d_node[p3]]
                sum_bk_uk = (<double>prod0 + <double>prod1
                             + <double>prod2 + <double>prod3)

                u_00 = (u_00 + a0_const_2 * (sum_bk_uk
                        + <double>briggs_b[bidx, 4])) * <double>briggs_b[bidx, 5]

            old = <double>u[node]
            u_00 = old * relax_old + u_00 * relax_new
            change = u_00 - old
            if change < 0.0:
                change = -change
            if change > max_u_change:
                max_u_change = change
            # Write-back: double → float32 (truncates, matches C and Numba).
            # Numba with float[::1] u: u[node] = u_00 (double) stores as float32.
            u[node] = <float>u_00
            node += 1

    return max_u_change


@cython.boundscheck(False)
@cython.wraparound(False)
@cython.cdivision(True)
@cython.nonecheck(False)
def set_bcs_cy(
        float[::1] u,            # float32 grid (gmt_grdfloat)
        int current_nx,
        int current_ny,
        int current_mx,
        long node_sw,
        long node_nw,
        long node_se,
        long node_ne,
        long d_N2, long d_NW, long d_N1, long d_NE,
        long d_W2, long d_W1, long d_E1, long d_E2,
        long d_SW, long d_S1, long d_SE, long d_S2,
        double x0c, double x1c, double y0c, double y1c,
        double eps_p2, double eps_m2,
        double two_plus_ep2, double two_plus_em2,
):
    """Apply natural BCs (eqs A-8..A-10) to the 2-wide ghost ring.

    Mirrors surface_set_BCs (surface.c:1047-1118) and the Numba _set_bcs.

    PRECISION CONTRACT (must match Numba exactly):
    - u[] is float32.  BC scalars (x0c, y0c, eps_m2, etc.) are double.
    - BC1: y0c * u[a] + y1c * u[b]
        double * float32 -> double per term; sum in double; truncate to float32.
        In Numba: float32 read, float64 scalar -> product is float64. Correct.
    - Corner BCs: u[a] + u[b] - u[c]
        All float32 operands -> float32 arithmetic in Numba (no float64 mixing).
        In Cython: use float temporaries (no <double> cast on individual reads).
    - BC2: u[N2] + eps_m2*(u[NW]+u[NE]-u[SW]-u[SE]) + two_plus*(u[S1]-u[N1])
        The parenthesised sub-sums (u[NW]+u[NE]-u[SW]-u[SE]) and (u[S1]-u[N1])
        are pure float32 expressions in Numba (no float64 operand in those
        sub-groups). They MUST be computed in float32 before being multiplied
        by eps_m2 / two_plus (float64).  Use `float` cdef temps to force this.
        The outer accumulation:  u[N2] (float32)
                                + float64 (eps_m2 * float32_sub)
                                + float64 (two_plus * float32_sub)
        -> float64; written as float32 via <float> cast.
    """
    cdef:
        long n_s, n_n, n_w, n_e, n
        float f_sub1, f_sub2   # float32 sub-sum temporaries (BC2 inner groups)

    # BC1 South/North edges
    # y0c/y1c are float64 -> products are float64 -> sum is float64 -> truncate.
    n_s = node_sw
    n_n = node_nw
    for _ in range(current_nx):
        u[n_s + d_S1] = <float>(y0c * <double>u[n_s] + y1c * <double>u[n_s + d_N1])
        u[n_n + d_N1] = <float>(y0c * <double>u[n_n] + y1c * <double>u[n_n + d_S1])
        n_s += 1
        n_n += 1

    n_w = node_nw
    n_e = node_ne
    for _ in range(current_ny):
        u[n_w + d_W1] = <float>(x1c * <double>u[n_w + d_E1] + x0c * <double>u[n_w])
        u[n_e + d_E1] = <float>(x1c * <double>u[n_e + d_W1] + x0c * <double>u[n_e])
        n_w += current_mx
        n_e += current_mx

    # Corner BCs: d2/dxdy = 0 at the 4 corners (surface.c:1042-1049).
    # All u[] reads — pure float32 arithmetic in Numba.
    # In Cython: assign to float temporaries then write; the float arithmetic
    # stays in float32 (no <double> widening of individual reads).
    n = node_sw
    u[n + d_SW] = u[n + d_SE] + u[n + d_NW] - u[n + d_NE]
    n = node_nw
    u[n + d_NW] = u[n + d_NE] + u[n + d_SW] - u[n + d_SE]
    n = node_se
    u[n + d_SE] = u[n + d_SW] + u[n + d_NE] - u[n + d_NW]
    n = node_ne
    u[n + d_NE] = u[n + d_NW] + u[n + d_SE] - u[n + d_SW]

    # BC2 South/North (eq A-10).
    # Inner sub-sums are pure float32; outer accumulation is float64.
    # f_sub1 = (u[NW]+u[NE]-u[SW]-u[SE])  -> float32 (4-term, all float32)
    # f_sub2 = (u[S1]-u[N1])              -> float32
    # result = u[N2] + eps_m2*f_sub1 + two_plus_em2*f_sub2
    #        = float32 + float64 + float64 -> float64 -> truncated to float32.
    n_s = node_sw
    n_n = node_nw
    for _ in range(current_nx):
        f_sub1 = u[n_s + d_NW] + u[n_s + d_NE] - u[n_s + d_SW] - u[n_s + d_SE]
        f_sub2 = u[n_s + d_S1] - u[n_s + d_N1]
        u[n_s + d_S2] = <float>(<double>u[n_s + d_N2]
                                + eps_m2 * <double>f_sub1
                                + two_plus_em2 * <double>f_sub2)
        f_sub1 = u[n_n + d_SW] + u[n_n + d_SE] - u[n_n + d_NW] - u[n_n + d_NE]
        f_sub2 = u[n_n + d_N1] - u[n_n + d_S1]
        u[n_n + d_N2] = <float>(<double>u[n_n + d_S2]
                                + eps_m2 * <double>f_sub1
                                + two_plus_em2 * <double>f_sub2)
        n_s += 1
        n_n += 1

    n_w = node_nw
    n_e = node_ne
    for _ in range(current_ny):
        f_sub1 = u[n_w + d_NE] + u[n_w + d_SE] - u[n_w + d_NW] - u[n_w + d_SW]
        f_sub2 = u[n_w + d_W1] - u[n_w + d_E1]
        u[n_w + d_W2] = <float>(<double>u[n_w + d_E2]
                                + eps_p2 * <double>f_sub1
                                + two_plus_ep2 * <double>f_sub2)
        f_sub1 = u[n_e + d_NW] + u[n_e + d_SW] - u[n_e + d_NE] - u[n_e + d_SE]
        f_sub2 = u[n_e + d_E1] - u[n_e + d_W1]
        u[n_e + d_E2] = <float>(<double>u[n_e + d_W2]
                                + eps_p2 * <double>f_sub1
                                + two_plus_ep2 * <double>f_sub2)
        n_w += current_mx
        n_e += current_mx
