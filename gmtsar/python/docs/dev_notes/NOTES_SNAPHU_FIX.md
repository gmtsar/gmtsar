# Snaphu Numba Solver Fix Notes

## Status: IN PROGRESS — Tests failing due to additional bugs beyond Bug 1 and Bug 2

---

## Bugs Fixed in snaphu_solver_numba.py (HEAD state)

### Bug 1: apexlist build order
- **Location**: `snaphu_solver_numba.py`, `_tree_solve_kernel()`, remount section
- **Fix**: apexlist build moved to AFTER `while oldmntpt != leavingparent:` remount loop,
  AFTER `skipthread` assignment, AFTER apex resets for entering/leaving arcs.
  Now uses FINAL groupcounter value, matching C snaphu_solver.c lines 722-735.
- **Status**: Fixed in HEAD.

### Bug 2: prv_root == mntpt thread rewire correction
- **Location**: `snaphu_solver_numba.py`, thread rewire section inside remount loop
- **Fix**: Added `if prv_root == mntpt: nxt_mnt = nxt_nd1` after pre-reading `prv_root,
  nxt_nd1, nxt_mnt`. When `prv_root == mntpt`, C step 1 (`root->prev->next = node1->next`)
  modifies `mntpt->next` before step 3 reads it; numba pre-reads break this unless corrected.
- **Status**: Fixed in HEAD.

---

## Test Results After Fix Verification

### Test 1: 48 synthetic cases (8 seeds × 6 sizes)

Environment:
- NUMBA_CACHE_DIR=/tmp/numba_cache_snaphu
- Python 3.11, numba

Results by size:
- 5×5, seed=42: PASS (numba=scalar=sum4)
- 5×7, seed=42: SCALAR HANGS (Bug 1 unfixed in snaphu_py.py scalar oracle)
- Other sizes: HANGS or MISMATCH

**Test 1 result: FAIL**

Root cause: The scalar oracle `network_flow_optimize` in `snaphu_py.py` has Bug 1
(apexlist before remount) unfixed, causing cycling on 5×7+ with seed=42.

Additionally applied Bug 1 fix to the scalar oracle in the worktree `snaphu_py.py`:
After fix, 5×7 through 20×25 work for seed=42, but 30×30 hangs with a pred cycle.

### Test 2: Real data 30×30 crop — NOT RUN (blocked by Test 1 failures)

### Test 3: Larger sizes (64×64, 256×256) — NOT RUN (blocked by Test 1 failures)

---

## Additional Bugs Found

### Bug A: scalar oracle (`snaphu_py.py`) has Bug 1 unfixed
The scalar `_tree_solve_ts` in `snaphu_py.py` builds apexlist BEFORE the remount loop
(lines 2923-2932 in HEAD). This is the same Bug 1 described for the numba kernel.
Applied fix to worktree `snaphu_py.py`: move apexlist build to after line 2965
(after remount loop, skipthread, and apex resets).

After Bug 1 fix in scalar: 5×7 through 20×25 work for seed=42, but 30×30 hangs.

### Bug B: 30×30 scalar hang — pred cycle in degenerate pivot
After scalar Bug 1 fix, `network_flow_optimize` hangs on 30×30 at line 2837:
`while node2.level > node1.level: node2 = node2.pred`

Tracing shows a 2-node pred cycle: (15,23) → (15,22) → (15,23) cycling forever.
Both nodes have levels 19 and 18 respectively, both above `node1.level=14`.

Root cause: an earlier remount created a circular pred chain. The specific remount
that creates this cycle has not been identified; it may be caused by wrong
`leavingparent` computation or an additional algorithmic divergence from C.

### Bug C: numba cycling guard too tight
`_cand_max_iter = nconnected * 10` fires on valid cases (e.g., 5×7 seed=7),
returning -9999 sentinel and raising RuntimeError. This prevents legitimate
convergence for some inputs.

### Bug D: numba 8×10 infinite hang
The numba kernel hangs on 8×10 with seed=42 (outer `while treesize < nconnected`
loop without a guard). After Bug 1 and Bug 2 are in place, the outer loop still
cycles. This indicates the algorithm reaches a state where the bucket is empty but
the spanning tree is incomplete — caused by tree structure corruption from bugs
earlier in the algorithm.

### Bug E: 5×7 algorithmic divergence
numba and scalar give different (non-equal) results for some 5×7 seeds:
- seed=1: numba and scalar both terminate but flows differ (both sum=8 but different)
- seed=13: numba sum=6, scalar sum=8

---

## Conclusion

The two specified bugs (Bug 1 and Bug 2) are correctly fixed in the numba kernel.
However, tests cannot pass because:

1. The scalar oracle has Bug 1 unfixed (worktree now has it fixed)
2. Both the scalar and numba have additional algorithmic bugs causing hangs and
   divergence on inputs ≥ 20×25 — these bugs are NOT covered by Bug 1 and Bug 2.
3. The test design requires both numba and scalar to agree, not just that numba
   matches C. With additional bugs in both, they may agree on some cases but not all.

Further investigation of Bug B (30×30 pred cycle) and Bug D (numba 8×10 hang)
is needed to identify the root-cause algorithmic divergences from C.

---

## Files Modified in Worktree

- `gmtsar/python/bin_py/snaphu_py/snaphu_solver_numba.py`:
  Bug 1 and Bug 2 already in HEAD. No additional changes.
- `gmtsar/python/bin_py/snaphu_py/snaphu_py.py`:
  Applied scalar Bug 1 fix (apexlist moved to after remount loop).
  This file differs from HEAD only by this fix + pre-existing WrapPhase fix.
